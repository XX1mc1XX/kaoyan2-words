// Cloudflare Pages Functions：账号、会话、进度同步
// 路由前缀 /api/*

const enc = new TextEncoder();
const dec = new TextDecoder();
const SESSION_DAYS = 30;
const MAX_PAYLOAD = 512 * 1024;
// 登录/注册这类小 JSON 不需要大 body；给个上限挡住「一次带 100MB」的请求
const MAX_SMALL_BODY = 8 * 1024;

const JSON_HEADERS = {
  'content-type': 'application/json; charset=utf-8',
  'cache-control': 'no-store',
};

function payloadTooLarge(text) {
  return !text || enc.encode(text).byteLength > MAX_PAYLOAD;
}

function json(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...JSON_HEADERS, ...extra },
  });
}

const hex = buf =>
  [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');

function randomHex(bytes) {
  const a = new Uint8Array(bytes);
  crypto.getRandomValues(a);
  return hex(a.buffer);
}

async function hashPassword(password, saltHex) {
  const salt = new Uint8Array(saltHex.match(/../g).map(h => parseInt(h, 16)));
  const key = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt, iterations: 100000 },
    key,
    256,
  );
  return hex(bits);
}

function cookieFrom(request, name) {
  const raw = request.headers.get('cookie') || '';
  for (const part of raw.split(';')) {
    const i = part.indexOf('=');
    if (i < 0) continue;
    if (part.slice(0, i).trim() === name) {
      // 手工测试或部分客户端会带引号，不去掉就会读不到 token，表现为随机掉登录
      return part.slice(i + 1).trim().replace(/^"|"$/g, '');
    }
  }
  return '';
}

async function currentUser(request, env) {
  const token = cookieFrom(request, 'ky_sid');
  if (!token) return null;
  const row = await env.DB.prepare(
    'SELECT s.user_id, s.expires_at, u.username FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?',
  ).bind(token).first();
  if (!row) return null;
  if (row.expires_at < Date.now()) {
    await env.DB.prepare('DELETE FROM sessions WHERE token = ?').bind(token).run();
    return null;
  }
  return { id: row.user_id, username: row.username, token };
}

function sessionCookie(token, maxAge) {
  return `ky_sid=${token}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=${maxAge}`;
}

// 限流计数：单条 UPSERT 原子自增，避免「先查再改」在并发下同时放行
async function bumpRate(env, key, windowMs) {
  const now = Date.now();
  const end = now + windowMs;
  const row = await env.DB.prepare(
    `INSERT INTO rate (key, n, reset_at) VALUES (?, 1, ?)
     ON CONFLICT(key) DO UPDATE SET
       n = CASE WHEN rate.reset_at < ? THEN 1 ELSE rate.n + 1 END,
       reset_at = CASE WHEN rate.reset_at < ? THEN ? ELSE rate.reset_at END
     RETURNING n`,
  ).bind(key, end, now, now, end).first();
  return row ? row.n : 1;
}

// 同一 IP 在窗口期内超过次数就拒绝
async function allowRate(env, key, limit, windowMs) {
  return (await bumpRate(env, key, windowMs)) <= limit;
}

// Pages 没有定时任务，只能在低频入口顺手清过期数据（一天前的限流行、过期的会话）
async function sweepExpired(env) {
  const now = Date.now();
  await env.DB.batch([
    env.DB.prepare('DELETE FROM rate WHERE reset_at < ?').bind(now - 86400_000),
    env.DB.prepare('DELETE FROM sessions WHERE expires_at < ?').bind(now),
    env.DB.prepare('DELETE FROM pair_codes WHERE expires_at < ?').bind(now),
  ]);
}
const stateHits = new Map();
function stateBudget(key, limit = 400, windowMs = 600000) {
  const now = Date.now();
  const cur = stateHits.get(key);
  if (!cur || cur.resetAt < now) {
    if (stateHits.size > 2000) {
      for (const [entryKey, value] of stateHits) if (value.resetAt <= now) stateHits.delete(entryKey);
      if (stateHits.size > 4000) stateHits.clear();
    }
    stateHits.set(key, { n: 1, resetAt: now + windowMs });
    return true;
  }
  if (cur.n >= limit) return false;
  cur.n += 1;
  return true;
}

const clientIp = request =>
  request.headers.get('cf-connecting-ip') || request.headers.get('x-forwarded-for') || 'unknown';

// 失败锁定：正常请求不查 D1；只有失败时才写一条限流行，既跨 isolate 生效，
// 也避免把高频读取变成每次都要写库。local 锁用来挡住同一 isolate 的连续重试。
const READ_FAILURE_LIMIT = 12;
const READ_FAILURE_WINDOW = 15 * 60_000;
const failureLocks = new Map();

function failureLockActive(key) {
  const lock = failureLocks.get(key);
  if (!lock) return false;
  if (lock.resetAt > Date.now()) return true;
  failureLocks.delete(key);
  return false;
}

