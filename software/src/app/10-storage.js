const LS_STATE = 'ky_words_v1';
const LS_CONF = 'ky_conf_v1';
const LS_POS = 'ky_pos_v1';
const LS_STAMP = 'ky_stamp_v1';
// 自绘 logo：渐变圆 + 抽象「W」笔画
// 品牌 Logo：极简科技感双色 W，金色节点代表一次记忆完成。
const AVATAR_LOGO = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" aria-hidden="true">'
  + '<defs><linearGradient id="kyLogoBg" x1="0" y1="0" x2="1" y2="1">'
  + '<stop offset="0" stop-color="#03141d"/><stop offset=".7" stop-color="#07343d"/>'
  + '<stop offset="1" stop-color="#115e59"/></linearGradient>'
  + '<linearGradient id="kyLogoLeft" x1="0" y1="0" x2="1" y2="1">'
  + '<stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#67e8f9"/></linearGradient>'
  + '<linearGradient id="kyLogoRight" x1="0" y1="0" x2="1" y2="1">'
  + '<stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#99f6e4"/></linearGradient></defs>'
  + '<rect width="36" height="36" fill="url(#kyLogoBg)"/>'
  + '<path d="M7.5 9.3 12.1 26l5.9-10.4v4.2" fill="none" stroke="url(#kyLogoLeft)" '
  + 'stroke-width="3.3" stroke-linecap="round" stroke-linejoin="round"/>'
  + '<path d="M18 19.8v-4.2L23.9 26l4.6-16.7" fill="none" stroke="url(#kyLogoRight)" '
  + 'stroke-width="3.3" stroke-linecap="round" stroke-linejoin="round"/>'
  + '<circle cx="28.5" cy="9.3" r="1.7" fill="#fbbf24"/>'
  + '</svg>';
