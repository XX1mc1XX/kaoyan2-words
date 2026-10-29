// ---------- 账号与云同步 ----------
let authMode = 'login';
// 头像要在首屏就画出来。放在这里而不是更上面的启动序列：renderAuth 读 authMode，
// 提前调用会撞上它的 TDZ，整段脚本会从那里中断。
renderAuth();

// 会话过期（401）后必须把界面也踢回未登录状态：
// 否则界面一直显示已登录，而自动同步在后台静默失败，用户完全无感知。
let sessionExpiredHandled = false;
function handleSessionExpired() {
  if (sessionExpiredHandled || !authUser) return;
  sessionExpiredHandled = true;
  authUser = null;
  try { localStorage.removeItem(LS_AUTH); } catch {}
  reloadSpace();
  renderAuth();
  showSessionNotice('登录已过期，请重新登录。进度仍保存在本机。', 8000);
}

// 顶部提示条：登录成功、退出、会话过期这类一次性结果都在这里说一声。
// 只写在弹窗里的话，弹窗一关用户就什么也看不到了。
function showSessionNotice(text, ms) {
  const el = $('sessionWarn');
  if (!el) return;
  el.textContent = text;
  el.classList.remove('hidden');
  clearTimeout(showSessionNotice.timer);
  showSessionNotice.timer = setTimeout(() => el.classList.add('hidden'), ms || 6000);
}

// 把一个或多个 AbortSignal 合成为一个信号；旧浏览器没有 AbortSignal.any 时手动桥接。
function combinedAbortSignal(signals) {
  const list = (signals || []).filter(Boolean);
  if (!list.length) return { signal: undefined, cleanup() {} };
  if (typeof AbortSignal !== 'undefined' && AbortSignal.any) {
    return { signal: AbortSignal.any(list), cleanup() {} };
  }
  const merged = new AbortController();
  const relays = [];
  const cleanup = () => {
    for (const [signal, relay] of relays) signal.removeEventListener('abort', relay);
    relays.length = 0;
  };
  const abortMerged = () => {
    cleanup();
    try { merged.abort(); } catch {}
  };
  for (const signal of list) {
    if (signal.aborted) { abortMerged(); break; }
    const relay = () => abortMerged();
    relays.push([signal, relay]);
    signal.addEventListener('abort', relay, { once: true });
  }
  return { signal: merged.signal, cleanup };
}

