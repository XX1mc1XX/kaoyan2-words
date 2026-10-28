// Cloudflare Pages Functions：账号、会话、进度同步
// 路由前缀 /api/*

const enc = new TextEncoder();
const SESSION_DAYS = 30;
const MAX_PAYLOAD = 512 * 1024;

const JSON_HEADERS = {
  'content-type': 'application/json; charset=utf-8',
  'cache-control': 'no-store',
};

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
    if (part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
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
function stateBudget(ip) {
  const now = Date.now();
  const cur = stateHits.get(ip);
  if (!cur || cur.resetAt < now) {
    if (stateHits.size > 2000) {
      for (const [key, value] of stateHits) if (value.resetAt <= now) stateHits.delete(key);
      if (stateHits.size > 4000) stateHits.clear();
    }
    stateHits.set(ip, { n: 1, resetAt: now + 600000 });
    return true;
  }
  if (cur.n >= 400) return false;
  cur.n += 1;
  return true;
}

const clientIp = request =>
  request.headers.get('cf-connecting-ip') || request.headers.get('x-forwarded-for') || 'unknown';

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

async function readStateBody(request) {
  if ((request.headers.get('x-ky-encoding') || '').toLowerCase() !== 'gzip') return readJson(request);
  try {
    const stream = request.body.pipeThrough(new DecompressionStream('gzip'));
    return await new Response(stream, { headers: { 'content-type': 'application/json' } }).json();
  } catch {
    return null;
  }
}

function mergeState(local, cloud) {
  const out = {};
  const keys = new Set([...Object.keys(local || {}), ...Object.keys(cloud || {})]);
  for (const k of keys) {
    const a = (local || {})[k];
    const b = (cloud || {})[k];
    if (!a) { out[k] = b; continue; }
    if (!b) { out[k] = a; continue; }
    const ta = a.t || 0, tb = b.t || 0;
    if (tb !== ta) { out[k] = tb > ta ? b : a; continue; }
    if (a.mastered !== b.mastered) { out[k] = a.mastered ? a : b; continue; }
    out[k] = { ...a, w: Math.max(a.w || 0, b.w || 0), due: Math.max(a.due || 0, b.due || 0) };
  }
  return out;
}

function mergeChapters(local, cloud) {
  const out = {};
  const keys = new Set([...Object.keys(local || {}), ...Object.keys(cloud || {})]);
  for (const k of keys) {
    const a = (local || {})[k];
    const b = (cloud || {})[k];
    if (!a) { out[k] = b; continue; }
    if (!b) { out[k] = a; continue; }
    const ta = a.t || 0, tb = b.t || 0;
    if (ta !== tb) { out[k] = tb > ta ? b : a; continue; }
    const pa = (a.order || []).length ? (a.pos || 0) : 0;
    const pb = (b.order || []).length ? (b.pos || 0) : 0;
    out[k] = pa >= pb ? a : b;
  }
  return out;
}

function latestChapterTime(chapterData) {
  let latest = 0;
  for (const rec of Object.values(chapterData || {})) {
    latest = Math.max(latest, Number(rec && rec.t) || 0);
  }
  return latest;
}
function mergeConf(local, cloud, localChapters, cloudChapters) {
  const a = local || {};
  const b = cloud || {};
  // conf.progressAt 是用户“切库/切章/翻词”动作的权威时间；
  // 章节记录里的 t 会包含程序化恢复，不能拿来反推当前该用哪本词书。
  let localAt = Number(a.progressAt) || 0;
  let cloudAt = Number(b.progressAt) || 0;
  if (!localAt && !cloudAt) {
    // 兼容旧数据：只有完全没有位置时间时，才退回章节活动时间。
    localAt = latestChapterTime(localChapters);
    cloudAt = latestChapterTime(cloudChapters);
  }
  const localForce = Number(a.forceAt) || 0;
  const cloudForce = Number(b.forceAt) || 0;
  const chooseCloud = cloudForce > localForce || (cloudForce === localForce && cloudAt >= localAt);
  const winner = chooseCloud ? b : a;
  const other = chooseCloud ? a : b;
  const deck = winner.deck || other.deck || 'core';
  return {
    ...other,
    ...winner,
    deck,
    chapter: Number(winner.chapter ?? (winner.deckChapter || {})[deck] ?? 0) || 0,
    deckChapter: { ...(other.deckChapter || {}), ...(winner.deckChapter || {}) },
    progressAt: Math.max(localAt, cloudAt),
  };
}
function mergeSnapshots(local, cloud) {
  const localForce = (local.conf && local.conf.forceAt) || 0;
  const cloudForce = (cloud.conf && cloud.conf.forceAt) || 0;
  if (cloudForce > localForce) {
    return { state: cloud.state || {}, chapterData: cloud.chapterData || {}, conf: cloud.conf };
  }
  return {
    state: mergeState(local.state, cloud.state),
    chapterData: mergeChapters(local.chapterData, cloud.chapterData),
    conf: mergeConf(local.conf, cloud.conf, local.chapterData, cloud.chapterData),
  };
}


const USER_RE = /^[A-Za-z0-9_一-龥]{3,24}$/;
const AUDIO_WORD_RE = /^[A-Za-z][A-Za-z'-]{1,40}$/;
// 音频请求量远高于其它接口，不走 D1 限流（每词一次写库太贵），
// 用 isolate 内的轻量计数挡住随机刷词；命中缓存的请求不计数。
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
  if (cur.n >= 400) return false;
  cur.n += 1;
  return true;
}
// 同源代理词典发音：避免浏览器 CORS/混合内容问题，也让 Service Worker 能缓存。
async function handleAudio(request, env, ctx) {
  const url = new URL(request.url);
  const word = url.searchParams.get('word') || '';
  if (!AUDIO_WORD_RE.test(word)) return json({ error: '发音词格式不对' }, 400);

  const cacheKey = new Request(url.toString());
  if (request.method === 'GET') {
    const hit = await caches.default.match(cacheKey);
    if (hit) return hit;
  }
  const ip = request.headers.get('cf-connecting-ip') || 'unknown';
  if (!audioBudget(ip)) return json({ error: '请求过于频繁，请稍后再试' }, 429);

  try {
    const target = 'https://dict.youdao.com/dictvoice?audio=' + encodeURIComponent(word) + '&type=2';
    const upstream = await fetch(target, {
      headers: { 'user-agent': 'Mozilla/5.0', 'referer': 'https://dict.youdao.com/' },
      cf: { cacheEverything: true, cacheTtl: 31536000 },
    });
    const type = upstream.headers.get('content-type') || '';
    if (!upstream.ok || !type.startsWith('audio/')) {
      return json({ error: '在线发音暂时不可用' }, 502);
    }
    const headers = {
      'content-type': type,
      'cache-control': 'public, max-age=31536000, immutable',
    };
    const length = upstream.headers.get('content-length');
    if (length) headers['content-length'] = length;
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

async function handleApi(request, env, ctx) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, '').replace(/^\/api/, '') || '/';
  const method = request.method;

  if (path === '/audio' && (method === 'GET' || method === 'HEAD')) return handleAudio(request, env, ctx);
  if (!env.DB) return json({ error: '数据库未绑定' }, 500);

  try {
    // 微信扫码登录：需要微信开放平台「网站应用」资质（企业主体 + 认证费）
    if (path === '/wx' && method === 'GET') {
      const appid = env.WX_APPID || '';
      return json({
        enabled: !!appid,
        appid,
        hint: appid ? '' : '需微信开放平台网站应用资质（企业主体），未配置时不可用',
      });
    }

    if (path === '/register' && method === 'POST') {
      if (!(await allowRate(env, 'reg:' + clientIp(request), 5, 3600_000))) {
        return json({ error: '注册太频繁，请稍后再试' }, 429);
      }
      await sweepExpired(env);
      const body = await readJson(request);
      const username = typeof body?.username === 'string' ? body.username.trim() : '';
      const password = typeof body?.password === 'string' ? body.password : '';
      if (!USER_RE.test(username)) return json({ error: '用户名需 3-24 位字母、数字、下划线或中文' }, 400);
      if (password.length < 6 || password.length > 72) return json({ error: '密码需 6-72 位' }, 400);
      // 用户名按不区分大小写判重，避免 Alice / alice 视觉上互相冒充
      const exists = await env.DB.prepare('SELECT id FROM users WHERE LOWER(username) = LOWER(?)').bind(username).first();
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
      if (!(await allowRate(env, 'login:' + clientIp(request), 30, 600_000))) {
        return json({ error: '登录尝试太频繁，请 10 分钟后再试' }, 429);
      }
      await sweepExpired(env);
      const body = await readJson(request);
      const username = typeof body?.username === 'string' ? body.username.trim() : '';
      const password = typeof body?.password === 'string' ? body.password : '';
      if (!username || !password) return json({ error: '用户名或密码不对' }, 401);
      // 账号级失败锁定：换 IP 也不能对同一个账号一直试
      const failKey = 'loginfail:' + username.toLowerCase();
      const failRow = await env.DB.prepare('SELECT n, reset_at FROM rate WHERE key = ?').bind(failKey).first();
      if (failRow && failRow.reset_at > Date.now() && failRow.n >= 10) {
        return json({ error: '这个账号尝试次数过多，请 15 分钟后再试' }, 429);
      }
      const row = await env.DB.prepare(
        'SELECT id, username, pass_hash, pass_salt FROM users WHERE LOWER(username) = LOWER(?)',
      ).bind(username).first();
      // 用户不存在时也跑一遍同样开销的哈希，避免靠响应时间探测账号是否存在
      const salt = row ? row.pass_salt : '00000000000000000000000000000000';
      const hash = await hashPassword(password, salt);
      if (!row || hash !== row.pass_hash) {
        await bumpRate(env, failKey, 15 * 60_000);
        return json({ error: '用户名或密码不对' }, 401);
      }
      if (failRow) await env.DB.prepare('DELETE FROM rate WHERE key = ?').bind(failKey).run();
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
      if (user) await env.DB.prepare('DELETE FROM sessions WHERE token = ?').bind(user.token).run();
      return json({ ok: true }, 200, { 'set-cookie': sessionCookie('', 0) });
    }

    if (path === '/me' && method === 'GET') {
      const user = await currentUser(request, env);
      return json({ user: user ? { username: user.username } : null });
    }

    // 配对码：电脑已登录后生成 6 位码，手机输入即登录同一账号
    if (path === '/pair/new' && method === 'POST') {
      const user = await currentUser(request, env);
      if (!user) return json({ error: '未登录' }, 401);
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
      if (!(await allowRate(env, 'pair:' + clientIp(request), 10, 600_000))) {
        return json({ error: '尝试太频繁，请 10 分钟后再试' }, 429);
      }
      const body = await readJson(request);
      const code = String(body?.code || '').trim();
      if (!/^\d{6}$/.test(code)) return json({ error: '配对码是 6 位数字' }, 400);
      // 先删再签：只有真正删掉这一行的请求才发 session，并发提交同一码不会签出两个
      const claimed = await env.DB.prepare(
        'DELETE FROM pair_codes WHERE code = ? AND expires_at >= ? RETURNING user_id',
      ).bind(code, Date.now()).first();
      if (!claimed) return json({ error: '配对码无效或已过期' }, 400);
      const u = await env.DB.prepare('SELECT username FROM users WHERE id = ?').bind(claimed.user_id).first();
      const token = randomHex(24);
      const exp = Date.now() + SESSION_DAYS * 86400_000;
      await env.DB.prepare('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)')
        .bind(token, claimed.user_id, exp).run();
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
      if (!body || typeof body.payload !== 'object' || body.payload === null) {
        return json({ error: '数据格式不对' }, 400);
      }
      const localText = JSON.stringify(body.payload);
      if (localText.length > MAX_PAYLOAD) return json({ error: '进度数据过大' }, 413);

      // 首次登录/冲突后的权威合并：一次请求完成读取、合并、写回。
      for (let attempt = 0; attempt < 2; attempt++) {
        const row = await env.DB.prepare(
          'SELECT s.user_id, s.expires_at, p.payload, p.updated_at ' +
          'FROM sessions s ' +
          'LEFT JOIN progress p ON p.user_id = s.user_id ' +
          'WHERE s.token = ?',
        ).bind(token).first();
        if (!row || Number(row.expires_at) < Date.now()) return json({ error: '未登录' }, 401);
        const now = Date.now();
        if (!row.payload) {
          const inserted = await env.DB.prepare(
            'INSERT INTO progress (user_id, payload, updated_at) VALUES (?, ?, ?) ' +
            'ON CONFLICT(user_id) DO NOTHING RETURNING updated_at',
          ).bind(row.user_id, localText, now).first();
          if (inserted) {
            return json({ ok: true, payload: body.payload, updatedAt: inserted.updated_at, merged: false });
          }
          continue;
        }
        let remote;
        try { remote = JSON.parse(row.payload); }
        catch { return json({ error: '云端进度损坏' }, 500); }
        const merged = mergeSnapshots(body.payload, remote);
        const mergedText = JSON.stringify(merged);
        if (mergedText === row.payload) {
          return json({ ok: true, payload: remote, updatedAt: row.updated_at, merged: false });
        }
        const updated = await env.DB.prepare(
          'UPDATE progress SET payload = ?, updated_at = ? ' +
          'WHERE user_id = ? AND updated_at = ? RETURNING updated_at',
        ).bind(mergedText, now, row.user_id, row.updated_at).first();
        if (updated) {
          return json({ ok: true, payload: merged, updatedAt: updated.updated_at, merged: true });
        }
      }
      return json({ error: 'conflict' }, 409);
    }

    if (path === '/state') {
      const token = cookieFrom(request, 'ky_sid');
      if (!token) return json({ error: '未登录' }, 401);

      if (method === 'GET') {
        // 一次查询同时完成会话校验和进度读取，避免原来两次 D1 往返。
        const row = await env.DB.prepare(
          'SELECT s.expires_at, p.payload, p.updated_at ' +
          'FROM sessions s ' +
          'LEFT JOIN progress p ON p.user_id = s.user_id ' +
          'WHERE s.token = ?',
        ).bind(token).first();
        if (!row || Number(row.expires_at) < Date.now()) return json({ error: '未登录' }, 401);
        const updatedAt = Number(row.updated_at || 0);
        if (!row.payload) return json({ payload: null, updatedAt: 0 });
        // 轮询时只带 since：云端没变化就不返回整份进度。
        const since = Number(url.searchParams.get('since') || 0);
        if (since > 0 && updatedAt <= since) return json({ unchanged: true, updatedAt });
        return json({ payload: JSON.parse(row.payload), updatedAt });
      }

      if (method === 'PUT' || method === 'POST') {
        const len = Number(request.headers.get('content-length') || 0);
        if (len > MAX_PAYLOAD * 1.2) return json({ error: '进度数据过大' }, 413);
        const body = await readStateBody(request);
        if (!body || typeof body.payload !== 'object' || body.payload === null) {
          return json({ error: '数据格式不对' }, 400);
        }
        const text = JSON.stringify(body.payload);
        if (text.length > MAX_PAYLOAD) return json({ error: '进度数据过大' }, 413);
        if (!stateBudget('state:' + clientIp(request))) {
          return json({ error: '同步太频繁，请稍后再试' }, 429);
        }

        // 乐观锁 + 写入合并成一条 SQL：常见情况下一次 D1 往返完成同步。
        const base = Math.max(0, Number(body.baseUpdatedAt || 0));
        // 兼容旧版前端：旧请求没有 baseUpdatedAt，仍按原来的覆盖行为处理。
        const force = body.force === true || !Object.prototype.hasOwnProperty.call(body, 'baseUpdatedAt');
        const now = Date.now();
        const written = await env.DB.prepare(
          'INSERT INTO progress (user_id, payload, updated_at) ' +
          'SELECT s.user_id, ?, ? ' +
          'FROM sessions s ' +
          'WHERE s.token = ? AND s.expires_at >= ? ' +
          'ON CONFLICT(user_id) DO UPDATE SET ' +
          'payload = excluded.payload, updated_at = excluded.updated_at ' +
          'WHERE ? = 1 OR progress.updated_at <= ? ' +
          'RETURNING updated_at',
        ).bind(text, now, token, now, force ? 1 : 0, base).first();
        if (written) return json({ ok: true, updatedAt: written.updated_at });

        // 没写成功通常是版本冲突；把云端最新数据一起返回，客户端一次合并后重试。
        const row = await env.DB.prepare(
          'SELECT s.expires_at, p.payload, p.updated_at ' +
          'FROM sessions s ' +
          'LEFT JOIN progress p ON p.user_id = s.user_id ' +
          'WHERE s.token = ?',
        ).bind(token).first();
        if (!row || Number(row.expires_at) < Date.now()) return json({ error: '未登录' }, 401);
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
