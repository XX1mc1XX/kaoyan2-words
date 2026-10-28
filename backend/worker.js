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

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

const USER_RE = /^[A-Za-z0-9_一-龥]{3,24}$/;

async function handleApi(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, '').replace(/^\/api/, '') || '/';
  const method = request.method;

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
      const body = await readJson(request);
      const username = String(body?.username || '').trim();
      const password = String(body?.password || '');
      if (!USER_RE.test(username)) return json({ error: '用户名需 3-24 位字母、数字、下划线或中文' }, 400);
      if (password.length < 6 || password.length > 72) return json({ error: '密码需 6-72 位' }, 400);
      const exists = await env.DB.prepare('SELECT id FROM users WHERE username = ?').bind(username).first();
      if (exists) return json({ error: '用户名已被占用' }, 409);
      const salt = randomHex(16);
      const hash = await hashPassword(password, salt);
      const now = Date.now();
      const res = await env.DB.prepare(
        'INSERT INTO users (username, pass_hash, pass_salt, created_at) VALUES (?, ?, ?, ?)',
      ).bind(username, hash, salt, now).run();
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
      const body = await readJson(request);
      const username = String(body?.username || '').trim();
      const password = String(body?.password || '');
      const row = await env.DB.prepare(
        'SELECT id, username, pass_hash, pass_salt FROM users WHERE username = ?',
      ).bind(username).first();
      if (!row) return json({ error: '用户名或密码不对' }, 401);
      const hash = await hashPassword(password, row.pass_salt);
      if (hash !== row.pass_hash) return json({ error: '用户名或密码不对' }, 401);
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
      await env.DB.prepare('DELETE FROM pair_codes WHERE expires_at < ?').bind(now).run();
      let code = '';
      for (let i = 0; i < 6; i++) {
        code = String(Math.floor(100000 + Math.random() * 900000));
        const dup = await env.DB.prepare('SELECT code FROM pair_codes WHERE code = ?').bind(code).first();
        if (!dup) break;
      }
      const expiresAt = now + 10 * 60 * 1000;
      await env.DB.prepare('INSERT INTO pair_codes (code, user_id, expires_at) VALUES (?, ?, ?)')
        .bind(code, user.id, expiresAt).run();
      return json({ code, expiresAt });
    }

    if (path === '/pair/claim' && method === 'POST') {
      const body = await readJson(request);
      const code = String(body?.code || '').trim();
      if (!/^\d{6}$/.test(code)) return json({ error: '配对码是 6 位数字' }, 400);
      const row = await env.DB.prepare('SELECT user_id, expires_at FROM pair_codes WHERE code = ?').bind(code).first();
      if (!row || row.expires_at < Date.now()) return json({ error: '配对码无效或已过期' }, 400);
      const u = await env.DB.prepare('SELECT username FROM users WHERE id = ?').bind(row.user_id).first();
      await env.DB.prepare('DELETE FROM pair_codes WHERE code = ?').bind(code).run();
      const token = randomHex(24);
      const exp = Date.now() + SESSION_DAYS * 86400_000;
      await env.DB.prepare('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)')
        .bind(token, row.user_id, exp).run();
      return json({ ok: true, username: u.username }, 200, {
        'set-cookie': sessionCookie(token, SESSION_DAYS * 86400),
      });
    }

    if (path === '/state') {
      const user = await currentUser(request, env);
      if (!user) return json({ error: '未登录' }, 401);
      if (method === 'GET') {
        const row = await env.DB.prepare('SELECT payload, updated_at FROM progress WHERE user_id = ?')
          .bind(user.id).first();
        if (!row) return json({ payload: null, updatedAt: 0 });
        return json({ payload: JSON.parse(row.payload), updatedAt: row.updated_at });
      }
      if (method === 'PUT' || method === 'POST') {
        const body = await readJson(request);
        if (!body || typeof body.payload !== 'object' || body.payload === null) {
          return json({ error: '数据格式不对' }, 400);
        }
        const text = JSON.stringify(body.payload);
        if (text.length > MAX_PAYLOAD) return json({ error: '进度数据过大' }, 413);
        const now = Date.now();
        await env.DB.prepare(
          `INSERT INTO progress (user_id, payload, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at`,
        ).bind(user.id, text, now).run();
        return json({ ok: true, updatedAt: now });
      }
    }

    return json({ error: '没有这个接口' }, 404);
  } catch (e) {
    return json({ error: '服务器错误：' + (e?.message || e) }, 500);
  }
}

// Pages 高级模式：/api/* 走后端，其余交给静态资源
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
      return handleApi(request, env);
    }
    return env.ASSETS.fetch(request);
  },
};
