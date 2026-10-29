let lastSpoken = '';
let speakVoice = null;
let zhVoice = null;
let voiceReady = false;
let speakBroken = false;
let speechToken = 0;
let audioFallbackTimer = null;
let offlineCacheTimer = null;
let pronunciationAudio = null;
let activePronunciationAudio = null;
// 必须与 sw.template.js 的 AUDIO_CACHE 版本号一致：SW 换缓存名会清空旧音频，
// 前端这两个「已经下载过」的标记要是还留着，就会以为全都下过了、永远不再补。
const AUDIO_CACHE_VERSION = 'v2';
const AUDIO_CACHE_NAME = 'ky-audio-' + AUDIO_CACHE_VERSION;
const AUDIO_WORDS_KEY = 'ky_audio_words_' + AUDIO_CACHE_VERSION;
const AUDIO_CACHE_CONFIRMED_HEADER = 'x-ky-cache';
const audioMarkerKey = (text, lang) => String(lang || 'en') + ':' + String(text || '');
const AUDIO_PRELOAD_AHEAD = 10;
// 只保留当前窗口附近的媒体元素；长期离线副本由 Cache Storage 承担。
const AUDIO_PLAYER_LIMIT = 32;
const AUDIO_BLOB_LIMIT = 24;
const audioPlayers = new Map();
const audioBlobUrls = new Map();
const audioFetching = new Set();
const AUDIO_CACHE_CONFIRMED_VALUES = new Set(['hit', 'stored']);
const normalizeAudioMarker = value => {
  const raw = String(value || '');
  return raw.includes(':') ? raw : 'en:' + raw;
};
function parseAudioMarkers(raw) {
  const out = new Set();
  try {
    const rows = raw ? JSON.parse(raw) : [];
    for (const row of Array.isArray(rows) ? rows : []) {
      const marker = normalizeAudioMarker(row);
      if (marker !== 'en:') out.add(marker);
    }
  } catch {}
  return out;
}
let audioMarkerBase;
try { audioMarkerBase = parseAudioMarkers(localStorage.getItem(AUDIO_WORDS_KEY)); }
catch { audioMarkerBase = new Set(); }
let audioMarkerAdds = new Set();
let audioMarkerRemoves = new Set();
let audioCachedWords = new Set(audioMarkerBase);
// 页面和 Service Worker 必须使用同一个确认协议：普通 200 不能冒充“已离线缓存”。
function audioCacheConfirmed(response) {
  return !!response && response.ok
    && AUDIO_CACHE_CONFIRMED_VALUES.has(String(response.headers.get(AUDIO_CACHE_CONFIRMED_HEADER) || '').toLowerCase());
}
let audioMarkerFlushTimer = null;
function flushAudioMarkers() {
  if (audioMarkerFlushTimer) { clearTimeout(audioMarkerFlushTimer); audioMarkerFlushTimer = null; }
  // 先读取其他标签页的最新集合，再只重放本标签页的增量，避免旧标签页把已淘汰项写回来。
  let latest;
  try { latest = parseAudioMarkers(localStorage.getItem(AUDIO_WORDS_KEY)); }
  catch { latest = new Set(audioMarkerBase); }
  for (const marker of audioMarkerRemoves) latest.delete(marker);
  for (const marker of audioMarkerAdds) latest.add(marker);
  try { localStorage.setItem(AUDIO_WORDS_KEY, JSON.stringify([...latest])); } catch {}
  audioMarkerBase = new Set(latest);
  audioCachedWords = new Set(latest);
  audioMarkerAdds.clear();
  audioMarkerRemoves.clear();
  try { updateOfflineStatus(); } catch {}
}
function replaceAudioMarkersFromStorage(raw) {
  const next = parseAudioMarkers(raw);
  for (const marker of audioMarkerRemoves) next.delete(marker);
  for (const marker of audioMarkerAdds) next.add(marker);
  audioMarkerBase = parseAudioMarkers(raw);
  audioCachedWords = next;
  updateOfflineStatus();
}
let audioCacheEpoch = '';
let audioCacheRevision = -1;
let audioCacheQuerySeq = 0;
const pendingAudioCacheQueries = new Map();
function acceptAudioCacheRevision(epoch, revision) {
  const nextEpoch = String(epoch || '');
  const nextRevision = Number(revision);
  if (nextEpoch && nextEpoch !== audioCacheEpoch) {
    audioCacheEpoch = nextEpoch;
    audioCacheRevision = -1;
  }
  if (!Number.isFinite(nextRevision)) return true;
  if (nextRevision < audioCacheRevision) return false;
  audioCacheRevision = nextRevision;
  return true;
}
function replaceAudioMarkerSet(next) {
  audioMarkerBase = new Set(next);
  audioCachedWords = new Set(next);
  audioMarkerAdds.clear();
  audioMarkerRemoves.clear();
  flushAudioMarkers();
}
function applyAudioCacheSnapshot(message) {
  if (!message || message.complete === false || !acceptAudioCacheRevision(message.epoch, message.revision)) return false;
  const next = new Set();
  for (const marker of Array.isArray(message.markers) ? message.markers : []) {
    const normalized = normalizeAudioMarker(marker);
    if (normalized && normalized !== 'en:') next.add(normalized);
  }
  const changed = next.size !== audioCachedWords.size || [...next].some(marker => !audioCachedWords.has(marker));
  if (changed) replaceAudioMarkerSet(next);
  const done = readAutoOfflineDone();
  if (done && next.size < done.expected) clearAutoOfflineDone();
  updateOfflineStatus();
  return true;
}
function queryAudioCacheSnapshot(timeoutMs) {
  const controller = navigator.serviceWorker && navigator.serviceWorker.controller;
  if (!controller) return Promise.reject(new Error('Service Worker 尚未接管页面'));
  audioCacheQuerySeq += 1;
  const requestId = 'audio-' + Date.now().toString(36) + '-' + audioCacheQuerySeq;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pendingAudioCacheQueries.delete(requestId);
      reject(new Error('音频缓存查询超时'));
    }, timeoutMs || 5000);
    pendingAudioCacheQueries.set(requestId, { resolve, reject, timer });
    controller.postMessage({ type: 'ky:audio-cache-query', protocol: 1, requestId, includeEntries: false });
  });
}
async function reconcileAudioCache() {
  if (!('caches' in window)) return audioCachedWords;
  // 优先向 SW 查询权威快照，避免每次启动都在页面主线程枚举最多 8000 个 Cache key。
  if (navigator.serviceWorker && navigator.serviceWorker.controller) {
    try {
      const snapshot = await queryAudioCacheSnapshot(5000);
      if (applyAudioCacheSnapshot(snapshot)) return audioCachedWords;
    } catch {}
  }
  try {
    const cache = await caches.open(AUDIO_CACHE_NAME);
    const keys = await cache.keys();
    const actual = new Set();
    for (const request of keys) {
      try {
        const url = new URL(request.url);
        const word = url.searchParams.get('word');
        if (!word) continue;
        actual.add(audioMarkerKey(word, url.searchParams.get('lang') === 'zh' ? 'zh' : 'en'));
      } catch {}
    }
    const changed = actual.size !== audioCachedWords.size || [...actual].some(marker => !audioCachedWords.has(marker));
    if (changed) replaceAudioMarkerSet(actual);
    else updateOfflineStatus();
    const done = readAutoOfflineDone();
    if (done && actual.size < done.expected) clearAutoOfflineDone();
    return actual;
  } catch {
    return audioCachedWords;
  }
}