async function failureLockRemaining(env, key, limit) {
  const now = Date.now();
  const row = await env.DB.prepare('SELECT n, reset_at FROM rate WHERE key = ?').bind(key).first();
  const resetAt = Number(row?.reset_at || 0);
  const count = Number(row?.n || 0);
  return resetAt > now && count >= limit ? resetAt - now : 0;
}

async function recordFailure(env, key, limit, windowMs) {
  if (failureLockActive(key)) return true;
  const count = await bumpRate(env, key, windowMs);
  if (count < limit) return false;
  failureLocks.set(key, { resetAt: Date.now() + windowMs });
  return true;
}

async function clearFailures(env, key) {
  failureLocks.delete(key);
  await env.DB.prepare('DELETE FROM rate WHERE key = ?').bind(key).run();
}

async function rejectFailedRead(env, key, data, status) {
  const locked = await recordFailure(env, key, READ_FAILURE_LIMIT, READ_FAILURE_WINDOW);
  if (locked) {
    return json({ error: '读取尝试过多，请 15 分钟后再试' }, 429, { 'retry-after': '900' });
  }
  return json(data, status);
}

// 浏览器写请求必须来自本站；Origin 是主防线，Sec-Fetch-Site 作为补充。
// 非浏览器请求缺少两者时仍允许，以兼容 API/测试客户端，但绝不接受明确跨站来源。
function requestOriginAllowed(request, url) {
  const site = (request.headers.get('sec-fetch-site') || '').toLowerCase();
  if (site && site !== 'same-origin' && site !== 'none') return false;
  const origin = request.headers.get('origin');
  if (!origin) return true;
  try {
    const got = new URL(origin);
    return got.protocol === url.protocol && got.host === url.host;
  } catch {
    return false;
  }
}

function isJsonRequest(request) {
  return /^application\/json(?:\s*;|$)/i.test(request.headers.get('content-type') || '');
}

// 读请求体时一边读一边累计大小，超限立刻取消。
// 不能用 request.json()：它会把整个 body 读进内存，一个解压后几百 MB 的
// gzip 请求就足以把 isolate 打 OOM。
// 返回 undefined = 超限（调用方回 413），null = 解析失败（回 400）。
async function readBody(request, limit) {
  const declared = Number(request.headers.get('content-length') || 0);
  if (declared > limit) return undefined;
  if (!request.body) return null;
  const reader = request.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) {
        await reader.cancel();
        return undefined;
      }
      chunks.push(value);
    }
  } catch {
    return null;
  }
  const bytes = new Uint8Array(total);
  let off = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, off);
    off += chunk.byteLength;
  }
  try { return JSON.parse(dec.decode(bytes)); } catch { return null; }
}

async function readJson(request) {
  return readBody(request, MAX_SMALL_BODY);
}

async function readStateBody(request) {
  if ((request.headers.get('x-ky-encoding') || '').toLowerCase() !== 'gzip') {
    return readBody(request, MAX_PAYLOAD);
  }
  const declared = Number(request.headers.get('content-length') || 0);
  // 压缩后就不该接近上限，先挡一道，省得白解压
  if (declared > MAX_PAYLOAD) return undefined;
  if (!request.body) return null;
  let stream;
  try {
    stream = request.body.pipeThrough(new DecompressionStream('gzip'));
  } catch {
    return null;
  }
  // 解压后的字节同样边读边数：先把解压结果整体读进内存正是 gzip bomb 的攻击点
  const reader = stream.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_PAYLOAD) {
        await reader.cancel();
        return undefined;
      }
      chunks.push(value);
    }
  } catch {
    return null;
  }
  const bytes = new Uint8Array(total);
  let off = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, off);
    off += chunk.byteLength;
  }
  try { return JSON.parse(dec.decode(bytes)); } catch { return null; }
}

/*__MERGE__*/

// serverFence 是服务端权威元数据：客户端只能回传，普通 PUT 不能据此改写 fence。
// resetAt 是旧版 clear 的遗留字段，也由顶层 reset/resetAt 协议重新生成。
function withoutClientServerFence(snapshot) {
  const out = copyRecord(snapshot);
  if (!isRecord(out.conf)) return out;
  const conf = copyRecord(out.conf);
  delete conf.serverFenceAt;
  delete conf.serverFenceMode;
  delete conf.serverFenceOperationId;
  delete conf.resetAt;
  delete conf.overwritePending;
  delete conf.overwriteMode;
  delete conf.importStartedAt;
  delete conf.importOperationId;
  delete conf.forceAt;
  out.conf = conf;
  return out;
}