async function api(path, options) {
  if (location.protocol === 'file:') throw new Error('离线版不支持登录同步');
  if (navigator.onLine === false) throw new Error('当前处于离线状态');
  const opt = options || {};
  const timeoutController = typeof AbortController !== 'undefined' ? new AbortController() : null;
  // 超时必须覆盖响应体和 JSON 解析，不能只覆盖收到响应头的阶段。
  const timer = timeoutController ? setTimeout(() => {
    try { timeoutController.abort(); } catch {}
  }, opt.timeout || 30000) : null;
  const epochController = apiEpochController;
  const epochSignal = epochController && epochController.signal;
  const abortBundle = combinedAbortSignal([opt.signal, timeoutController && timeoutController.signal, epochSignal]);
  let body;
  let headers = {};
  if (opt.body !== undefined) {
    const text = JSON.stringify(opt.body);
    body = text;
    headers = { 'content-type': 'application/json' };
    if (opt.compress && text.length >= 2048 && typeof CompressionStream !== 'undefined' && typeof Blob !== 'undefined') {
      try {
        body = await new Response(
          new Blob([text], { type: 'application/json' }).stream().pipeThrough(new CompressionStream('gzip')),
        ).arrayBuffer();
        headers = { 'content-type': 'application/octet-stream', 'x-ky-encoding': 'gzip' };
      } catch {}
    }
  }
  try {
    let res;
    try {
      res = await fetch('/api' + path, {
        method: opt.method || (opt.body !== undefined ? 'POST' : 'GET'),
        credentials: 'same-origin',
        headers,
        body,
        keepalive: opt.keepalive === true,
        signal: abortBundle.signal,
      });
    } catch (e) {
      if (e && e.name === 'AbortError' && opt.signal && opt.signal.aborted) throw e;
      if (e && e.name === 'AbortError' && epochSignal && epochSignal.aborted) throw e;
      if (e && e.name === 'AbortError' && timeoutController && timeoutController.signal.aborted) {
        throw new Error('网络请求超时，请稍后重试');
      }
      throw new Error(navigator.onLine === false ? '当前处于离线状态' : '网络请求超时，请稍后重试');
    }

    let text = '';
    try {
      text = await res.text();
    } catch (e) {
      if (e && e.name === 'AbortError' && opt.signal && opt.signal.aborted) throw e;
      if (e && e.name === 'AbortError' && epochSignal && epochSignal.aborted) throw e;
      if (e && e.name === 'AbortError' && timeoutController && timeoutController.signal.aborted) {
        throw new Error('网络请求超时，请稍后重试');
      }
      throw new Error('读取服务器响应失败，请稍后重试');
    }

    let data = null;
    let parseError = null;
    if (text) {
      try { data = JSON.parse(text); }
      catch (e) { parseError = e; }
    }
    if (res.status === 401 && path !== '/login' && path !== '/register') handleSessionExpired();
    if (res.status === 409 && data && data.code === 'ACCOUNT_MISMATCH') { refreshAuth(); }
    if (!res.ok) {
      const err = new Error((data && data.error) || ('请求失败 ' + res.status));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    if (res.status === 204) return {};
    if (parseError) {
      const err = new Error('服务器响应格式错误');
      err.status = res.status;
      throw err;
    }
    if (!text) throw new Error('服务器返回空响应');
    return data || {};
  } finally {
    if (timer) clearTimeout(timer);
    abortBundle.cleanup();
  }
}


// 本地四块进度必须一起成功或一起失败。localStorage 没有多键事务：
// 逐键调用 save() 时，第二块写失败会留下「新 state + 旧 chapter/conf」的半导入状态。
// 这里保留每个键的原始文本，任意一次写入失败就按原文本回滚。
function commitStores(next) {
  const nextChapters = next.chapterData === undefined ? chapterData : next.chapterData;
  const restPairs = [
    ['ky_chapter_v1', nextChapters],
    [LS_POS, positionStoreFromChapters(nextChapters)],
    [LS_DAILY, next.daily],
    [LS_CONF, next.conf],
  ];
  let texts;
  try { texts = restPairs.map(([, value]) => JSON.stringify(value)); }
  catch { return false; }
  const storageKeys = restPairs.map(([key]) => scopedKey(key));
  const before = storageKeys.map(key => {
    try { return localStorage.getItem(key); } catch { return null; }
  });
  try {
    for (let i = 0; i < storageKeys.length; i += 1) localStorage.setItem(storageKeys[i], texts[i]);
  } catch {
    for (let i = 0; i < storageKeys.length; i += 1) {
      try {
        if (before[i] === null) localStorage.removeItem(storageKeys[i]);
        else localStorage.setItem(storageKeys[i], before[i]);
      } catch {}
    }
    showStorageWarning();
    return false;
  }
  // state 用 generation 分片原子切换；它失败时旧 generation 仍完整，回滚其余三块即可。
  if (next.state !== undefined && !writeStateStorageForScope(next.state, authUser)) {
    for (let i = 0; i < storageKeys.length; i += 1) {
      try {
        if (before[i] === null) localStorage.removeItem(storageKeys[i]);
        else localStorage.setItem(storageKeys[i], before[i]);
      } catch {}
    }
    return false;
  }
  if (next.state !== undefined) markStateChanged();
  else invalidateSnapshotCache();
  for (const key of [LS_STATE, ...restPairs.map(([key]) => key)]) {
    try { bus.emit('data:change', key); } catch {}
  }
  return true;
}

function objectRecord(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
function boundedInt(value, min, max, fallback) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, Math.floor(n)));
}
// 操作时间不能来自遥远的未来，否则一次坏备份就能让后续真实操作永远合并失败。
// due 是唯一允许向未来延伸的字段，但仍限制在一以内年，避免 Number 溢出。
function safeTimestamp(value, now, futureMs) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.min(Math.floor(n), now + Math.max(0, Number(futureMs) || 0));
}
function cleanIcon(icon) {
  if (!objectRecord(icon)) return null;
  if (icon.kind === 'preset') {
    const preset = ICON_PRESETS.find(p => p.id === icon.id);
    return preset ? { kind: 'preset', id: preset.id } : null;
  }
  if (icon.kind === 'image' && typeof icon.data === 'string'
      && icon.data.length <= ICON_DATA_MAX
      && /^data:image\/(?:png|jpe?g|webp|gif);base64,/i.test(icon.data)) {
    const out = { kind: 'image', data: icon.data };
    if (typeof icon.name === 'string') out.name = icon.name.slice(0, 80);
    return out;
  }
  return null;
}
function validateStateStore(store, now) {
  if (!objectRecord(store)) return {};
  const out = {};
  let count = 0;
  for (const [name, rec] of Object.entries(store)) {
    if (name === '__proto__' || !name || name.length > 120 || !objectRecord(rec) || count >= 20000) continue;
    count += 1;
    if (rec.del === 1) {
      out[name] = { del: 1, t: safeTimestamp(rec.t, now, 0) };
      continue;
    }
    const clean = {};
    const w = boundedInt(rec.w, 0, 1000000, 0);
    const seen = boundedInt(rec.seen, 0, 1000000, 0);
    const due = safeTimestamp(rec.due, now, 365 * DAY);
    const t = safeTimestamp(rec.t, now, 0);
    if (w) clean.w = w;
    if (rec.mastered === true) clean.mastered = true;
    if (seen) clean.seen = seen;
    if (due > now) clean.due = due;
    else if (due) clean.due = due;
    if (t) clean.t = t;
    out[name] = clean;
  }
  return out;
}
function validateChapterStore(store, now) {
  if (!objectRecord(store)) return {};
  const out = {};
  for (const [key, rec] of Object.entries(store)) {
    if (key === '__proto__' || !/^[a-z][a-z0-9_-]{0,31}:\d{1,6}$/i.test(key) || !objectRecord(rec)) continue;
    if (rec.del === 1) {
      out[key] = { del: 1, t: safeTimestamp(rec.t, now, 0) };
      continue;
    }
    const order = [];
    const names = new Set();
    if (Array.isArray(rec.order)) {
      for (const name of rec.order) {
        if (typeof name !== 'string' || !name || name.length > 120 || names.has(name)) continue;
        names.add(name);
        order.push(name);
        if (order.length >= CHAPTER_SIZE * 2) break;
      }
    }
    const clean = {
      order,
      pos: boundedInt(rec.pos, 0, CHAPTER_SIZE * 2, 0),
      t: safeTimestamp(rec.t, now, 0),
    };
    if (typeof rec.posWord === 'string' && rec.posWord.length <= 120) clean.posWord = rec.posWord;
    if (rec.shuffled === true) clean.shuffled = true;
    out[key] = clean;
  }
  return out;
}
function validateDailyStore(store, now) {
  const out = pruneDaily(store);
  for (const [key, rec] of Object.entries(out)) {
    const at = new Date(key + 'T00:00:00').getTime();
    if (!Number.isFinite(at) || at > now + DAY) {
      delete out[key];
      continue;
    }
    if (!rec.del) {
      rec.s = boundedInt(rec.s, 0, 1000000, 0);
      rec.m = boundedInt(rec.m, 0, 1000000, 0);
      rec.t = safeTimestamp(rec.t, now, 0);
      if (!rec.t) delete rec.t;
    } else {
      rec.t = safeTimestamp(rec.t, now, 0);
    }
  }
  return out;
}
function validateConfStore(store) {
  if (!objectRecord(store)) return { ...conf };
  const now = Date.now();
  const deck = Object.prototype.hasOwnProperty.call(DECKS, store.deck) ? store.deck : 'core';
  const chapter = boundedInt(store.chapter, 0, 100000, 0);
  const byDeck = {};
  if (objectRecord(store.deckChapter)) {
    for (const [name, value] of Object.entries(store.deckChapter)) {
      if (Object.prototype.hasOwnProperty.call(DECKS, name) && Number.isInteger(Number(value))) {
        byDeck[name] = boundedInt(value, 0, 100000, 0);
      }
    }
  }
  byDeck[deck] = chapter;
  const out = {
    deck,
    chapter,
    deckChapter: byDeck,
    progressAt: safeTimestamp(store.progressAt, now, 0),
    showByDefault: store.showByDefault === true,
    speak: store.speak !== false,
    speakLang: store.speakLang === 'zh' ? 'zh' : 'en',
    icon: cleanIcon(store.icon),
    iconAt: safeTimestamp(store.iconAt, now, 0),
  };
  out.resetAt = safeTimestamp(store.resetAt, now, 0);
  const serverFenceAt = safeTimestamp(store.serverFenceAt, now, 0);
  if (serverFenceAt) {
    out.serverFenceAt = serverFenceAt;
    out.serverFenceMode = store.serverFenceMode === 'import' ? 'import' : 'clear';
    const operationId = normalizeOperationId(store.serverFenceOperationId);
    if (out.serverFenceMode === 'import' && operationId) out.serverFenceOperationId = operationId;
  }
  if (store.overwritePending === true) out.overwritePending = true;
  if (store.overwriteMode === 'import' || store.overwriteMode === 'clear') out.overwriteMode = store.overwriteMode;
  const importStartedAt = safeTimestamp(store.importStartedAt, now, 0);
  if (importStartedAt) out.importStartedAt = importStartedAt;
  const importOperationId = normalizeOperationId(store.importOperationId);
  if (importOperationId) out.importOperationId = importOperationId;
  return out;
}
// 只把和默认值不同的字段写进 payload。全量写 w:0 / mastered:false / due:0
// 会把进度撑到接近 512KB 上限，一旦越线就是永久 413，同步彻底停摆且没有降级路径。
function slimRecord(rec) {
  if (!rec || typeof rec !== 'object') return rec;
  if (rec.del) return { del: 1, t: Number(rec.t) || 0 };
  const out = {};
  if (rec.w) out.w = rec.w;
  if (rec.mastered) out.mastered = true;
  if (rec.seen) out.seen = rec.seen;
  const t = Number(rec.t) || 0;
  if (t) out.t = t;
  const due = Number(rec.due) || 0;
  if (due) out.due = due;
  return out;
}

