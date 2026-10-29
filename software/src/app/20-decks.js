const DECKS = {
  core: { label: '阶段一 · 核心词', note: '阶段一 · 核心词：先背完这一套，再进入核心派生。', get words() { return deckJson('words'); } },
  derivative: { label: '阶段二 · 核心派生', note: '阶段二 · 核心派生：只收词族中高频、词性或语义有明显变化的成员。', get words() { return deckJson('derivatives'); } },
  foundation: { label: '基础词自测', note: '基础词自测：专门检查你以为会、实际可能不会的熟词。', get words() { return deckJson('basic'); } },
  insurance: { label: '高/中频保险库', note: '高/中频保险库：收入闪过中未进主线的词，只用于补漏，不建议一开始通背。', get words() { return deckJson('insurance'); } },
  mastered: { label: '已认识', note: '左滑认识的词都收进这里，不会被删除。去「词表」页点「恢复」可以放回原词库。', words: [] }
};
let activeDeck = Object.prototype.hasOwnProperty.call(DECKS, conf.deck) ? conf.deck : 'core';
// 全量词表只在「已认识库」和跨库搜索时才会被真正解析。
let allWordsCache = null;
const allWords = () => {
  if (WEB_MODE && !allDecksReady()) return [];
  if (!allWordsCache) {
    const seen = new Set(), list = [];
    for (const w of [...deckJson('words'), ...deckJson('derivatives'), ...deckJson('basic'), ...deckJson('insurance')]) {
      if (!seen.has(w.word)) { seen.add(w.word); list.push(w); }
    }
    allWordsCache = list;
  }
  return allWordsCache;
};
let wordLocationCache = null;
const wordLocation = () => {
  if (!wordLocationCache) {
    wordLocationCache = new Map();
    for (const key of ['core', 'derivative', 'foundation', 'insurance']) {
      DECKS[key].words.forEach((word, index) => wordLocationCache.set(word.word, { deck: key, index }));
    }
  }
  return wordLocationCache;
};
const deckWords = () => {
  if (activeDeck !== 'mastered') return DECKS[activeDeck].words;
  if (!masteredWordsCache) masteredWordsCache = allWords().filter(w => isMastered(w));
  return masteredWordsCache;
};
let queue = [];
let idx = 0;
let revealed = null;   // null=跟随「默认显示」设置；true/false=当前词手动覆盖
let dragging = false;
let chapterData = loadChapterStoreWithPositions(load('ky_chapter_v1', {}));
let curChapter = 0;
let priorityFilter = 'all';
let searchText = '';