// 图标 dataURL 的上限。它要跟着账号同步，撑大了会顶到同步 payload 的 512KB 线；
// 导入备份时也可能被人塞进一张几百 KB 的图，直接写满 localStorage。
const ICON_DATA_MAX = 120 * 1024;
const ICON_PRESETS = [
  { id: 'brand', label: '默认 Logo', svg: AVATAR_LOGO },
  { id: 'book', label: '书本', svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" aria-hidden="true">'
    + '<defs><linearGradient id="kyBook" x1="0" y1="0" x2="1" y2="1">'
    + '<stop offset="0" stop-color="#fbbf24"/><stop offset="1" stop-color="#b45309"/></linearGradient></defs>'
    + '<circle cx="18" cy="18" r="18" fill="url(#kyBook)"/>'
    + '<path d="M7.5 11.8c3.9-1.3 7.2-1 10.5.9v12.9c-3.3-1.8-6.6-2.1-10.5-.9V11.8Zm21 0c-3.9-1.3-7.2-1-10.5.9v12.9c3.3-1.8 6.6-2.1 10.5-.9V11.8Z" fill="#fff"/>'
    + '<path d="M10.2 15.1c2.2-.3 4.1.1 5.8 1.2M10.2 18.4c2.2-.3 4.1.1 5.8 1.2M25.8 15.1c-2.2-.3-4.1.1-5.8 1.2M25.8 18.4c-2.2-.3-4.1.1-5.8 1.2" fill="none" stroke="#b45309" stroke-width="1.1" stroke-linecap="round"/>'
    + '</svg>' },
  { id: 'star', label: '星光', svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" aria-hidden="true">'
    + '<defs><linearGradient id="kyStar" x1="0" y1="0" x2="1" y2="1">'
    + '<stop offset="0" stop-color="#a78bfa"/><stop offset="1" stop-color="#5b21b6"/></linearGradient></defs>'
    + '<circle cx="18" cy="18" r="18" fill="url(#kyStar)"/>'
    + '<path d="m18 7.3 3.2 6.4 7.1 1-5.1 5 1.2 7-6.4-3.3-6.4 3.3 1.2-7-5.1-5 7.1-1L18 7.3Z" fill="#fff"/>'
    + '</svg>' },
  { id: 'leaf', label: '绿叶', svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" aria-hidden="true">'
    + '<defs><linearGradient id="kyLeaf" x1="0" y1="0" x2="1" y2="1">'
    + '<stop offset="0" stop-color="#4ade80"/><stop offset="1" stop-color="#15803d"/></linearGradient></defs>'
    + '<circle cx="18" cy="18" r="18" fill="url(#kyLeaf)"/>'
    + '<path d="M9.5 26.5c0-9.8 6.2-16.3 17-17.2-.5 10.8-6.6 17-16.4 17.2Z" fill="#fff"/>'
    + '<path d="M10.8 26.2c3.8-5.9 7.8-9.5 13.4-12.4" fill="none" stroke="#15803d" stroke-width="1.8" stroke-linecap="round"/>'
    + '</svg>' },
  { id: 'moon', label: '月亮', svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" aria-hidden="true">'
    + '<defs><linearGradient id="kyMoon" x1="0" y1="0" x2="1" y2="1">'
    + '<stop offset="0" stop-color="#60a5fa"/><stop offset="1" stop-color="#1e3a8a"/></linearGradient></defs>'
    + '<circle cx="18" cy="18" r="18" fill="url(#kyMoon)"/>'
    + '<path d="M23.8 8.1a10.7 10.7 0 1 0 4.2 18.5 9.3 9.3 0 0 1-4.2-18.5Z" fill="#fff"/>'
    + '<circle cx="26.8" cy="10.6" r="1.2" fill="#fff"/><circle cx="29.6" cy="14" r=".8" fill="#fff"/>'
    + '</svg>' },
];
const LS_AUTH = 'ky_auth_user_v1';
// 每日学习节奏：{ '2026-10-28': { s: 过卡次数, m: 当天新掌握数 } }
const LS_DAILY = 'ky_daily_v1';
const DAILY_KEEP_DAYS = 120;
const savedAuthUser = (() => { try { return localStorage.getItem(LS_AUTH) || null; } catch { return null; } })();
let authUser = savedAuthUser; // 先用上次账号打开本地进度；联网后再校验会话
let syncTimer = null;
let syncing = false;
let syncInitialized = false;
let syncDirty = false;
let syncPaused = false;
let localRevision = 0;
let applyingRemote = false;
let syncEpoch = 0;
// 账号切换时必须真正中止在途 API，而不只是让晚到的结果失效：
// 否则弱网请求会继续占连接，旧页面也会多跑几十秒。
let apiEpochController = typeof AbortController !== 'undefined' ? new AbortController() : null;
function abortApiRequests() {
  if (apiEpochController) { try { apiEpochController.abort(); } catch {} }
  apiEpochController = typeof AbortController !== 'undefined' ? new AbortController() : null;
}
const DAY = 864e5;
// 极简事件总线（发布/订阅）：数据一变就广播，谁关心谁订阅，避免到处手动串调用
const bus = (() => {
  const subs = new Map();
  return {
    on(type, fn) {
      if (!subs.has(type)) subs.set(type, new Set());
      subs.get(type).add(fn);
      return () => subs.get(type).delete(fn);
    },
    emit(type, payload) {
      const set = subs.get(type);
      if (!set) return;
      for (const fn of [...set]) { try { fn(payload); } catch (e) {} }
    },
  };
})();
// 本地数据按账号隔离：未登录用公共空间，登录后各账号各存各的。
// 大 state 按稳定 hash 分成 64 个分片：一次背词只重写一个约 4KB 的分片，
// 不再同步 JSON.stringify 整个 200KB+ 状态。meta 最后切换 generation，
// 构建中途失败时旧 generation 仍可完整读取。
const SCOPED_KEYS = new Set(['ky_words_v1', 'ky_conf_v1', 'ky_chapter_v1', 'ky_pos_v1', 'ky_stamp_v1', 'ky_daily_v1']);
const STATE_SHARD_COUNT = 64;
const STATE_META_KEY = LS_STATE + '#meta';
const accountScope = name => String(name || '').trim().toLowerCase();
const storageKeyFor = (key, scope) => (scope && (SCOPED_KEYS.has(key) || String(key).startsWith(LS_STATE + '#'))
  ? key + '@' + accountScope(scope)
  : key);