function snapshot() {
  if (snapshotCacheRevision === localRevision && snapshotCacheValue) return snapshotCacheValue;
  const slimState = {};
  for (const [name, rec] of Object.entries(state)) {
    if (name === '__proto__') continue;
    slimState[name] = slimRecord(rec);
  }
  // 只上传能通过校验的图标：坏数据不该被同步到别的设备，也不该撑大 payload
  const iconOk = !!configuredIcon();
  const value = {
    state: slimState,
    chapterData,
    daily,
    conf: {
      deck: conf.deck,
      chapter: Number(conf.chapter) || 0,
      deckChapter: conf.deckChapter || {},
      progressAt: Number(conf.progressAt) || 0,
      showByDefault: !!conf.showByDefault,
      speak: conf.speak !== false,
      speakLang: conf.speakLang === 'zh' ? 'zh' : 'en',
      // 图标是账号级偏好：跟着账号走，换手机不用重设。体积由 ICON_DATA_MAX 兜住。
      // iconAt 必须无条件上传：icon 为 null 时 iconOk 是 false，若这时把 iconAt 也归零，
      // 服务端会判定「本机这次没动过图标」，云端旧图标永远删不掉，另一台设备也变不回默认。
      icon: iconOk ? conf.icon : null,
      iconAt: Number(conf.iconAt) || 0,
      resetAt: Number(conf.resetAt) || 0,
      serverFenceAt: Number(conf.serverFenceAt) || 0,
      serverFenceMode: conf.serverFenceMode === 'import' ? 'import' : (conf.serverFenceMode === 'clear' ? 'clear' : ''),
      serverFenceOperationId: normalizeOperationId(conf.serverFenceOperationId),
      importStartedAt: Number(conf.importStartedAt) || 0,
      importOperationId: normalizeOperationId(conf.importOperationId),
    },
  };
  snapshotCacheRevision = localRevision;
  snapshotCacheValue = value;
  return value;
}

