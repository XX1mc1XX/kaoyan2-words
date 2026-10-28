# -*- coding: utf-8 -*-
"""登录面板（账号密码 + 微信扫码占位）与进度云同步。"""
import io

P = r"c:\my_project\单词\software\template.html"
t = io.open(P, encoding="utf-8").read()
log = []


def rep(old, new, label):
    global t
    if old in t:
        t = t.replace(old, new, 1)
        log.append("OK    " + label)
    else:
        log.append("MISS  " + label)


# ---------- 1. header 账号按钮 ----------
rep('''    <button class="tab" id="tabStat">统计</button>
  </div>''',
    '''    <button class="tab" id="tabStat">统计</button>
    <button class="account-btn" id="accountBtn">登录</button>
  </div>''', "header 账号按钮")

# ---------- 2. 弹层 HTML ----------
rep('''<script>
const WORDS = __DATA__;''',
    '''<div class="modal hidden" id="authModal">
  <div class="modal-card">
    <button class="modal-close" id="authClose" aria-label="关闭">×</button>
    <div class="modal-title" id="authTitle">登录</div>
    <p class="modal-note">登录后进度在手机和电脑之间同步。</p>
    <form class="auth-form" id="authForm">
      <input class="auth-input" id="authUser" placeholder="用户名" autocomplete="username" required>
      <input class="auth-input" id="authPass" type="password" placeholder="密码（至少 6 位）" autocomplete="current-password" required>
      <button class="btn primary" id="authSubmit" type="submit">登录</button>
    </form>
    <button class="auth-switch" id="authMode">没有账号？注册一个</button>
    <div class="auth-sep"><span>或</span></div>
    <button class="wx-btn" id="wxLogin" disabled title="需微信开放平台网站应用资质">微信扫码登录（暂不可用）</button>
    <div class="auth-status" id="authStatus"></div>
    <div class="auth-sync hidden" id="authSync">
      <button class="btn" id="syncUp">用本机进度覆盖云端</button>
      <button class="btn" id="syncDown">用云端进度覆盖本机</button>
      <button class="auth-switch danger-link" id="authLogout">退出登录</button>
    </div>
  </div>
</div>
<script>
const WORDS = __DATA__;''', "登录弹层")

# ---------- 3. 样式 ----------
rep(".danger{border:1px solid color-mix(in srgb,var(--bad) 38%,var(--line));",
    """.account-btn{border:1px solid var(--line);background:transparent;color:var(--muted);
  font:inherit;font-size:12.5px;font-weight:700;border-radius:999px;padding:6px 11px;cursor:pointer;
  max-width:88px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.account-btn.online{color:var(--brand);border-color:color-mix(in srgb,var(--brand) 45%,var(--line))}
.modal{position:fixed;inset:0;z-index:60;display:flex;align-items:center;justify-content:center;
  padding:18px;background:rgba(0,0,0,.55);backdrop-filter:blur(2px)}
.modal-card{position:relative;width:min(100%,360px);background:var(--card);color:var(--ink);
  border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);
  padding:22px 18px 18px;display:flex;flex-direction:column;gap:10px}
.modal-close{position:absolute;top:8px;right:10px;border:0;background:transparent;color:var(--muted);
  font-size:24px;line-height:1;cursor:pointer;padding:4px 6px}
.modal-title{font-size:17px;font-weight:800}
.modal-note{margin:0;font-size:12.5px;color:var(--muted);line-height:1.6}
.auth-form{display:flex;flex-direction:column;gap:8px}
.auth-input{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:11px;
  padding:11px 12px;font:inherit;font-size:14px}
.auth-input:focus{outline:2px solid color-mix(in srgb,var(--brand) 45%,transparent);outline-offset:1px}
.auth-switch{border:0;background:transparent;color:var(--brand);font:inherit;font-size:12.5px;
  cursor:pointer;padding:4px;text-decoration:underline;text-underline-offset:3px}
.danger-link{color:var(--bad)}
.auth-sep{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:11.5px}
.auth-sep::before,.auth-sep::after{content:"";flex:1;height:1px;background:var(--line)}
.wx-btn{border:1px solid var(--line);background:transparent;color:var(--muted);border-radius:11px;
  padding:11px;font:inherit;font-size:13px;cursor:not-allowed;opacity:.65}
.auth-status{font-size:12.5px;color:var(--muted);min-height:1em;line-height:1.5}
.auth-status.err{color:var(--bad)}
.auth-status.ok{color:var(--ok)}
.auth-sync{display:flex;flex-direction:column;gap:8px}
.danger{border:1px solid color-mix(in srgb,var(--bad) 38%,var(--line));""", "弹层样式")

