
// 词库放进 JSON 数据块：浏览器不把它当脚本编译，切到哪个库才 JSON.parse 哪个。
const _deckCache = {};
function deckJson(id) {
  if (!(id in _deckCache)) {
    const el = document.getElementById('ky-deck-' + id);
    let rows = [];
    if (el) {
      try { rows = JSON.parse(el.textContent); }
      catch (err) { console.error('词库数据解析失败：' + id, err); }
    }
    _deckCache[id] = Array.isArray(rows) ? rows : [];
  }
  return _deckCache[id];
}
const DATA_META = (() => {
  const el = document.getElementById('ky-deck-meta');
  try { return el ? JSON.parse(el.textContent) : {}; }
  catch { return {}; }
})();
const WEB_MODE = !!(DATA_META && DATA_META.web);
const DECK_IDS = { core: 'words', derivative: 'derivatives', foundation: 'basic', insurance: 'insurance' };
const DECK_KEYS = ['core', 'derivative', 'foundation', 'insurance'];
const _deckReady = new Set(WEB_MODE ? [] : DECK_KEYS);
const _deckLoading = {};

function deckDataReady(deckKey) {
  if (!WEB_MODE) return true;
  if (deckKey === 'mastered') return DECK_KEYS.every(deckDataReady);
  const id = DECK_IDS[deckKey];
  return !!id && _deckReady.has(id);
}
function allDecksReady() {
  return !WEB_MODE || DECK_KEYS.every(deckDataReady);
}
function deckDataLength(deckKey) {
  const id = DECK_IDS[deckKey];
  if (!id) return 0;
  const size = DATA_META && DATA_META.deck_sizes && DATA_META.deck_sizes[id];
  return Math.max(deckJson(id).length, Number(size) || 0);
}
function deckCanShowChapter(deckKey, ch) {
  if (deckDataReady(deckKey)) return true;
  return WEB_MODE && deckKey === 'core' && ch === 0 && deckJson('words').length > 0;
}
function resetDeckCaches() {
  allWordsCache = null;
  wordLocationCache = null;
  masteredWordsCache = null;
}
function loadWebDeck(deckKey) {
  const id = DECK_IDS[deckKey];
  if (!id) return Promise.reject(new Error('unknown deck'));
  if (!WEB_MODE || _deckReady.has(id)) return Promise.resolve(deckJson(id));
  if (_deckLoading[deckKey]) return _deckLoading[deckKey];
  const url = DATA_META && DATA_META.assets && DATA_META.assets[id];
  if (!url) return Promise.reject(new Error('deck asset missing'));
  _deckLoading[deckKey] = fetch(url, { cache: 'force-cache' })
    .then(response => {
      if (!response.ok) throw new Error('deck load failed: ' + response.status);
      return response.json();
    })
    .then(rows => {
      if (!Array.isArray(rows) || !rows.length) throw new Error('deck data invalid');
      _deckCache[id] = rows;
      _deckReady.add(id);
      resetDeckCaches();
      return rows;
    })
    .finally(() => { delete _deckLoading[deckKey]; });
  return _deckLoading[deckKey];
}
async function ensureDeckData(deckKey) {
  if (deckKey === 'mastered') {
    await Promise.all(DECK_KEYS.map(loadWebDeck));
  } else {
    await loadWebDeck(deckKey);
  }
  updateDeckMeta();
  renderChapters();
  if (!$('viewStat').classList.contains('hidden')) updateStats();
  return deckWords();
}