function applySnapshot(d) {
  if (!objectRecord(d)) return false;
  const now = Date.now();
  const nextState = d.state === undefined ? state : validateStateStore(d.state, now);
  const nextChapters = d.chapterData === undefined ? chapterData : validateChapterStore(d.chapterData, now);
  const nextDaily = d.daily === undefined ? daily : validateDailyStore(d.daily, now);
  const nextConf = d.conf === undefined ? { ...conf } : validateConfStore(d.conf);
  // 位置也要先以「提交成功后的 conf」计算，不能先改全局变量再落盘：
  // 写 localStorage 失败时，页面可能已经跳到新章节，内存与磁盘永久分叉。
  const nextDeck = Object.prototype.hasOwnProperty.call(DECKS, nextConf.deck) ? nextConf.deck : 'core';
  const savedChapter = Number((nextConf.deckChapter || {})[nextDeck]);
  const nextChapter = Number.isInteger(savedChapter) && savedChapter >= 0
    ? savedChapter : Math.max(0, Number(nextConf.chapter) || 0);
  nextConf.deck = nextDeck;
  nextConf.chapter = nextChapter;
  nextConf.deckChapter = { ...(nextConf.deckChapter || {}), [nextDeck]: nextChapter };
  if (!commitStores({ state: nextState, chapterData: nextChapters, daily: nextDaily, conf: nextConf })) return false;
  state = nextState;
  chapterData = nextChapters;
  daily = nextDaily;
  conf = nextConf;
  activeDeck = nextDeck;
  invalidateSnapshotCache();
  const deckSelect = $('deckSelect');
  if (deckSelect) deckSelect.value = activeDeck;
  updateDeckMeta();
  // 同步回来的进度是权威位置：直接跳到云端当前词库、章节和单词，不保留本机旧位置。
  loadChapter(nextChapter);
  renderChapters();
  updateStats();
  renderList();
  renderAuth();
  renderIconSettings();
  syncFavicon(currentIcon());
  return true;
}
function authSay(msg, kind) {
  const el = $('authStatus');
  el.textContent = msg || '';
  el.className = 'auth-status' + (kind ? ' ' + kind : '');
}

// 登录/退出后重新装载该账号自己的进度
function reloadSpace() {
  if (authUser) {
    const canonical = accountScope(authUser);
    const legacySuffix = '@' + authUser;
    const targetSuffix = '@' + canonical;
    if (legacySuffix !== targetSuffix) {
      const shardKeys = [];
      for (let i = 0; i < localStorage.length; i += 1) {
        const key = localStorage.key(i) || '';
        if (key.startsWith(LS_STATE + '#') && key.endsWith(legacySuffix)) shardKeys.push(key);
      }
      for (const oldKey of shardKeys) {
        const newKey = oldKey.slice(0, -legacySuffix.length) + targetSuffix;
        if (!localStorage.getItem(newKey)) localStorage.setItem(newKey, localStorage.getItem(oldKey));
        localStorage.removeItem(oldKey);
      }
    }
    for (const base of SCOPED_KEYS) {
      if (base === LS_STAMP) continue;
      const legacy = base + '@' + authUser;
      const target = base + '@' + canonical;
      if (legacy !== target) {
        const legacyRaw = localStorage.getItem(legacy);
        const targetRaw = localStorage.getItem(target);
        if (legacyRaw && !targetRaw) {
          localStorage.setItem(target, legacyRaw);
          localStorage.removeItem(legacy);
        } else if (legacyRaw) {
          // target 已有新数据时不能覆盖；旧大小写键若确属同一账号则清掉，避免下次重复迁移。
          try { localStorage.removeItem(legacy); } catch {}
        }
      }
    }
  }
  const now = Date.now();
  state = validateStateStore(load(LS_STATE, {}), now);
  chapterData = validateChapterStore(load('ky_chapter_v1', {}), now);
  daily = validateDailyStore(load(LS_DAILY, {}), now);
  conf = validateConfStore(Object.assign({
    deck: 'core', chapter: 0, deckChapter: {}, progressAt: 0,
    showByDefault: false, speak: true, speakLang: 'en', icon: null, iconAt: 0,
  }, load(LS_CONF, {})));
  delete conf.autoShow;
  delete conf.forceAt;
  // 换了账号，「已认识」缓存必须重建，否则会沿用上一个账号的词
  masteredWordsCache = null;
  activeDeck = conf.deck;
  $('deckSelect').value = activeDeck;
  updateDeckMeta();
  renderChapters();
  loadChapter(resumePosition());
  conf.deckChapter = conf.deckChapter || {};
  conf.deckChapter[activeDeck] = curChapter;
  conf.chapter = curChapter;
  commitStores({ state, chapterData, daily, conf });
  renderChapters();
  updateStats();
  renderList();
  renderIconSettings();
  syncFavicon(currentIcon());
  // 账号切换后开启一轮全新的会话；旧请求即使晚回来也不能影响新账号。
  abortApiRequests();
  clearTimeout(syncTimer);
  syncEpoch += 1;
  syncing = false;
  pendingSync = false;
  syncInitialized = false;
  lastSyncAt = 0;
  syncDirty = !!authUser;
  syncPaused = false;
  localRevision += 1;
}
function parseStore(raw) {
  try {
    const v = JSON.parse(raw);
    return v && typeof v === 'object' ? v : {};
  } catch { return {}; }
}
// 登录时把游客空间里背的进度并进账号空间：逐词、逐章按时间取新。
// 以前是「账号空间存在就整体放弃游客进度」，注册过一次再以游客身份背词就会丢。
// 游客空间里的墓碑只表示「这个游客空间被清空过」，不该顺手把账号里同样的词一起删掉。
function withoutTombstones(store) {
  const out = {};
  for (const [k, v] of Object.entries(store || {})) {
    if (v && v.del) continue;
    out[k] = v;
  }
  return out;
}
function adoptGuestProgress(username) {
  try {
    const scope = accountScope(username);
    const chapterStoreKey = 'ky_chapter_v1@' + scope;
    const confKey = LS_CONF + '@' + scope;
    const dailyKey = LS_DAILY + '@' + scope;
    const guestStateStore = readStateStoreForScope(null, {});
    const guestChapterStore = parseStore(localStorage.getItem('ky_chapter_v1'));
    const guestDailyStore = parseStore(localStorage.getItem(LS_DAILY));
    const accountStateStore = readStateStoreForScope(username, {});
    const accountChapterStore = parseStore(localStorage.getItem(chapterStoreKey));
    const accountDailyStore = parseStore(localStorage.getItem(dailyKey));

    const mergedState = mergeState(accountStateStore, withoutTombstones(guestStateStore));
    if (Object.keys(mergedState).length) writeStateStorageForScope(mergedState, username);

    const mergedChapters = mergeChapters(accountChapterStore, withoutTombstones(guestChapterStore));
    if (Object.keys(mergedChapters).length) {
      localStorage.setItem(chapterStoreKey, JSON.stringify(mergedChapters));
      localStorage.setItem(LS_POS + '@' + scope, JSON.stringify(positionStoreFromChapters(mergedChapters)));
    }

    // 每日学习节奏也并进账号空间：同一天取新（带 t 时）或取大（老数据），不同天取并集
    const mergedDaily = mergeDaily(accountDailyStore, withoutTombstones(guestDailyStore), todayTs());
    if (Object.keys(mergedDaily).length) {
      localStorage.setItem(dailyKey, JSON.stringify(mergedDaily));
    }

    // 位置（哪本词书 / 第几章）按合并规则定，不能整份覆盖：
    // 用游客 conf 直接覆盖账号 conf，会把账号侧的 deckChapter、图标、朗读设置全丢掉。
    const accountConf = parseStore(localStorage.getItem(confKey));
    const guestConf = parseStore(localStorage.getItem(LS_CONF));
    const destructiveKeys = [
      'overwritePending', 'overwriteMode', 'resetAt', 'serverFenceAt', 'serverFenceMode',
      'serverFenceOperationId', 'importStartedAt', 'importOperationId', 'forceAt',
    ];
    for (const key of destructiveKeys) delete guestConf[key];
    const mergedConf = mergeConf(
      accountConf,
      guestConf,
      accountChapterStore,
      guestChapterStore,
      latestActivity(accountStateStore, accountDailyStore),
      latestActivity(guestStateStore, guestDailyStore),
    );
    // 「清空后待同步」的标志不能从游客空间带进来：未登录时清空的是游客进度，
    // 登录进来不该顺手清掉账号的云端进度。账号自己攒下的标志要保留，
    // 所以按「账号这一侧是否真的待同步」判断值，而不是判断键存不存在
    // （账号清过一次时会留着 overwritePending: false，按键判断会把它误认成待同步）。
    for (const key of destructiveKeys) {
      if (Object.prototype.hasOwnProperty.call(accountConf, key)) mergedConf[key] = accountConf[key];
      else delete mergedConf[key];
    }
    localStorage.setItem(confKey, JSON.stringify(mergedConf));
  } catch {}
}