const scopedKey = key => storageKeyFor(key, authUser);
const stateShardIndex = name => {
  let hash = 2166136261;
  const text = String(name || '');
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) % STATE_SHARD_COUNT;
};
const stateShardStorageKey = (generation, index, scope) => storageKeyFor(LS_STATE + '#' + generation + '-' + index, scope);
function stateMetaForScope(scope) {
  try {
    const raw = String(localStorage.getItem(storageKeyFor(STATE_META_KEY, scope)) || '');
    const match = raw.match(/^2:([a-z0-9-]+)$/);
    return match ? match[1] : '';
  } catch { return ''; }
}
function readStateStoreForScope(scope, fallback) {
  try {
    const generation = stateMetaForScope(scope);
    if (generation) {
      const out = {};
      for (let i = 0; i < STATE_SHARD_COUNT; i += 1) {
        const raw = localStorage.getItem(stateShardStorageKey(generation, i, scope));
        if (!raw) continue;
        const rows = JSON.parse(raw);
        if (!rows || typeof rows !== 'object' || Array.isArray(rows)) continue;
        for (const [name, rec] of Object.entries(rows)) {
          if (name !== '__proto__') out[name] = rec;
        }
      }
      // 兼容仍开着旧版本页面的标签页：它在迁移后写回的 legacy 快照不能整份丢弃。
      try {
        const legacy = JSON.parse(localStorage.getItem(storageKeyFor(LS_STATE, scope)));
        if (legacy && typeof legacy === 'object' && !Array.isArray(legacy)) {
          for (const [name, rec] of Object.entries(legacy)) {
            if (name === '__proto__') continue;
            out[name] = out[name] ? mergeWordRecord(out[name], rec) : rec;
          }
        }
      } catch {}
      return out;
    }
  } catch {}
  try { return JSON.parse(localStorage.getItem(storageKeyFor(LS_STATE, scope))) ?? fallback; }
  catch { return fallback; }
}
const load = (key, fallback) => {
  if (key === LS_STATE) return readStateStoreForScope(authUser, fallback);
  try { return JSON.parse(localStorage.getItem(scopedKey(key))) ?? fallback; } catch { return fallback; }
};
function positionStoreFromChapters(chapters) {
  const out = {};
  for (const [key, rec] of Object.entries(chapters || {})) {
    if (!rec || rec.del || !Array.isArray(rec.order)) continue;
    const pos = Math.max(0, Number(rec.pos) || 0);
    out[key] = { pos, t: Number(rec.t) || 0 };
    if (typeof rec.posWord === 'string') out[key].posWord = rec.posWord;
  }
  return out;
}
function loadChapterStoreWithPositions(base) {
  const out = { ...(base && typeof base === 'object' && !Array.isArray(base) ? base : {}) };
  const positions = load(LS_POS, {});
  for (const [key, pos] of Object.entries(positions && typeof positions === 'object' ? positions : {})) {
    const rec = out[key];
    if (!rec || rec.del || !pos || typeof pos !== 'object') continue;
    rec.pos = Math.max(0, Number(pos.pos) || 0);
    if (typeof pos.posWord === 'string') rec.posWord = pos.posWord;
    if (Number(pos.t)) rec.t = Number(pos.t);
  }
  return out;
}
let storageWarned = false;
function showStorageWarning() {
  if (storageWarned) return;
  storageWarned = true;
  const el = document.getElementById('storageWarn');
  if (el) el.classList.remove('hidden');
}
function markStateChanged() {
  masteredWordsCache = null;
  stateRevision += 1;
  listQueryCache.key = '';
  invalidateSnapshotCache();
}
function writeStateStorageForScope(store, scope) {
  const shards = Array.from({ length: STATE_SHARD_COUNT }, () => ({}));
  for (const [name, rec] of Object.entries(store || {})) {
    if (name === '__proto__') continue;
    shards[stateShardIndex(name)][name] = rec;
  }
  const oldGeneration = stateMetaForScope(scope);
  const generation = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  try {
    for (let i = 0; i < STATE_SHARD_COUNT; i += 1) {
      const key = stateShardStorageKey(generation, i, scope);
      if (Object.keys(shards[i]).length) localStorage.setItem(key, JSON.stringify(shards[i]));
      else localStorage.removeItem(key);
    }
    // meta 是原子切换点；它写入前旧 generation 始终是权威数据。
    localStorage.setItem(storageKeyFor(STATE_META_KEY, scope), '2:' + generation);
  } catch (e) {
    try {
      for (let i = 0; i < STATE_SHARD_COUNT; i += 1) {
        localStorage.removeItem(stateShardStorageKey(generation, i, scope));
      }
    } catch {}
    showStorageWarning();
    return false;
  }
  try {
    if (oldGeneration && oldGeneration !== generation) {
      for (let i = 0; i < STATE_SHARD_COUNT; i += 1) {
        localStorage.removeItem(stateShardStorageKey(oldGeneration, i, scope));
      }
    }
    localStorage.removeItem(storageKeyFor(LS_STATE, scope));
  } catch {}
  return true;
}
function saveStateRecord(name) {
  if (!name || name === '__proto__') return false;
  // 旧格式第一次写入时先完整迁移；之后每次只更新 hash 对应的一个分片。
  const generation = stateMetaForScope(authUser);
  if (!generation) {
    const ok = writeStateStorageForScope(state, authUser);
    if (ok) markStateChanged();
    return ok;
  }
  const index = stateShardIndex(name);
  const key = stateShardStorageKey(generation, index, authUser);
  try {
    let shard = {};
    try { shard = JSON.parse(localStorage.getItem(key)) || {}; } catch {}
    if (!shard || typeof shard !== 'object' || Array.isArray(shard)) shard = {};
    shard[name] = state[name];
    localStorage.setItem(key, JSON.stringify(shard));
    markStateChanged();
    return true;
  } catch {
    showStorageWarning();
    return false;
  }
}
let masteredWordsCache = null;
let listQueryCache = { key: '', matches: [] };
let stateRevision = 0;
let snapshotCacheRevision = -1;
let snapshotCacheValue = null;
function invalidateSnapshotCache() {
  snapshotCacheRevision = -1;
  snapshotCacheValue = null;
}
const save = (key, value) => {
  let ok = false;
  try {
    ok = key === LS_STATE
      ? writeStateStorageForScope(value, authUser)
      : (localStorage.setItem(scopedKey(key), JSON.stringify(value)), true);
  } catch (e) {
    showStorageWarning();
    ok = false;
  }
  if (key === LS_STATE) markStateChanged();
  else invalidateSnapshotCache();
  try { bus.emit('data:change', key); } catch {}
  return ok;
};
const todayTs = () => { const d = new Date(); d.setHours(0,0,0,0); return d.getTime(); };
const dayKey = ts => {
  const d = new Date(ts);
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
};
let daily = load(LS_DAILY, {});
// 只保留最近 120 天，跨账号合并也不会无限膨胀。
// 顺便收敛字段类型：导入文件是外部输入，数值、墓碑、时间戳都要校验。
function pruneDaily(d) {
  const cut = todayTs() - (DAILY_KEEP_DAYS - 1) * DAY;
  const out = {};
  for (const [k, v] of Object.entries(d || {})) {
    if (k === '__proto__') continue;
    const ts = new Date(k + 'T00:00:00').getTime();
    if (!Number.isFinite(ts) || ts < cut) continue;
    if (!v || typeof v !== 'object') continue;
    if (v.del) { out[k] = { del: 1, t: Number(v.t) || 0 }; continue; }
    const rec = { s: Math.max(0, Number(v.s) || 0), m: Math.max(0, Number(v.m) || 0) };
    const t = Number(v.t) || 0;
    if (t) rec.t = t;
    out[k] = rec;
  }
  return out;
}
// s = 今天过卡次数；m = 今天从未掌握变成掌握的词数
function bumpDaily(known, isNewMaster) {
  const key = dayKey(Date.now());
  // 清空/导入会留下 { del: 1 } 墓碑，往里加计数前必须先把墓碑清掉，
  // 否则这一天的记录会继续被当成「已删除」。
  const cur = daily[key];
  const rec = cur && !cur.del ? cur : { s: 0, m: 0 };
  delete rec.del;
  rec.s = (rec.s || 0) + 1;
  if (known && isNewMaster) rec.m = (rec.m || 0) + 1;
  rec.t = Date.now();   // 合并按 t 取新，撤销减掉的计数才不会被「取大」复活
  daily[key] = rec;
  daily = pruneDaily(daily);
  save(LS_DAILY, daily);
}
// 撤销时把刚才加的数量减回去，否则误滑一次会永久多算一天的学习量
function revertDaily(delta) {
  if (!delta) return;
  const key = delta.day || dayKey(Date.now());
  const cur = daily[key];
  if (!cur || cur.del) return;
  daily[key] = {
    s: Math.max(0, (cur.s || 0) - (delta.s || 0)),
    m: Math.max(0, (cur.m || 0) - (delta.m || 0)),
    t: Date.now(),
  };
  save(LS_DAILY, daily);
}
// 连续学习天数：今天还没学就从昨天起算，中间断一天就停
function streakDays(d) {
  const recs = d || {};
  let ts = todayTs();
  let n = 0;
  if (!(recs[dayKey(ts)] || {}).s) ts -= DAY;
  while ((recs[dayKey(ts)] || {}).s) { n += 1; ts -= DAY; }
  return n;
}
// 合并每日节奏由 shared/merge.js 统一提供（带 t 时按时间取新；只有老数据才退回取大）。
// 以前本地这份用 Math.max，撤销减掉的计数一同步就被云端「取大」复活了。
const $ = id => document.getElementById(id);
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])';
const isShown = el => !!el && !el.hidden && getComputedStyle(el).visibility !== 'hidden' && el.getClientRects().length > 0;
const focusablesIn = root => [...root.querySelectorAll(FOCUSABLE)].filter(isShown);
function trapModalFocus(event, root, close) {
  if (event.key === 'Escape') { event.preventDefault(); close(); return; }
  if (event.key !== 'Tab') return;
  const items = focusablesIn(root);
  if (!items.length) { event.preventDefault(); root.focus({ preventScroll: true }); return; }
  const first = items[0], last = items[items.length - 1], active = document.activeElement;
  if (event.shiftKey && (active === first || !root.contains(active))) { event.preventDefault(); last.focus({ preventScroll: true }); }
  else if (!event.shiftKey && (active === last || !root.contains(active))) { event.preventDefault(); first.focus({ preventScroll: true }); }
}
function setPageInert(on, keep) {
  const regions = [document.querySelector('header'), document.querySelector('main'), document.getElementById('undoBar'), document.getElementById('detailMask'), document.getElementById('authModal')];
  for (const el of regions.filter(Boolean)) {
    if (keep && el === keep) continue;
    el.inert = on;
    if (on) el.setAttribute('aria-hidden', 'true'); else el.removeAttribute('aria-hidden');
  }
}

let state = load(LS_STATE, {});
let conf = Object.assign({ deck: 'core', chapter: 0, deckChapter: {}, progressAt: 0, showByDefault: false, speak: true, speakLang: 'en', icon: null, iconAt: 0 }, load(LS_CONF, {}));