const USER_RE = /^[A-Za-z0-9_一-龥]{3,24}$/;
const AUDIO_WORD_RE = /^[A-Za-z][A-Za-z'-]{1,40}$/;
// 中文释义走百度 TTS：任意中文文本都能合成，英文词典接口只认词条
// 释义里会有「...」「…」「《》」这些符号，漏掉就会让整条中文朗读被判 400 而没声音
const AUDIO_ZH_RE = /^[一-鿿A-Za-z0-9，、。；;:：.…《》\s]{1,60}$/;
const AUDIO_QUERY_KEYS = new Set(['word', 'lang', 'offline', 'v']);
// 音频请求量远高于其它接口，不走 D1 限流（每词一次写库太贵），
// 用 isolate 内的轻量计数挡住随机刷词；命中缓存的请求不计数。
// 额度按「一次全量离线缓存」估算：四本词库三千多词，中英文各一条音频，
// 合计约六千多次请求，上限要能一次跑完。命中缓存的请求不计数。
// 跨站调用由 handleAudio 的 Sec-Fetch-Site 拦在前面，这里只兜随机刷词。
const audioHits = new Map();
function audioBudget(ip) {
  const now = Date.now();
  const cur = audioHits.get(ip);
  if (!cur || cur.resetAt < now) {
    // 先清过期项；只有清完仍然爆表才整体丢弃，避免被少量过期记录逼着清空
    if (audioHits.size > 5000) {
      for (const [key, value] of audioHits) if (value.resetAt <= now) audioHits.delete(key);
      if (audioHits.size > 8000) audioHits.clear();
    }
    audioHits.set(ip, { n: 1, resetAt: now + 600000 });
    return true;
  }
  if (cur.n >= 20000) return false;
  cur.n += 1;
  return true;
}
// 同源代理词典发音：避免浏览器 CORS/混合内容问题，也让 Service Worker 能缓存。
async function handleAudio(request, env, ctx) {
  // 只允许自家页面调用：否则任何站点都能把这个代理当免费的词典发音接口用
  const site = request.headers.get('sec-fetch-site');
  if (site && site !== 'same-origin') return json({ error: '不允许跨站调用' }, 403);
  const url = new URL(request.url);
  if (!requestOriginAllowed(request, url)) return json({ error: 'cross-site denied' }, 403);
  const word = url.searchParams.get('word') || '';
  const isZh = url.searchParams.get('lang') === 'zh';
  if (isZh ? !AUDIO_ZH_RE.test(word) : !AUDIO_WORD_RE.test(word)) {
    return json({ error: '发音词格式不对' }, 400);
  }

  // v 是前端缓存版本号；offline/v 都只影响请求方式，不能进入音频缓存键。
  // 只接受协议参数并拒绝重复项，避免随机参数或重复参数制造无限缓存键。
  const seen = new Set();
  for (const key of url.searchParams.keys()) {
    if (!AUDIO_QUERY_KEYS.has(key) || seen.has(key)) return json({ error: '参数不合法' }, 400);
    seen.add(key);
  }
  const cacheUrl = new URL('/api/audio', url.origin);
  cacheUrl.searchParams.set('word', word);
  if (isZh) cacheUrl.searchParams.set('lang', 'zh');
  const cacheKey = new Request(cacheUrl.toString());
  if (request.method === 'GET' || request.method === 'HEAD') {
    const hit = await caches.default.match(cacheKey);
    if (hit) return request.method === 'HEAD' ? new Response(null, { headers: hit.headers }) : hit;
  }
  const ip = request.headers.get('cf-connecting-ip') || 'unknown';
  if (!audioBudget(ip)) return json({ error: '请求过于频繁，请稍后再试' }, 429);

  try {
    const target = isZh
      ? 'https://fanyi.baidu.com/gettts?lan=zh&text=' + encodeURIComponent(word) + '&spd=7&source=web'
      : 'https://dict.youdao.com/dictvoice?audio=' + encodeURIComponent(word) + '&type=2';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    let upstream;
    try {
      upstream = await fetch(target, {
        signal: controller.signal,
        headers: isZh
          ? { 'user-agent': 'Mozilla/5.0', 'referer': 'https://fanyi.baidu.com/' }
          : { 'user-agent': 'Mozilla/5.0', 'referer': 'https://dict.youdao.com/' },
        cf: { cacheEverything: true, cacheTtl: 31536000 },
      });
    } finally {
      clearTimeout(timer);
    }
    const type = upstream.headers.get('content-type') || '';
    const rawLength = upstream.headers.get('content-length');
    const declaredLength = rawLength === null ? null : Number(rawLength.trim());
    // 只有上游明确声明 Content-Length: 0 才是空包；chunked 响应没有该头，不能误判成 0。
    if (rawLength !== null && rawLength.trim() === '0') {
      return json({ error: '音频内容为空' }, 502);
    }
    if (declaredLength !== null && Number.isFinite(declaredLength) && declaredLength > 2 * 1024 * 1024) {
      return json({ error: '音频文件过大' }, 502);
    }
    if (!upstream.ok || !type.startsWith('audio/')) {
      return json({ error: '在线发音暂时不可用' }, 502);
    }
    const headers = {
      'content-type': type,
      'cache-control': 'public, max-age=31536000, immutable',
    };
    if (rawLength !== null) headers['content-length'] = rawLength;
    if (request.method === 'HEAD') return new Response(null, { status: 200, headers });
    const response = new Response(upstream.body, { status: 200, headers });
    if (ctx && typeof ctx.waitUntil === 'function') {
      ctx.waitUntil(caches.default.put(cacheKey, response.clone()));
    }
    return response;
  } catch {
    return json({ error: '在线发音加载失败' }, 502);
  }
}

// 健康检查必须真的碰一下 D1；只检查 env.DB 是否存在无法发现绑定失效或查询故障。
async function handleHealth(request, env) {
  if (!stateBudget('health:' + clientIp(request), 60, 60_000)) {
    const headers = { 'cache-control': 'no-store', 'retry-after': '60' };
    return request.method === 'HEAD'
      ? new Response(null, { status: 429, headers })
      : json({ error: '健康检查太频繁，请稍后再试' }, 429, headers);
  }

  let healthy = false;
  try {
    const row = env.DB ? await env.DB.prepare('SELECT 1 AS ok').first() : null;
    healthy = !!row && Number(row.ok) === 1;
  } catch (e) {
    console.error('[health] D1 check failed', e);
  }
  if (request.method === 'HEAD') {
    return new Response(null, { status: healthy ? 200 : 503, headers: { 'cache-control': 'no-store' } });
  }
  return json({ ok: healthy, database: healthy }, healthy ? 200 : 503, { 'cache-control': 'no-store' });
}

async function handleApi(request, env, ctx) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, '').replace(/^\/api/, '') || '/';
  const method = request.method;
  if (method !== 'GET' && method !== 'HEAD' && !requestOriginAllowed(request, url)) {
    return json({ error: '请求来源不合法' }, 403);
  }

  if (path === '/audio' && (method === 'GET' || method === 'HEAD')) return handleAudio(request, env, ctx);
  if (path === '/health' && (method === 'GET' || method === 'HEAD')) return handleHealth(request, env);
  if (!env.DB) return json({ error: '数据库未绑定' }, 500);

  try {
    // 微信扫码登录：需要微信开放平台「网站应用」资质（企业主体 + 认证费）
    if (path === '/wx' && method === 'GET') {
      // 扫码登录的回调（code 换 token、绑定 or 建号）还没实现。
      // 只要配了 appid 就放出去，用户会被跳到微信授权页、回来却什么也不发生。
      return json({ enabled: false, hint: '微信扫码登录尚未接入回调，暂不可用' });
    }

    if (path === '/register' && method === 'POST') {
      if (!isJsonRequest(request)) return json({ error: '请求格式不对' }, 415);
      if (!(await allowRate(env, 'reg:' + clientIp(request), 5, 3600_000))) {
        return json({ error: '注册太频繁，请稍后再试' }, 429);
      }
      await sweepExpired(env);
      const body = await readJson(request);
      if (body === undefined) return json({ error: '请求内容过大' }, 413);
      const username = typeof body?.username === 'string' ? body.username.trim() : '';
      const password = typeof body?.password === 'string' ? body.password : '';
      if (!USER_RE.test(username)) return json({ error: '用户名需 3-24 位字母、数字、下划线或中文' }, 400);
      if (password.length < 6 || password.length > 72) return json({ error: '密码需 6-72 位' }, 400);
      // 用户名按不区分大小写判重，避免 Alice / alice 视觉上互相冒充。
      // COLLATE NOCASE 能走唯一索引；LOWER() 用不上索引，并发下也挡不住两个都插进去。
      const exists = await env.DB.prepare('SELECT id FROM users WHERE username = ? COLLATE NOCASE').bind(username).first();
      if (exists) return json({ error: '用户名已被占用' }, 409);
      const salt = randomHex(16);
      const hash = await hashPassword(password, salt);
      const now = Date.now();
      let res;
      try {
        res = await env.DB.prepare(
          'INSERT INTO users (username, pass_hash, pass_salt, created_at) VALUES (?, ?, ?, ?)',
        ).bind(username, hash, salt, now).run();
      } catch (e) {
        // 并发注册同名会撞 UNIQUE，这里回 409 而不是 500
        if (String(e?.message || e).includes('UNIQUE')) return json({ error: '用户名已被占用' }, 409);
        throw e;
      }
      const userId = res.meta?.last_row_id;
      const token = randomHex(24);
      const exp = now + SESSION_DAYS * 86400_000;
      await env.DB.prepare('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)')
        .bind(token, userId, exp).run();
      return json({ ok: true, username }, 200, {
        'set-cookie': sessionCookie(token, SESSION_DAYS * 86400),
      });
    }

    if (path === '/login' && method === 'POST') {
      if (!isJsonRequest(request)) return json({ error: '请求格式不对' }, 415);
      if (!(await allowRate(env, 'login:' + clientIp(request), 30, 600_000))) {
        return json({ error: '登录尝试太频繁，请 10 分钟后再试' }, 429);
      }
      await sweepExpired(env);
      const body = await readJson(request);
      if (body === undefined) return json({ error: '请求内容过大' }, 413);
      const username = typeof body?.username === 'string' ? body.username.trim() : '';
      const password = typeof body?.password === 'string' ? body.password : '';
      if (!username || !password) return json({ error: '用户名或密码不对' }, 401);
      // 失败锁定按「IP + 账号」计数：只按账号计数会让任何人靠故意输错把别人锁死，
      // 15 分钟一次地重复等于永久锁。
      const failKey = 'loginfail:' + clientIp(request) + ':' + username.toLowerCase();
      // 再留一道账号级上限，只统计失败次数且阈值放高，挡住换 IP 无限试同一个账号
      const acctKey = 'loginacct:' + username.toLowerCase();
      const failRow = await env.DB.prepare('SELECT n, reset_at FROM rate WHERE key = ?').bind(failKey).first();
      if (failRow && failRow.reset_at > Date.now() && failRow.n >= 10) {
        return json({ error: '尝试次数过多，请 15 分钟后再试' }, 429);
      }
      const row = await env.DB.prepare(
        'SELECT id, username, pass_hash, pass_salt FROM users WHERE username = ? COLLATE NOCASE',
      ).bind(username).first();
      // 用户不存在时也跑一遍同样开销的哈希，避免靠响应时间探测账号是否存在
      const salt = row ? row.pass_salt : '00000000000000000000000000000000';
      const hash = await hashPassword(password, salt);
      if (!row || hash !== row.pass_hash) {
        await bumpRate(env, failKey, 15 * 60_000);
        const acctFails = await bumpRate(env, acctKey, 15 * 60_000);
        if (acctFails > 200) return json({ error: '这个账号尝试次数过多，请 15 分钟后再试' }, 429);
        return json({ error: '用户名或密码不对' }, 401);
      }
      await env.DB.prepare('DELETE FROM rate WHERE key IN (?, ?)').bind(failKey, acctKey).run();
      const token = randomHex(24);
      const exp = Date.now() + SESSION_DAYS * 86400_000;
      await env.DB.prepare('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)')
        .bind(token, row.id, exp).run();
      return json({ ok: true, username: row.username }, 200, {
        'set-cookie': sessionCookie(token, SESSION_DAYS * 86400),
      });
    }

    if (path === '/logout' && method === 'POST') {
      const user = await currentUser(request, env);
      const body = await readJson(request);
      const expectedUser = typeof body?.expectedUsername === 'string' ? body.expectedUsername.trim() : '';
      if (user && expectedUser && user.username.toLowerCase() !== expectedUser.toLowerCase()) {
        return json({ error: '账号已切换，请重新打开页面', code: 'ACCOUNT_MISMATCH' }, 409);
      }
      if (user) await env.DB.prepare('DELETE FROM sessions WHERE token = ?').bind(user.token).run();
      return json({ ok: true }, 200, { 'set-cookie': sessionCookie('', 0) });
    }

    if (path === '/me' && method === 'GET') {
      if (!stateBudget('read:me:' + clientIp(request), 120, 60_000)) {
        return json({ error: '请求过于频繁，请稍后再试' }, 429, { 'retry-after': '60' });
      }
      const user = await currentUser(request, env);
      return json({ user: user ? { username: user.username } : null });
    }

    // 前端错误上报：只进 Worker 日志，不落库、不回错误码，
    // 免得前端为了上报再产生一层失败重试。
    if (path === '/log' && method === 'POST') {
      if (!(await allowRate(env, 'log:' + clientIp(request), 20, 60_000))) return json({ ok: true });
      const body = await readJson(request);
      if (body && typeof body.message === 'string') {
        const clip = v => String(v == null ? '' : v).replace(/[\r\n]+/g, ' ').slice(0, 400);
        console.error('[client]', clip(body.message), clip(body.source), clip(body.stack));
      }
      return json({ ok: true });
    }

    // 配对码：电脑已登录后生成 6 位码，手机输入即登录同一账号
    if (path === '/pair/new' && method === 'POST') {
      if (!stateBudget('pair-new:' + clientIp(request), 30, 60_000)) {
        return json({ error: '生成配对码太频繁，请稍后再试' }, 429, { 'retry-after': '60' });
      }
      const user = await currentUser(request, env);
      if (!user) return json({ error: '未登录' }, 401);
      // 已登录用户也会消耗 D1 写入；按账号限制，避免刷新页面就无限换码。
      if (!(await allowRate(env, 'pairnew:' + user.id, 5, 600_000))) {
        return json({ error: '生成配对码太频繁，请 10 分钟后再试' }, 429, { 'retry-after': '600' });
      }
      const now = Date.now();
      let code = '';
      for (let i = 0; i < 6 && !code; i++) {
        const buf = new Uint8Array(4);
        crypto.getRandomValues(buf);
        const candidate = String((new DataView(buf.buffer).getUint32(0) % 900000) + 100000);
        const dup = await env.DB.prepare('SELECT code FROM pair_codes WHERE code = ?').bind(candidate).first();
        if (!dup) code = candidate;
      }
      if (!code) return json({ error: '生成配对码失败，请重试' }, 503);
      const expiresAt = now + 5 * 60 * 1000;
      // 清旧码 + 插新码放同一批次，避免并发下留下多个有效码
      await env.DB.batch([
        env.DB.prepare('DELETE FROM pair_codes WHERE expires_at < ?').bind(now),
        env.DB.prepare('DELETE FROM pair_codes WHERE user_id = ?').bind(user.id),  // 同时只留一个有效码
        env.DB.prepare('INSERT INTO pair_codes (code, user_id, expires_at) VALUES (?, ?, ?)')
          .bind(code, user.id, expiresAt),
      ]);
      return json({ code, expiresAt });
    }

    if (path === '/pair/claim' && method === 'POST') {
      if (!isJsonRequest(request)) return json({ error: '请求格式不对' }, 415);
      const ip = clientIp(request);
      const failKey = 'pairfail:' + ip;
      const lockedFor = await failureLockRemaining(env, failKey, 5);
      if (lockedFor > 0) {
        return json({ error: '配对尝试次数过多，请 15 分钟后再试' }, 429, {
          'retry-after': String(Math.max(1, Math.ceil(lockedFor / 1000))),
        });
      }
      // 6 位码 + 5 分钟有效期：先限制总尝试次数，再用独立失败次数触发 15 分钟锁定。
      if (!(await allowRate(env, 'pair:' + ip, 6, 600_000))) {
        return json({ error: '尝试太频繁，请 10 分钟后再试' }, 429, { 'retry-after': '600' });
      }
      const failClaim = async (data, status) => {
        const locked = await recordFailure(env, failKey, 5, 15 * 60_000);
        return locked
          ? json({ error: '配对尝试次数过多，请 15 分钟后再试' }, 429, { 'retry-after': '900' })
          : json(data, status);
      };
      const body = await readJson(request);
      if (body === undefined) return json({ error: '请求内容过大' }, 413);
      const code = String(body?.code || '').trim();
      if (!/^\d{6}$/.test(code)) return failClaim({ error: '配对码是 6 位数字' }, 400);
      // 先删再签：只有真正删掉这一行的请求才发 session，并发提交同一码不会签出两个
      const claimed = await env.DB.prepare(
        'DELETE FROM pair_codes WHERE code = ? AND expires_at >= ? RETURNING user_id',
      ).bind(code, Date.now()).first();
      if (!claimed) return failClaim({ error: '配对码无效或已过期' }, 400);
      const u = await env.DB.prepare('SELECT username FROM users WHERE id = ?').bind(claimed.user_id).first();
      const token = randomHex(24);
      const exp = Date.now() + SESSION_DAYS * 86400_000;
      await env.DB.prepare('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)')
        .bind(token, claimed.user_id, exp).run();
      await clearFailures(env, failKey);
      return json({ ok: true, username: u.username }, 200, {
        'set-cookie': sessionCookie(token, SESSION_DAYS * 86400),
      });
    }

    if (path === '/state/sync' && method === 'POST') {
      const token = cookieFrom(request, 'ky_sid');
      if (!token) return json({ error: '未登录' }, 401);
      if (!stateBudget('sync:' + clientIp(request))) {
        return json({ error: '同步太频繁，请稍后再试' }, 429);
      }
      const body = await readStateBody(request);
      if (body === undefined) return json({ error: '进度数据过大' }, 413);
      if (!body || !isRecord(body.payload)) {
        return json({ error: '数据格式不对' }, 400);
      }
      // 体积上限在 readStateBody 里已经按解压后的字节数卡过，这里不必再序列化一遍。
      // 客户端做过「清空全部 / 导入覆盖」时带上 reset：云端独有的键只有服务端知道，
      // 墓碑必须由服务端在这一份云端快照上生成，否则别的设备背过的词会原样活过来。
      const wantsReset = body.reset === true;
      const expectedUser = typeof body.expectedUsername === 'string' ? body.expectedUsername.trim() : '';
      if (!expectedUser) return json({ error: '缺少账号校验', code: 'EXPECTED_USER_REQUIRED' }, 428);

      // 首次登录/冲突后的权威合并：一次请求完成读取、合并、写回。
      for (let attempt = 0; attempt < 2; attempt++) {
        const row = await env.DB.prepare(
          'SELECT s.user_id, s.expires_at, u.username, p.payload, p.updated_at ' +
          'FROM sessions s JOIN users u ON u.id = s.user_id ' +
          'LEFT JOIN progress p ON p.user_id = s.user_id ' +
          'WHERE s.token = ?',
        ).bind(token).first();
        if (!row || Number(row.expires_at) < Date.now()) return json({ error: '未登录' }, 401);
        if (String(row.username).toLowerCase() !== expectedUser.toLowerCase()) {
          return json({ error: '账号已切换，请重新打开页面', code: 'ACCOUNT_MISMATCH' }, 409);
        }
        const now = Date.now();
        let remote = null;
        if (row.payload) {
          try { remote = JSON.parse(row.payload); }
          catch { return json({ error: '云端进度损坏' }, 500); }
        }
        // 客户端快照只提供进度数据；fence 必须由云端状态和本次服务端时间生成。
        // reset/import 由共享 destructive 入口处理，普通同步由 mergeSyncSnapshot 套用云端 fence。
        const local = withoutClientServerFence(body.payload);
        const mergeOptions = {
          reset: wantsReset,
          mode: body.mode === 'import' ? 'import' : 'clear',
          resetAt: body.resetAt,
          importStartedAt: body.importStartedAt,
          operationId: body.operationId,
          now,
        };
        const merged = wantsReset
          ? mergeDestructiveSnapshot(local, remote, mergeOptions)
          : mergeSyncSnapshot(local, remote, mergeOptions);
        // 入库的都是键排序后的规范形态，所以「合并结果 vs 已存文本」可以逐字节比较：
        // 用原始键序比较会让两台设备交替同步时每次都判定「有变化」，
        // 于是每轮都重写 updated_at，另一台的 since 轮询永远失效。
        const mergedText = stableJson(merged);
        if (payloadTooLarge(mergedText)) return json({ error: '进度数据过大' }, 413);
        if (row.payload && mergedText === row.payload) {
          return json({ ok: true, payload: remote, updatedAt: row.updated_at, merged: false });
        }
        if (!row.payload) {
          // 首次同步没有云端基线，也先跑共享合并：clear/import 会在这里生成首批 fence。
          const inserted = await env.DB.prepare(
            'INSERT INTO progress (user_id, payload, updated_at) VALUES (?, ?, ?) ' +
            'ON CONFLICT(user_id) DO NOTHING RETURNING updated_at',
          ).bind(row.user_id, mergedText, now).first();
          if (inserted) {
            return json({ ok: true, payload: merged, updatedAt: inserted.updated_at, merged: wantsReset });
          }
          continue;
        }
        // updated_at 同时当乐观锁版本号用，必须严格单调：
        // 同一毫秒的两台设备否则会双双写入成功，另一边的增量轮询也会漏更新。
        const updated = await env.DB.prepare(
          'UPDATE progress SET payload = ?, updated_at = MAX(?, updated_at + 1) ' +
          'WHERE user_id = ? AND updated_at = ? RETURNING updated_at',
        ).bind(mergedText, now, row.user_id, row.updated_at).first();
        if (updated) {
          return json({ ok: true, payload: merged, updatedAt: updated.updated_at, merged: true });
        }
      }
      return json({ error: 'conflict' }, 409);
    }

    if (path === '/state') {
      const isRead = method === 'GET';
      if (isRead && !stateBudget('read:state:' + clientIp(request), 120, 60_000)) {
        return json({ error: '读取进度太频繁，请稍后再试' }, 429, { 'retry-after': '60' });
      }
      const token = cookieFrom(request, 'ky_sid');
      const failKey = 'readfail:state:' + clientIp(request);
      if (isRead && failureLockActive(failKey)) {
        return json({ error: '读取尝试过多，请 15 分钟后再试' }, 429, { 'retry-after': '900' });
      }
      if (!token) {
        return isRead
          ? rejectFailedRead(env, failKey, { error: '未登录' }, 401)
          : json({ error: '未登录' }, 401);
      }

      if (isRead) {
        // 一次查询同时完成会话校验和进度读取，避免原来两次 D1 往返。
        const row = await env.DB.prepare(
          'SELECT s.expires_at, u.username, p.payload, p.updated_at ' +
          'FROM sessions s JOIN users u ON u.id = s.user_id ' +
          'LEFT JOIN progress p ON p.user_id = s.user_id ' +
          'WHERE s.token = ?',
        ).bind(token).first();
        if (!row || Number(row.expires_at) < Date.now()) {
          return rejectFailedRead(env, failKey, { error: '未登录' }, 401);
        }
        const expectedUser = (url.searchParams.get('expectedUsername') || '').trim();
        if (!expectedUser) {
          return rejectFailedRead(env, failKey, { error: '缺少账号校验', code: 'EXPECTED_USER_REQUIRED' }, 428);
        }
        if (String(row.username).toLowerCase() !== expectedUser.toLowerCase()) {
          return rejectFailedRead(env, failKey, { error: '账号已切换，请重新打开页面', code: 'ACCOUNT_MISMATCH' }, 409);
        }
        const updatedAt = Number(row.updated_at || 0);
        if (!row.payload) return json({ payload: null, updatedAt: 0 });
        // 轮询时只带 since：云端没变化就不返回整份进度。
        const since = Number(url.searchParams.get('since') || 0);
        if (since > 0 && updatedAt <= since) return json({ unchanged: true, updatedAt });
        return json({ payload: JSON.parse(row.payload), updatedAt });
      }

      if (method === 'PUT' || method === 'POST') {
        const body = await readStateBody(request);
        if (body === undefined) return json({ error: '进度数据过大' }, 413);
        if (!body || !isRecord(body.payload)) {
          return json({ error: '数据格式不对' }, 400);
        }
        const expectedUser = typeof body.expectedUsername === 'string' ? body.expectedUsername.trim() : '';
        if (!expectedUser) return json({ error: '缺少账号校验', code: 'EXPECTED_USER_REQUIRED' }, 428);
        if (!stateBudget('state:' + clientIp(request))) {
          return json({ error: '同步太频繁，请稍后再试' }, 429);
        }
        const local = withoutClientServerFence(body.payload);
        const now = Date.now();
        // 先读云端 fence 再合并：普通 PUT 不能拿客户端 serverFence 当权威，
        // 也不能因为旧页面回传缺字段就把服务端 fence 抹掉。
        const current = await env.DB.prepare(
          'SELECT s.expires_at, u.username, p.payload, p.updated_at ' +
          'FROM sessions s JOIN users u ON u.id = s.user_id ' +
          'LEFT JOIN progress p ON p.user_id = s.user_id ' +
          'WHERE s.token = ?',
        ).bind(token).first();
        if (!current || Number(current.expires_at) < Date.now()) return json({ error: '未登录' }, 401);
        if (String(current.username).toLowerCase() !== expectedUser.toLowerCase()) {
          return json({ error: '账号已切换，请重新打开页面', code: 'ACCOUNT_MISMATCH' }, 409);
        }
        let remote = null;
        if (current.payload) {
          try { remote = JSON.parse(current.payload); }
          catch { return json({ error: '云端进度损坏' }, 500); }
        }
        const merged = mergeSyncSnapshot(local, remote, { reset: false, mode: 'clear', now });
        const text = stableJson(merged);
        if (payloadTooLarge(text)) return json({ error: '进度数据过大' }, 413);
        if (current.payload && text === current.payload) {
          return json({ ok: true, updatedAt: current.updated_at, merged: false });
        }

        // 乐观锁 + 写入合并成一条 SQL：常见情况下一次 D1 往返完成同步。
        const base = Math.max(0, Number(body.baseUpdatedAt || 0));
        // 没有 baseUpdatedAt 的旧客户端不能走 force：一次旧缓存页面就可能覆盖
        // 另一台设备刚合并的进度。没有版本基线时宁可返回 409 让客户端升级/重新合并。
        const force = body.force === true;
        // updated_at 兼作乐观锁版本号，写入时必须严格单调，
        // 否则同一毫秒的两台设备会同时写成功，另一边的增量轮询也会漏更新。
        const written = await env.DB.prepare(
          'INSERT INTO progress (user_id, payload, updated_at) ' +
          'SELECT s.user_id, ?, ? ' +
          'FROM sessions s JOIN users u ON u.id = s.user_id ' +
          'WHERE s.token = ? AND u.username = ? COLLATE NOCASE AND s.expires_at >= ? ' +
          'ON CONFLICT(user_id) DO UPDATE SET ' +
          'payload = excluded.payload, ' +
          'updated_at = MAX(excluded.updated_at, progress.updated_at + 1) ' +
          'WHERE ? = 1 OR progress.updated_at <= ? ' +
          'RETURNING updated_at',
        ).bind(text, now, token, expectedUser, now, force ? 1 : 0, base).first();
        if (written) return json({ ok: true, updatedAt: written.updated_at });

        // 没写成功通常是版本冲突；把云端最新数据一起返回，客户端一次合并后重试。
        const row = await env.DB.prepare(
          'SELECT s.expires_at, u.username, p.payload, p.updated_at ' +
          'FROM sessions s JOIN users u ON u.id = s.user_id ' +
          'LEFT JOIN progress p ON p.user_id = s.user_id ' +
          'WHERE s.token = ?',
        ).bind(token).first();
        if (!row || Number(row.expires_at) < Date.now()) return json({ error: '未登录' }, 401);
        if (String(row.username).toLowerCase() !== expectedUser.toLowerCase()) return json({ error: '账号已切换，请重新打开页面', code: 'ACCOUNT_MISMATCH' }, 409);
        let payload = null;
        try { payload = row.payload ? JSON.parse(row.payload) : null; } catch {}
        return json({ error: 'conflict', updatedAt: Number(row.updated_at || 0), payload }, 409);
      }
    }

    return json({ error: '没有这个接口' }, 404);
  } catch (e) {
    // 不把 SQL 错误、上游异常原文回给客户端
    console.error(e);
    return json({ error: '服务器内部错误，请稍后再试' }, 500);
  }
}

// Pages 高级模式：/api/* 走后端，其余交给静态资源
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
      return handleApi(request, env, ctx);
    }
    const asset = await env.ASSETS.fetch(request);
    const type = asset.headers.get('content-type') || '';
    if (type.includes('text/html')) {
      // HTML 每次都向服务器确认，避免手机长期加载旧版本
      const copy = new Response(asset.body, asset);
      copy.headers.set('cache-control', 'no-cache, must-revalidate');
      return copy;
    }
    return asset;
  },
};