function configuredIcon() {
  const icon = conf.icon;
  if (!icon || typeof icon !== 'object') return null;
  if (icon.kind === 'preset') {
    const preset = ICON_PRESETS.find(p => p.id === icon.id);
    return preset ? { ...preset, kind: 'preset' } : null;
  }
  if (icon.kind === 'image' && typeof icon.data === 'string'
      && icon.data.length <= ICON_DATA_MAX
      && /^data:image\/(?:png|jpe?g|webp|gif);base64,/i.test(icon.data)) return icon;
  return null;
}
function currentIcon() {
  return configuredIcon() || ICON_PRESETS[0];
}
function iconDataUrl(icon) {
  return icon.kind === 'image'
    ? icon.data
    : 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(icon.svg);
}
function iconLabel(icon) {
  return icon.kind === 'image' ? (icon.name ? '自定义：' + icon.name : '自定义图片') : icon.label;
}
let faviconToken = 0;
function syncFavicon(icon) {
  try {
    const link = $('appFavicon');
    if (link) {
      link.href = iconDataUrl(icon);
      link.type = icon.kind === 'image'
        ? icon.data.slice(5, icon.data.indexOf(';'))
        : 'image/svg+xml';
    }
    const touch = $('appleTouchIcon');
    if (!touch) return;
    // 连点图标时，旧图的 onload 可能后到，把刚换上的图又盖回去
    const token = ++faviconToken;
    const image = new Image();
    image.onload = () => {
      if (token !== faviconToken) return;
      try {
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 180;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#f4f6f3';
        ctx.fillRect(0, 0, 180, 180);
        ctx.drawImage(image, 0, 0, 180, 180);
        touch.href = canvas.toDataURL('image/png');
      } catch {
        touch.href = iconDataUrl(icon);
      }
    };
    image.onerror = () => { if (token === faviconToken) touch.href = iconDataUrl(icon); };
    image.src = iconDataUrl(icon);
  } catch {}
}
function renderIconSettings() {
  const preview = $('iconPreview');
  const choices = $('iconChoices');
  if (!preview || !choices) return;
  const active = configuredIcon();
  const selected = currentIcon();
  preview.replaceChildren();
  const previewImg = new Image();
  previewImg.src = iconDataUrl(selected);
  previewImg.alt = '';
  preview.append(previewImg);
  // 自定义图片时不能把「默认 Logo」标成选中，那会和左上角的实际图标自相矛盾
  const selectedId = active ? (active.kind === 'preset' ? active.id : null) : 'brand';
  $('iconCurrentName').textContent = active ? iconLabel(active) : '默认 Logo';
  choices.replaceChildren();
  for (const preset of ICON_PRESETS) {
    const isSelected = preset.id === selectedId;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'icon-choice' + (isSelected ? ' active' : '');
    button.title = preset.label;
    button.setAttribute('aria-label', '使用' + preset.label + '图标');
    button.setAttribute('aria-pressed', String(isSelected));
    const img = new Image();
    img.src = iconDataUrl(preset);
    img.alt = '';
    const label = document.createElement('span');
    label.textContent = preset.label;
    button.append(img, label);
    button.onclick = () => {
      conf.icon = preset.id === 'brand' ? null : { kind: 'preset', id: preset.id };
      conf.iconAt = Date.now();
      save(LS_CONF, conf);
      renderAuth();
      renderIconSettings();
      syncFavicon(currentIcon());
      $('iconStatus').textContent = preset.id === 'brand'
        ? '已恢复默认 Logo。'
        : '已更换为「' + preset.label + '」图标。';
    };
    choices.append(button);
  }
  $('iconReset').disabled = !active;
}
function renderAuth() {
  const btn = $('accountBtn');
  const avatar = $('accountAvatar');
  const active = configuredIcon();
  if (active) {
    avatar.textContent = '';
    const image = new Image();
    image.src = iconDataUrl(active);
    image.alt = '';
    avatar.append(image);
    avatar.title = iconLabel(active) + (authUser ? ' · ' + authUser : '');
  } else {
    avatar.textContent = '';
    avatar.insertAdjacentHTML('afterbegin', AVATAR_LOGO);
    avatar.title = authUser ? (authUser + ' · 默认 Logo') : '未登录，点这里登录或注册';
  }
  btn.classList.toggle('custom-icon', !!active);
  btn.classList.toggle('online', !!authUser);
  // 头像只有 34px，光靠绿点和底色区分登录态，读屏用户和色弱用户都读不出来
  btn.setAttribute('aria-label', authUser
    ? '账号：' + authUser + '，点这里管理账号与离线缓存'
    : '未登录，点这里登录或注册');
  $('authSync').classList.toggle('hidden', !authUser);
  $('pairNewBox').classList.toggle('hidden', !authUser);
  $('pairClaimToggle').classList.toggle('hidden', !!authUser);
  if (authUser) $('pairClaimBox').classList.add('hidden');
  else $('pairCodeShow').classList.add('hidden');
  $('authForm').classList.toggle('hidden', !!authUser);
  $('authMode').classList.toggle('hidden', !!authUser);
  $('wxLogin').classList.toggle('hidden', !!authUser);
  document.querySelector('.auth-sep').classList.toggle('hidden', !!authUser);
  $('authTitle').textContent = authUser ? '已登录：' + authUser : (authMode === 'login' ? '登录' : '注册');
  $('authSubmit').textContent = authMode === 'login' ? '登录' : '注册并登录';
  $('authPass').setAttribute('autocomplete', authMode === 'login' ? 'current-password' : 'new-password');
}

