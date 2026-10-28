# -*- coding: utf-8 -*-
"""本地存储按账号隔离：换账号不再串进度；登录时把未登录的进度带进账号。"""
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


# 1. load/save 按账号加作用域
rep("""const load = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };""",
    """// 本地数据按账号隔离：未登录用公共空间，登录后各账号各存各的
const SCOPED_KEYS = new Set(['ky_words_v1', 'ky_conf_v1', 'ky_chapter_v1', 'ky_stamp_v1']);
const scopedKey = key => (authUser && SCOPED_KEYS.has(key) ? key + '@' + authUser : key);
const load = (key, fallback) => { try { return JSON.parse(localStorage.getItem(scopedKey(key))) ?? fallback; } catch { return fallback; } };""",
    "load 作用域")

rep("    localStorage.setItem(key, JSON.stringify(value));",
    "    localStorage.setItem(scopedKey(key), JSON.stringify(value));", "save 作用域")

rep("    try { localStorage.setItem(LS_STAMP, String(Date.now())); } catch {}",
    "    try { localStorage.setItem(scopedKey(LS_STAMP), String(Date.now())); } catch {}", "时间戳作用域")

rep("    const localStamp = Number(localStorage.getItem(LS_STAMP) || 0);",
    "    const localStamp = Number(localStorage.getItem(scopedKey(LS_STAMP)) || 0);", "读取时间戳作用域")

# 2. 切换账号时重载内存中的状态
rep("""function renderAuth() {""",
    """// 登录/退出后重新装载该账号自己的进度
function reloadSpace() {
  state = load(LS_STATE, {});
  chapterData = load('ky_chapter_v1', {});
  conf = Object.assign({ deck: 'core', deckChapter: {}, showByDefault: false, speak: true }, load(LS_CONF, {}));
  delete conf.autoShow;
  activeDeck = DECKS[conf.deck] ? conf.deck : 'core';
  $('deckSelect').value = activeDeck;
  updateDeckMeta();
  renderChapters();
  loadChapter((conf.deckChapter && conf.deckChapter[activeDeck]) || 0);
  updateStats();
  renderList();
}
// 第一次登录某账号时，把未登录状态下背的进度带进该账号，避免看起来清零
function adoptGuestProgress(username) {
  try {
    if (localStorage.getItem(LS_STATE + '@' + username)) return;
    for (const key of ['ky_words_v1', 'ky_conf_v1', 'ky_chapter_v1']) {
      const v = localStorage.getItem(key);
      if (v) localStorage.setItem(key + '@' + username, v);
    }
  } catch {}
}

function renderAuth() {""", "账号空间切换")

# 3. 登录后切空间
rep("""async function afterLogin(username) {
  authUser = username;
  renderAuth();""",
    """async function afterLogin(username) {
  adoptGuestProgress(username);
  authUser = username;
  reloadSpace();
  renderAuth();""", "登录切空间")

# 4. 退出登录切回公共空间
rep("""  try { await api('/logout', { method: 'POST' }); } catch {}
  authUser = null;
  renderAuth();
  authSay('已退出登录，本机进度保留', 'ok');""",
    """  try { await api('/logout', { method: 'POST' }); } catch {}
  authUser = null;
  reloadSpace();
  renderAuth();
  authSay('已退出登录，进度仍保存在本机', 'ok');""", "退出切空间")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