window.addEventListener('storage', event => {
  if (event.key !== AUDIO_WORDS_KEY) return;
  replaceAudioMarkersFromStorage(event.newValue || '[]');
});

function rememberAudio(word, lang) {
  const marker = normalizeAudioMarker(String(word || '').includes(':') ? word : audioMarkerKey(word, lang || 'en'));
  if (!marker || marker === 'en:' || audioCachedWords.has(marker)) return;
  audioCachedWords.add(marker);
  audioMarkerRemoves.delete(marker);
  audioMarkerAdds.add(marker);
  if (!audioMarkerFlushTimer) audioMarkerFlushTimer = setTimeout(flushAudioMarkers, 1200);
}
function forgetAudio(marker) {
  const key = normalizeAudioMarker(marker);
  if (!key || key === 'en:') return false;
  const existed = audioCachedWords.delete(key);
  audioMarkerAdds.delete(key);
  audioMarkerRemoves.add(key);
  if (!audioMarkerFlushTimer) audioMarkerFlushTimer = setTimeout(flushAudioMarkers, 1200);
  return existed;
}
// 英文走有道词典发音（浏览器直连也行）；中文释义走百度 TTS，必须经自家 worker 转一手。
const AUDIO_PROXY_READY = location.protocol !== 'file:';
function audioUrl(text, lang) {
  if (lang === 'zh') return '/api/audio?lang=zh&word=' + encodeURIComponent(text);
  return 'https://dict.youdao.com/dictvoice?audio=' + encodeURIComponent(text) + '&type=2';
}
function cachedAudioUrl(text, lang) {
  // v 是内容版本而不是缓存键噪声；SW 与 Worker 都会规范化掉它。
  return '/api/audio?' + (lang === 'zh' ? 'lang=zh&v=2&' : '') + 'word=' + encodeURIComponent(text);
}
function playSrcFor(text, lang) {
  if (lang === 'zh') return cachedAudioUrl(text, 'zh');
  if (AUDIO_PROXY_READY && audioCachedWords.has(audioMarkerKey(text, 'en'))) return cachedAudioUrl(text, 'en');
  return audioUrl(text, 'en');
}
function offlineAudioUrl(text, lang) {
  return cachedAudioUrl(text, lang);
}
function refreshVoice() {
  try {
    const synth = window.speechSynthesis;
    if (!synth) return;
    const voices = synth.getVoices() || [];
    if (!voices.length) return;
    const us = voices.filter(v => /en[-_]US/i.test(v.lang));
    const anyEn = voices.filter(v => /^en/i.test(v.lang));
    const pick = (list) => list.find(v => !/online|natural|network/i.test(v.name + ' ' + v.voiceURI))
                    || list[0];
    speakVoice = pick(us) || pick(anyEn) || null;
    // 中文优先普通话、优先本地引擎（离线也能读），在线合成放最后
    const zh = voices.filter(v => /^zh|^cmn/i.test(v.lang));
    zhVoice = zh.find(v => /zh[-_]CN|^cmn/i.test(v.lang) && v.localService)
           || zh.find(v => v.localService)
           || zh.find(v => /zh[-_]CN|^cmn/i.test(v.lang))
           || zh[0] || null;
    voiceReady = true;
  } catch (e) {}
}
function speechFail(msg) {
  if (speakBroken) return;
  speakBroken = true;
  const el = $('speakWarn');
  if (el) {
    el.textContent = '发音不可用：' + msg + '。请检查网络或系统媒体音量，也可换用系统浏览器打开。';
    el.classList.remove('hidden');
  }
}
if (window.speechSynthesis) {
  refreshVoice();
  window.speechSynthesis.onvoiceschanged = refreshVoice;
}
// 浏览器要求先有用户手势。不要提前 speak 预热，否则某些引擎会进入静默失败状态。
let userGestured = false;
const markGesture = () => {
  userGestured = true;
  if (window.speechSynthesis && !voiceReady) refreshVoice();
  // 首次手势之前不允许预加载音频，手势到了立刻把整章补上
  chapterPrefetchKey = '';
  prefetchChapterAudio();
};
document.addEventListener('touchstart', markGesture, { once: true, passive: true });
document.addEventListener('mousedown', markGesture, { once: true });
document.addEventListener('keydown', markGesture, { once: true });
function systemSpeak(text, token, notify, reason, lang) {
  if (token !== speechToken) return false;
  const synth = window.speechSynthesis;
  if (!synth || typeof SpeechSynthesisUtterance === 'undefined') {
    if (notify) speechFail(reason || '浏览器不支持语音合成');
    return false;
  }
  const isZh = lang === 'zh-CN';
  if (!voiceReady || (isZh && !zhVoice)) refreshVoice();
  // 没有中文音色时硬提交只会让引擎拿英文声线乱念，或者干脆不出声，不如直接报错
  if (isZh && !zhVoice) {
    if (notify) speechFail(reason || '系统没有可用的中文语音');
    return false;
  }
  const hadSpeech = !!(synth.speaking || synth.pending);
  if (hadSpeech) {
    try { synth.cancel(); } catch {}
  }
  // 安卓上语音引擎被系统挂起后会静默排队，只 cancel 不 resume 就一直不出声
  if (synth.paused) { try { synth.resume(); } catch {} }
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang || 'en-US';
  u.rate = isZh ? 1.1 : 0.95;
  u.pitch = 1;
  u.volume = 1;
  if (isZh) { if (zhVoice) u.voice = zhVoice; }
  else if (speakVoice) u.voice = speakVoice;
  u.onstart = () => {
    if (token !== speechToken) return;
    speakBroken = false;
  };
  u.onerror = event => {
    const err = event && event.error;
    if (!err || err === 'interrupted' || err === 'canceled' || err === 'not-allowed') return;
    if (notify) speechFail(err);
  };
  const submit = () => {
    if (token !== speechToken) return;
    try { synth.speak(u); } catch (err) { if (notify) speechFail(err.message || String(err)); }
  };
  // 当前没有系统语音时同步提交，避免每次人为等待；只有取消旧语音后才让出 30ms。
  if (hadSpeech) setTimeout(submit, 30); else submit();
  return true;
}
function trimAudioPlayers() {
  for (const [word, player] of audioPlayers) {
    if (audioPlayers.size <= AUDIO_PLAYER_LIMIT) break;
    if (player === activePronunciationAudio) continue;
    audioPlayers.delete(word);
    try {
      player.pause();
      player.removeAttribute('src');
      player.load();
    } catch {}
  }
}
function preloadAudioWord(word, lang) {
  if (!word || navigator.onLine === false) return null;
  if (lang === 'zh' && !AUDIO_PROXY_READY) return null;
  const playerKey = audioMarkerKey(word, lang);
  let player = audioPlayers.get(playerKey);
  if (!player) {
    player = new Audio();
    player.preload = 'auto';
    player.setAttribute('playsinline', '');
    player.src = playSrcFor(word, lang);
    audioPlayers.set(playerKey, player);
    trimAudioPlayers();
    try { player.load(); } catch {}
  }
  return player;
}
function trimAudioBlobs() {
  for (const [word, url] of audioBlobUrls) {
    if (audioBlobUrls.size <= AUDIO_BLOB_LIMIT) break;
    audioBlobUrls.delete(word);
    try { URL.revokeObjectURL(url); } catch {}
  }
}
function cachePronunciationForOffline(text, lang) {
  if (!text || navigator.onLine === false || location.protocol === 'file:') return;
  const marker = audioMarkerKey(text, lang);
  if (audioCachedWords.has(marker) || audioFetching.has(marker)) return;
  audioFetching.add(marker);
  fetch(offlineAudioUrl(text, lang) + '&offline=1').then(response => {
    if (!audioCacheConfirmed(response)) throw new Error('audio cache not confirmed');
    return response.blob();
  }).then(blob => {
    if (!blob.size || !/^audio\//i.test(blob.type || '')) throw new Error('invalid audio');
    const old = audioBlobUrls.get(marker);
    if (old) { try { URL.revokeObjectURL(old); } catch {} }
    audioBlobUrls.set(marker, URL.createObjectURL(blob));
    trimAudioBlobs();
    rememberAudio(marker);
  }).catch(() => {}).finally(() => audioFetching.delete(marker));
}
function audioKeyOf(item) {
  return conf.speakLang === 'zh' ? meaningForSpeech(item) : (item && item.word);
}
// 真人音频提前加载到内存；离线副本单独延后缓存，避免抢占首次发声的带宽。
function prefetchAudioNearby() {
  if (!userGestured || navigator.onLine === false || !queue.length) return;
  const lang = conf.speakLang === 'zh' ? 'zh' : 'en';
  const keys = queue.slice(idx, idx + AUDIO_PRELOAD_AHEAD + 1).map(audioKeyOf).filter(Boolean);
  for (const key of keys) preloadAudioWord(key, lang);
  if (location.protocol === 'file:' || offlineCacheTimer) return;
  offlineCacheTimer = setTimeout(() => {
    offlineCacheTimer = null;
    if (navigator.onLine === false) return;
    const cacheKeys = queue.slice(idx, idx + 3).map(audioKeyOf).filter(Boolean);
    for (const key of cacheKeys) cachePronunciationForOffline(key, lang);
  }, 900);
}
// 整章预热：用户在一章里随便拖、随便翻，音频都已经在内存里，出声零等待。
// 分批加载，别一次甩几百个请求出去把主线程和网络都堵住。
let chapterPrefetchKey = '';
let chapterPrefetchTimer = null;
function prefetchChapterAudio() {
  if (!userGestured || navigator.onLine === false || !queue.length) return;
  const lang = conf.speakLang === 'zh' ? 'zh' : 'en';
  // 只预热当前词前后的小窗口。整章下载交给显式“下载全部”，避免每章
  // 一次生成 200 个 Audio 对象并抢占移动网络。
  const start = Math.max(0, idx - 2);
  const end = Math.min(queue.length, idx + AUDIO_PRELOAD_AHEAD + 1);
  const key = activeDeck + ':' + curChapter + ':' + lang + ':' + idx + ':' + start + ':' + end;
  if (chapterPrefetchKey === key) return;
  chapterPrefetchKey = key;
  if (chapterPrefetchTimer) { clearTimeout(chapterPrefetchTimer); chapterPrefetchTimer = null; }
  for (let i = start; i < end; i += 1) {
    const k = audioKeyOf(queue[i]);
    if (k) preloadAudioWord(k, lang);
  }
}
function getPronunciationAudio() {
  if (!pronunciationAudio) {
    pronunciationAudio = new Audio();
    pronunciationAudio.preload = 'auto';
    pronunciationAudio.setAttribute('playsinline', '');
  }
  return pronunciationAudio;
}
function playAudioElement(player, word, token, notify, options, source, lang) {
  if (!player || token !== speechToken) return false;
  let settled = false;
  const useSystem = reason => {
    if (settled || token !== speechToken) return;
    settled = true;
    clearTimeout(audioFallbackTimer);
    try { player.pause(); } catch {}
    if (activePronunciationAudio === player) activePronunciationAudio = null;
    const ok = systemSpeak(word, token, notify, reason, lang);
    if (options && options.onStatus) options.onStatus(ok ? 'system' : 'failed');
    if (!ok && notify) speechFail(reason || '在线发音和系统语音都不可用');
  };
  player.onplaying = () => {
    if (settled || token !== speechToken) return;
    settled = true;
    clearTimeout(audioFallbackTimer);
    speakBroken = false;
    cachePronunciationForOffline(word, lang === 'zh-CN' ? 'zh' : 'en');
    prefetchAudioNearby();
    if (options && options.onStatus) options.onStatus('online');
  };
  player.onended = () => {
    if (activePronunciationAudio === player) activePronunciationAudio = null;
  };
  player.onerror = () => useSystem('在线发音加载失败');
  try {
    if (window.speechSynthesis && (window.speechSynthesis.speaking || window.speechSynthesis.pending)) {
      window.speechSynthesis.cancel();
    }
  } catch {}
  activePronunciationAudio = player;
  try {
    player.currentTime = 0;
    const playing = player.play();
    if (playing && typeof playing.catch === 'function') playing.catch(() => useSystem('浏览器阻止了在线发音'));
    audioFallbackTimer = setTimeout(() => useSystem('在线发音启动超时'), 900);
    return true;
  } catch (e) {
    useSystem(e.message || String(e));
    return true;
  }
}
// 释义里常有括号注释和分号，念出来会很啰嗦，先清一遍
function meaningForSpeech(item) {
  const meaning = (item && typeof item === 'object') ? String(item.meaning || '') : '';
  return meaning
    .replace(/[（(][^）)]*[）)]/g, ' ')
    .replace(/[；;]/g, '，')
    .replace(/\s+/g, ' ')
    .trim();
}
function speak(item, options) {
  const notify = !!(options && options.notify);
  const word = typeof item === 'string' ? item : (item && item.word);
  if (!word) return false;
  if (!userGestured) return false;
  // 中英两条链路只差音源：中文用释义文本走百度 TTS，英文用单词走有道
  const isZh = conf.speakLang === 'zh';
  const key = isZh ? meaningForSpeech(item) : word;
  const lang = isZh ? 'zh-CN' : 'en-US';
  const tag = isZh ? 'zh' : 'en';
  // 中文音频必须经 worker 代理；单文件版没有代理，只能靠系统语音
  const canAudio = !isZh || AUDIO_PROXY_READY;
  if (!key) {
    if (notify) speechFail('这个词还没有中文释义');
    return false;
  }
  const token = ++speechToken;
  clearTimeout(audioFallbackTimer);
  if (activePronunciationAudio) {
    try { activePronunciationAudio.pause(); } catch {}
    activePronunciationAudio = null;
  }
  if (canAudio) {
    const direct = audioPlayers.get(audioMarkerKey(key, tag));
    if (direct && direct.readyState >= 2 && !direct.error) {
      return playAudioElement(direct, key, token, notify, options, 'direct', lang);
    }
    const blobUrl = audioBlobUrls.get(audioMarkerKey(key, tag));
    if (blobUrl) {
      const player = getPronunciationAudio();
      player.src = blobUrl;
      return playAudioElement(player, key, token, notify, options, 'blob', lang);
    }
    // 缓存过的词（含全量下载的）在线也直接用本地，别绕网络去等系统语音
    if (audioCachedWords.has(audioMarkerKey(key, tag))) {
      const player = getPronunciationAudio();
      player.src = playSrcFor(key, tag);
      return playAudioElement(player, key, token, notify, options, 'cached', lang);
    }
  }
  // 新词不等待网络：音频还没到手就先让系统语音出声，真人音频在后台准备，下一轮秒播
  prefetchAudioNearby();
  if (canAudio) cachePronunciationForOffline(key, tag);
  const ok = systemSpeak(key, token, notify, isZh ? '系统没有可用的中文语音' : '在线真人音频尚未就绪', lang);
  if (options && options.onStatus) options.onStatus(ok ? 'system' : 'failed');
  if (!ok && notify) speechFail(isZh ? '系统语音不可用' : '系统语音也不可用');
  return ok;
}
function toggleMeaning() {
  if (studyLoading) return;
  const cur = revealed === null ? !!conf.showByDefault : revealed;
  revealed = !cur;
  renderStudy();
}
// 左滑 = 认识：标记掌握，之后不再出现
// 右滑 = 不认识：权重 +1，下次重排越靠前
// 已认识库：左滑降权重
function lowerWeight(word) {
  if (!word) return;
  const before = state[word.word] && !state[word.word].del ? { ...state[word.word] } : undefined;
  const st = state[word.word];
  if (!st || st.del || !st.w) return;
  st.w = Math.max(0, st.w - 1);
  st.t = Date.now();
  if (!saveStateRecord(word.word)) {
    if (before === undefined) delete state[word.word]; else state[word.word] = before;
    showSessionNotice('保存失败：浏览器存储空间不足，请先导出备份。', 8000);
    return;
  }
  bumpDaily(false, false);
  if (navigator.vibrate) navigator.vibrate(18);
  renderStudy();
}
// 已认识库：右滑恢复，放回原词库
function restoreMastered(word) {
  if (!word) return;
  const at = idx;
  const before = state[word.word] && !state[word.word].del ? { ...state[word.word] } : undefined;   // 恢复后队列少一个，停在原位就是原来的下一个词
  if (state[word.word]) {
    const st = liveEntry(word.word);
    st.mastered = false; st.due = 0; st.t = Date.now();
    if (!save(LS_STATE, state)) {
      if (before === undefined) delete state[word.word]; else state[word.word] = before;
      showSessionNotice('保存失败：浏览器存储空间不足，请先导出备份。', 8000);
      return;
    }
    bumpDaily(false, false);
  }
  // 重建当前章队列：deckWords() 会因掌握数变化而重算切片，
  // 只改 queue 会导致切片与队列不一致、恢复的词本轮永远轮不到
  // 不能用 posWord 定位——刚恢复的词已不在队列里，找不到就会跳回第一个
  loadChapter(curChapter, undefined, at);
  savePos();
  updateStats();
  showUndo(word, 'restored', { s: 1, m: 0 }, before, at);
}
// 左滑/左键、右滑/右键统一走这里，滑动和键盘不再各有一套语义
function applyWordAction(word, dir) {
  if (!word) return;
  if (activeDeck === 'mastered') {
    if (dir === 'left') lowerWeight(word);
    else restoreMastered(word);
  } else {
    mark(word, dir === 'left');
  }
}
function mark(word, known) {
  if (!word) return;
  const before = state[word.word] && !state[word.word].del ? { ...state[word.word] } : undefined;
  const actionPos = idx;
  const st = liveEntry(word.word);
  const wasMastered = !!st.mastered;
  st.t = Date.now();
  st.seen = (st.seen || 0) + 1;
  if (known) { st.mastered = true; st.due = todayTs() + 7 * DAY; }
  else { st.w = (st.w || 0) + 1; st.mastered = false; st.due = 0; }
  state[word.word] = st;
  if (!saveStateRecord(word.word)) {
    if (before === undefined) delete state[word.word]; else state[word.word] = before;
    showSessionNotice('保存失败：浏览器存储空间不足，请先导出备份。', 8000);
    return;
  }
  bumpDaily(known, known && !wasMastered);
  if (known) {
    showUndo(word, undefined, { s: 1, m: wasMastered ? 0 : 1 }, before, actionPos);
    // 移出当前队列：进度条总数同步减少，下一个词自动顶上原位
    queue = queue.filter(w => w.word !== word.word);
    if (idx >= queue.length) idx = Math.max(queue.length - 1, 0);
    revealed = null;
    savePos();
    renderStudy();
  } else {
    if (activeDeck === 'mastered') {                   // 已掌握库里取消掌握 -> 立即移出列表
      queue = queue.filter(w => w.word !== word.word);
      if (idx >= queue.length) idx = Math.max(queue.length - 1, 0);
      revealed = null;
      savePos();
      renderStudy();
    }
    if (navigator.vibrate) navigator.vibrate(22);
    // 实时反馈：当前词还在屏幕上，直接把权重亮出来并闪一下
    if (queue[idx] && queue[idx].word === word.word) {
      const wb = $('weightBadge');
      wb.textContent = String(st.w);
      wb.classList.remove('hidden');
      wb.classList.remove('pulse');
      void wb.offsetWidth;
      wb.classList.add('pulse');
      $('wordId').textContent = displayWeightOf(word).toFixed(2);
    }
  }
  updateStats();
}
function renderRhythm() {
  const streakEl = $('sStreak'), weekEl = $('sWeek'), todayEl = $('sToday');
  if (!streakEl || !weekEl || !todayEl) return;
  const todayRec = daily[dayKey(Date.now())] || {};
  streakEl.textContent = String(streakDays(daily));
  todayEl.textContent = todayRec.s
    ? '今天过了 ' + todayRec.s + ' 次卡' + (todayRec.m ? '，新掌握 ' + todayRec.m + ' 个' : '') + '。'
    : '今天还没开始背。';
  const days = [];
  for (let i = 6; i >= 0; i -= 1) days.push(todayTs() - i * DAY);
  let max = 0;
  for (const ts of days) max = Math.max(max, (daily[dayKey(ts)] || {}).s || 0);
  const WEEKDAY = '日一二三四五六';
  const frag = document.createDocumentFragment();
  days.forEach((ts, i) => {
    const rec = daily[dayKey(ts)] || {};
    const cell = document.createElement('div');
    cell.className = 'week-day' + (i === 6 ? ' today' : '');
    const num = document.createElement('b');
    num.textContent = String(rec.s || 0);
    const bar = document.createElement('i');
    const ratio = max ? (rec.s || 0) / max : 0;
    bar.style.setProperty('--h', Math.max(3, Math.round(ratio * 56)) + 'px');
    const lab = document.createElement('span');
    lab.textContent = i === 6 ? '今' : WEEKDAY[new Date(ts).getDay()];
    cell.append(num, bar, lab);
    frag.append(cell);
  });
  weekEl.replaceChildren(frag);
}