# ---------- 4. save 里挂本地时间戳 ----------
rep("    localStorage.setItem(key, JSON.stringify(value));",
    """    localStorage.setItem(key, JSON.stringify(value));
    try { localStorage.setItem(LS_STAMP, String(Date.now())); } catch {}
    scheduleCloudSync();""", "save 挂同步")

rep("const LS_CONF = 'ky_conf_v1';",
    "const LS_CONF = 'ky_conf_v1';\nconst LS_STAMP = 'ky_stamp_v1';", "新增 LS_STAMP")

# ---------- 5. 同步逻辑 ----------
rep("""$('deckSelect').onchange = event => switchDeck(event.target.value);
</script>""",
    """$('deckSelect').onchange = event => switchDeck(event.target.value);

// ---------- 账号与云同步 ----------
let authUser = null;
let authMode = 'login';
let syncTimer = null;
let syncing = false;

async function api(path, options) {
  const opt = options || {};
  const res = await fetch('/api' + path, {
    method: opt.method || (opt.body ? 'POST' : 'GET'),
    credentials: 'same-origin',
    headers: opt.body ? { 'content-type': 'application/json' } : {},
    body: opt.body ? JSON.stringify(opt.body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch {}
  if (!res.ok) throw new Error((data && data.error) || ('请求失败 ' + res.status));
  return data || {};
}

function snapshot() {
  return {
    state,
    chapterData,
    conf: {
      deck: conf.deck,
      deckChapter: conf.deckChapter || {},
      showByDefault: !!conf.showByDefault,
      speak: conf.speak !== false,
    },
  };
}

function applySnapshot(d) {
  if (!d || typeof d !== 'object') return;
  if (d.state && typeof d.state === 'object') {
    state = d.state;
    save(LS_STATE, state);
  }
  if (d.chapterData && typeof d.chapterData === 'object') {
    chapterData = d.chapterData;
    save('ky_chapter_v1', chapterData);
  }
  if (d.conf && typeof d.conf === 'object') {
    if (d.conf.deck && DECKS[d.conf.deck]) conf.deck = d.conf.deck;
    if (d.conf.deckChapter) conf.deckChapter = d.conf.deckChapter;
    if (typeof d.conf.showByDefault === 'boolean') conf.showByDefault = d.conf.showByDefault;
    if (typeof d.conf.speak === 'boolean') conf.speak = d.conf.speak;
    save(LS_CONF, conf);
    activeDeck = DECKS[conf.deck] ? conf.deck : 'core';
    $('deckSelect').value = activeDeck;
    updateDeckMeta();
    loadChapter((conf.deckChapter && conf.deckChapter[activeDeck]) || 0);
    renderChapters();
  }
  updateStats();
  renderList();
}

function authSay(msg, kind) {
  const el = $('authStatus');
  el.textContent = msg || '';
  el.className = 'auth-status' + (kind ? ' ' + kind : '');
}

function renderAuth() {
  const btn = $('accountBtn');
  btn.textContent = authUser ? authUser : '登录';
  btn.classList.toggle('online', !!authUser);
  $('authSync').classList.toggle('hidden', !authUser);
  $('authForm').classList.toggle('hidden', !!authUser);
  $('authMode').classList.toggle('hidden', !!authUser);
  $('wxLogin').classList.toggle('hidden', !!authUser);
  document.querySelector('.auth-sep').classList.toggle('hidden', !!authUser);
  $('authTitle').textContent = authUser ? '已登录：' + authUser : (authMode === 'login' ? '登录' : '注册');
  $('authSubmit').textContent = authMode === 'login' ? '登录' : '注册并登录';
  $('authPass').setAttribute('autocomplete', authMode === 'login' ? 'current-password' : 'new-password');
}

function scheduleCloudSync() {
  if (!authUser || syncing) return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(uploadProgress, 2500);
}

async function uploadProgress(silent) {
  if (!authUser) return;
  syncing = true;
  try {
    await api('/state', { method: 'PUT', body: { payload: snapshot() } });
    if (!silent) authSay('已上传到云端', 'ok');
  } catch (e) {
    if (!silent) authSay(e.message, 'err');
  } finally {
    syncing = false;
  }
}

async function refreshAuth() {
  try {
    const r = await api('/me');
    authUser = r.user ? r.user.username : null;
  } catch {
    authUser = null;
  }
  renderAuth();
}

async function afterLogin(username) {
  authUser = username;
  renderAuth();
  authSay('已登录，正在比对云端进度…');
  try {
    const r = await api('/state');
    const localStamp = Number(localStorage.getItem(LS_STAMP) || 0);
    if (!r.payload) {
      await uploadProgress(true);
      authSay('已把本机进度上传到云端', 'ok');
    } else if (r.updatedAt > localStamp) {
      const words = Object.keys(r.payload.state || {}).length;
      authSay('云端有 ' + words + ' 个词的进度（较新）。点下面按钮选择保留哪一份。');
    } else {
      await uploadProgress(true);
      authSay('本机进度较新，已上传到云端', 'ok');
    }
  } catch (e) {
    authSay(e.message, 'err');
  }
}

$('accountBtn').onclick = () => {
  $('authModal').classList.remove('hidden');
  authSay('');
  refreshAuth();
};
$('authClose').onclick = () => $('authModal').classList.add('hidden');
$('authModal').onclick = event => {
  if (event.target === $('authModal')) $('authModal').classList.add('hidden');
};
$('authMode').onclick = () => {
  authMode = authMode === 'login' ? 'register' : 'login';
  renderAuth();
  authSay('');
};
$('authForm').onsubmit = async event => {
  event.preventDefault();
  const username = $('authUser').value.trim();
  const password = $('authPass').value;
  if (!username || password.length < 6) { authSay('用户名不能为空，密码至少 6 位', 'err'); return; }
  $('authSubmit').disabled = true;
  authSay('处理中…');
  try {
    const r = await api(authMode === 'login' ? '/login' : '/register', { body: { username, password } });
    $('authPass').value = '';
    await afterLogin(r.username);
  } catch (e) {
    authSay(e.message, 'err');
  } finally {
    $('authSubmit').disabled = false;
  }
};
$('authLogout').onclick = async () => {
  try { await api('/logout', { method: 'POST' }); } catch {}
  authUser = null;
  renderAuth();
  authSay('已退出登录，本机进度保留', 'ok');
};
$('syncUp').onclick = () => uploadProgress(false);
$('syncDown').onclick = async () => {
  try {
    const r = await api('/state');
    if (!r.payload) { authSay('云端还没有进度', 'err'); return; }
    applySnapshot(r.payload);
    localStorage.setItem(LS_STAMP, String(Date.now()));
    save(LS_CONF, conf);
    authSay('已用云端进度覆盖本机', 'ok');
  } catch (e) {
    authSay(e.message, 'err');
  }
};
// 微信扫码：需要开放平台网站应用资质，未配置时按钮保持禁用
api('/wx').then(r => {
  const btn = $('wxLogin');
  if (r.enabled) {
    btn.disabled = false;
    btn.textContent = '微信扫码登录';
    btn.onclick = () => {
      const redirect = encodeURIComponent(location.origin + '/');
      location.href = 'https://open.weixin.qq.com/connect/qrconnect?appid=' + encodeURIComponent(r.appid)
        + '&redirect_uri=' + redirect + '&response_type=code&scope=snsapi_login&state=ky#wechat_redirect';
    };
  }
}).catch(() => {});
refreshAuth();
</script>""", "同步逻辑")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