function scheduleCloudSync(delay) {
  if (!authUser || syncPaused || navigator.onLine === false) return;
  clearTimeout(syncTimer);
  const wait = typeof delay === 'number' ? delay : 6000;
  syncTimer = setTimeout(() => {
    if (syncing) { pendingSync = true; return; }
    syncNow(true);
  }, wait);
}

let pendingSync = false;
let lastSyncAt = 0;
let lastFlushAt = 0;

// 页面要走了就别再等 6 秒防抖：用 keepalive 补发一次。
// 否则最后几秒背的词只落在 localStorage，换设备就看不到。
function flushSyncOnHide() {
  if (!authUser || !syncDirty || syncing || navigator.onLine === false) return;
  const now = Date.now();
  if (now - lastFlushAt < 3000) return;   // pagehide 与 visibilitychange 会连着触发
  lastFlushAt = now;
  clearTimeout(syncTimer);
  // keepalive 有 64KB 的体积上限，超了会直接抛错；
  // 这里只做尽力而为，失败就等下次正常同步。
  putState(snapshot(), lastSyncAt, false, true).catch(() => {});
}
window.addEventListener('pagehide', flushSyncOnHide);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') flushSyncOnHide();
});

function noteLocalChange() {
  if (applyingRemote) return;
  syncDirty = true;
  localRevision += 1;
  invalidateSnapshotCache();
}

/*__MERGE__*/
// 键序无关的比较：合并后的对象与本地对象键序常常不同，
// 用 JSON.stringify 直接比会永远判定「有变化」，每次同步都重放位置。
function sameJson(a, b) {
  const x = stableJson(a), y = stableJson(b);
  return x !== null && x === y;
}

async function putState(payload, baseUpdatedAt, force, keepalive) {
  const body = {
    payload,
    baseUpdatedAt: Math.max(0, Number(baseUpdatedAt) || 0),
    expectedUsername: authUser,
  };
  if (force) body.force = true;
  return api('/state', { method: 'PUT', body, compress: true, timeout: 45000, keepalive });
}

// 只取「进度位置」相关的字段：合并后的 conf 还带着图标等设置，
// 全量比较会把每次同步都判成有变化，然后把用户拉到旧位置。
function progressKey(c) {
  const x = c || {};
  // 账号级设置也要进入比较；只比较位置会让“只换图标/朗读设置”的云端变化永远不落地。
  return [x.deck || '', Number(x.chapter) || 0, x.deckChapter || {}, Number(x.progressAt) || 0,
    x.showByDefault === true, x.speak !== false, x.speakLang === 'zh' ? 'zh' : 'en',
    x.icon || null, Number(x.iconAt) || 0, Number(x.resetAt) || 0,
    Number(x.serverFenceAt) || 0, x.serverFenceMode || '', normalizeOperationId(x.serverFenceOperationId),
    Number(x.importStartedAt) || 0, normalizeOperationId(x.importOperationId)];
}
function applyMergedSnapshot(merged, local) {
  const changedLocally = !sameJson(
    { s: merged.state, c: merged.chapterData, d: merged.daily, p: progressKey(merged.conf) },
    { s: local.state, c: local.chapterData, d: local.daily, p: progressKey(local.conf) },
  );
  if (changedLocally) {
    applyingRemote = true;
    try {
      // 应用失败不能被当成“没有变化”，否则调用方会推进 lastSyncAt 并清掉 dirty。
      if (!applySnapshot(merged)) throw new Error('本地存储空间不足，云端进度未能应用');
    } finally { applyingRemote = false; }
  }
  return changedLocally;
}

async function syncWithServer(local, guard, reset) {
  // 位置/顺序参与合并，主程序更新后必须重新走服务端合并，不能沿用旧的增量版本。
  lastSyncAt = 0;
  const body = { payload: local, expectedUsername: authUser };
  // reset 让服务端在云端快照上补全墓碑：客户端只知道本机有哪些词，
  // 只在别的设备上出现过的词必须由服务端来删，否则下次合并又活过来。
  if (reset) {
    body.reset = true;
    // 带上本机的重置时刻，墓碑时间取它与服务端 now 的较早者；
    // 否则客户端时钟慢几秒时，「清空之后马上又背的词」会被判成旧记录删掉。
    body.mode = conf.overwriteMode === 'import' ? 'import' : 'clear';
    if (body.mode === 'import') {
      body.importStartedAt = Number(conf.importStartedAt) || Date.now();
      body.operationId = normalizeOperationId(conf.importOperationId);
    } else {
      body.resetAt = Number(conf.resetAt) || Date.now();
    }
  }
  const result = await api('/state/sync', {
    method: 'POST',
    body,
    compress: true,
    timeout: 45000,
  });
  // 请求在途的这几十秒里用户又背了词：这批新词不在 merged 里，
  // 现在 apply 会连本地带云端一起抹掉。交回下一轮再合并。
  if (guard && !guard()) {
    // lastSyncAt 也不能推进到这一版：否则下一轮 syncDirty 会拿本地旧快照
    // 走 PUT 覆盖（CAS 恰好通过），把云端刚合并进来的数据抹掉。
    // 保持 0 就会在下一轮触发 409，从而重新走一次服务端合并。
    lastSyncAt = 0;
    return { result, changedLocally: false, skipped: true };
  }
  const changedLocally = applyMergedSnapshot(result.payload, local);
  lastSyncAt = result.updatedAt || Date.now();
  return { result, changedLocally };
}

// 微信式：登录后自动双向合并，用户不需要点任何按钮。
// 合并一律交给服务端（/state/sync）完成：本地再合并一遍等于把同一份
// 三百多 KB 的数据重复序列化几次，还多一套可能和服务端跑偏的逻辑。
async function syncNow(quiet) {
  if (!authUser) return;
  if (syncPaused && quiet) return;
  if (!quiet) syncPaused = false;
  if (syncing) { pendingSync = true; return; }
  syncing = true;
  const epoch = syncEpoch;
  const startedAs = authUser;
  const revision = localRevision;
  const stale = () => epoch !== syncEpoch || authUser !== startedAs;
  // 「这轮同步的输入还有效吗」：不仅账号没换，本地也没再产生新进度。
  // 弱网下一次同步挂 20 秒，这期间背的词不在合并结果里，
  // 直接 apply 会把本地和云端一起抹掉——所以一律交回下一轮。
  const fresh = () => !stale() && localRevision === revision;
  if (!quiet) {
    $('syncNowBtn').disabled = true;
    authSay('正在同步…');
  }
  try {
    let result = 'pulled';
    // 清空 / 导入之后必须走一次带 reset 的服务端合并，
    // 否则云端独有的词没人写墓碑，下次合并就活过来
    const overwrite = !!conf.overwritePending;
    if (overwrite || (!syncInitialized && syncDirty)) {
      const synced = await syncWithServer(snapshot(), fresh, overwrite);
      if (!synced.skipped) syncInitialized = true;
      if (overwrite) {
        // 请求已经成功，服务端墓碑已落地；即使这次因为本地又变了没 apply，
        // 也不该再重发 reset——那会把另一台设备在这期间背的词一起删掉。
        // 直接落盘而不走 save()：这个标志不是学习进度，不该触发 data:change。
        // 用 delete 而不是置 false：留着 false 会让「按值判断」的地方以为它存在过。
        delete conf.overwritePending;
        delete conf.overwriteMode;
        delete conf.importStartedAt;
        delete conf.importOperationId;
        try { localStorage.setItem(scopedKey(LS_CONF), JSON.stringify(conf)); } catch {}
      }
      result = synced.skipped ? 'unchanged' : (synced.changedLocally ? 'merged' : 'pushed');
    } else if (!syncInitialized) {
      const synced = await syncWithServer(snapshot(), fresh);
      if (!synced.skipped) syncInitialized = true;
      result = synced.skipped ? 'unchanged' : (synced.changedLocally ? 'merged' : 'pulled');
    } else if (syncDirty) {
      const local = snapshot();
      try {
        const saved = await putState(local, lastSyncAt);
        if (stale()) return;
        lastSyncAt = saved.updatedAt || Date.now();
        result = 'pushed';
      } catch (e) {
        if (e.status !== 409) throw e;
        const synced = await syncWithServer(snapshot(), fresh);
        result = synced.skipped ? 'unchanged' : (synced.changedLocally ? 'merged' : 'pushed');
      }
    } else {
      const expected = encodeURIComponent(authUser || '');
      const path = lastSyncAt ? '/state?since=' + encodeURIComponent(lastSyncAt) + '&expectedUsername=' + expected : '/state?expectedUsername=' + expected;
      const remote = await api(path);
      if (stale()) return;
      if (remote.unchanged) {
        lastSyncAt = remote.updatedAt || lastSyncAt;
        result = 'unchanged';
      } else {
        // 轮询发现云端变了：直接把本机快照交给服务端合并，一次往返拿到结果
        const synced = await syncWithServer(snapshot(), fresh);
        if (!synced.skipped) syncInitialized = true;
        result = synced.skipped ? 'unchanged' : (synced.changedLocally ? 'merged' : 'pulled');
      }
    }
    if (stale()) return;
    if (localRevision === revision) syncDirty = false;
    if (!quiet) {
      authSay(result === 'pushed' ? '已上传本机进度'
        : result === 'merged' ? '已合并云端进度'
        : '进度已同步', 'ok');
    }
  } catch (e) {
    if (e && e.status === 413) {
      syncPaused = true;
      authSay('云端进度超过 512KB，请导出备份后清理旧记录再同步。', 'err');
      showSessionNotice('云端进度过大，自动同步已暂停。', 8000);
    } else if (!stale() && !quiet) authSay('同步失败：' + e.message, 'err');
  } finally {
    // 按钮复位移到 epoch 判断外面：会话过期会重置 syncEpoch，
    // 之前那样会让「立即同步」一直停在 disabled 直到刷新页面。
    $('syncNowBtn').disabled = false;
    if (epoch === syncEpoch) {
      syncing = false;
      if (pendingSync) {
        pendingSync = false;
        scheduleCloudSync();
      } else if (syncDirty && localRevision !== revision) {
        scheduleCloudSync(500);
      }
    }
  }
}

async function refreshAuth() {
  const before = authUser;
  try {
    const r = await api('/me');
    // 请求发出后用户可能已经登录成功（或退出了），这次结果已过期，直接丢弃，
    // 否则慢网络下会把刚登录的账号又踢回游客
    if (authUser !== before) return;
    const next = r.user ? r.user.username : null;
    if (next !== authUser) {
      if (!authUser && next) adoptGuestProgress(next);
      authUser = next;
      try {
        if (next) localStorage.setItem(LS_AUTH, next);
        else localStorage.removeItem(LS_AUTH);
      } catch {}
      reloadSpace();
    }
  } catch {
    // 离线时保留上次账号；若账号已在请求期间切换，不能把内存身份写回旧值。
  }
  renderAuth();
  if (authUser && !syncInitialized) scheduleCloudSync(200);
}

async function afterLogin(username) {
  sessionExpiredHandled = false;
  $('sessionWarn').classList.add('hidden');
  adoptGuestProgress(username);
  authUser = username;
  try { localStorage.setItem(LS_AUTH, username); } catch {}
  reloadSpace();
  renderAuth();
  // 登录成功后关闭弹窗并恢复页面可交互状态。
  closeAuthModal();
  showSessionNotice('已登录：' + username + '，正在同步进度…', 5000);
  setTimeout(() => syncNow(false), 0);
}

let authReturnFocus = null;
function openAuthModal() {
  authReturnFocus = document.activeElement;
  $('authModal').classList.remove('hidden');
  setPageInert(true, $('authModal'));
  const target = authUser ? focusablesIn($('authModal'))[0] : $('authUser');
  (target || $('authModal')).focus({ preventScroll: true });
}
function closeAuthModal() {
  if ($('authModal').classList.contains('hidden')) return;
  $('authModal').classList.add('hidden');
  setPageInert(false);
  const back = authReturnFocus;
  authReturnFocus = null;
  if (back && back.isConnected) back.focus({ preventScroll: true });
}
$('accountBtn').onclick = () => {
  openAuthModal();
  authSay('');
  loadWechatLogin();
  refreshAuth();
  renderIconSettings();
  refreshOfflineStat();
};
$('authClose').onclick = closeAuthModal;
$('authModal').onclick = event => {
  if (event.target === $('authModal')) closeAuthModal();
};
$('authModal').addEventListener('keydown', event => trapModalFocus(event, $('authModal'), closeAuthModal));
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
  const btn = $('authLogout');
  btn.disabled = true;
  try {
    await api('/logout', { method: 'POST', body: { expectedUsername: authUser } });
  } catch (e) {
    // 离线时服务端 session 还活着。这时假装退出，下次刷新会被自动登回去，
    // 用户会以为退出没生效。宁可报错也不要装作成功。
    btn.disabled = false;
    authSay('退出失败：' + ((e && e.message) || '网络异常') + '，请联网后再试', 'err');
    return;
  }
  btn.disabled = false;
  authUser = null;
  try { localStorage.removeItem(LS_AUTH); } catch {}
  reloadSpace();
  renderAuth();
  closeAuthModal();
  showSessionNotice('已退出登录，进度仍保存在本机', 5000);
};
$('pairClaimToggle').onclick = () => {
  const open = $('pairClaimBox').classList.toggle('hidden') === false;
  $('pairClaimToggle').setAttribute('aria-expanded', String(open));
};
$('pairClaimBtn').onclick = async () => {
  const code = $('pairCode').value.replace(/\D/g, '');
  if (code.length !== 6) { authSay('配对码是 6 位数字', 'err'); return; }
  try {
    const r = await api('/pair/claim', { body: { code } });
    $('pairCode').value = '';
    $('pairClaimBox').classList.add('hidden');
    await afterLogin(r.username);
  } catch (e) {
    authSay(e.message, 'err');
  }
};
$('pairNewBtn').onclick = async () => {
  try {
    const r = await api('/pair/new', { method: 'POST' });
    const box = $('pairCodeShow');
    box.classList.remove('hidden');
    box.textContent = r.code;
    const mins = Math.max(1, Math.round((r.expiresAt - Date.now()) / 60000));
    authSay('在另一台设备输入这 6 位码，' + mins + ' 分钟内有效', 'ok');
  } catch (e) {
    authSay(e.message, 'err');
  }
};
$('syncNowBtn').onclick = () => syncNow(false);
// 后台定时同步：降低频率，避免移动端持续联网导致卡顿。
setInterval(() => {
  if (!authUser || document.visibilityState !== 'visible' || navigator.onLine === false) return;
  syncNow(true);
}, 30000);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && authUser && navigator.onLine !== false) refreshAuth().finally(() => { if (authUser) syncNow(true); });
});
window.addEventListener('online', () => {
  if (authUser) scheduleCloudSync(500);
});

// 微信扫码接口只在用户首次打开登录面板时加载，避免首屏多一次网络请求。
let wechatLoginLoaded = false;
function loadWechatLogin() {
  if (wechatLoginLoaded) return;
  wechatLoginLoaded = true;
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
}
const idle = window.requestIdleCallback || (fn => setTimeout(fn, 1200));
idle(() => refreshAuth());

