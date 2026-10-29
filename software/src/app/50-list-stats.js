let statsDirty = false;
let statsFrame = 0;
function updateStats() {
  if (!$('viewStat') || $('viewStat').classList.contains('hidden')) { statsDirty = true; return; }
  // 统计页可见时同步计算，避免测试或调用方紧接着读取 DOM 拿到旧值。
  updateStatsNow();
}
function updateStatsNow() {
  statsFrame = 0;
  if (!$('viewStat') || $('viewStat').classList.contains('hidden')) { statsDirty = true; return; }
  statsDirty = false;
  renderRhythm();
  if (WEB_MODE && !deckDataReady(activeDeck)) {
    const target = activeDeck;
    $('sTotal').textContent = target === 'mastered' ? '?' : deckDataLength(target);
    $('sLearned').textContent = '?';
    $('sMastered').textContent = '?';
    $('sDue').textContent = '?';
    if ($('sReview')) $('sReview').textContent = '?';
    if (!$('viewStat').classList.contains('hidden')) {
      ensureDeckData(target).then(() => {
        if (activeDeck === target && !$('viewStat').classList.contains('hidden')) updateStatsNow();
      }).catch(() => {
        if (activeDeck === target) {
  $('sTotal').textContent = '加载失败';
          $('sLearned').textContent = '?';
          $('sMastered').textContent = '?';
          $('sDue').textContent = '?';
        }
      });
    }
    return;
  }
  let learned = 0, mastered = 0, dueReview = 0;
  const words = deckWords();
  const total = activeDeck === 'mastered' ? words.length : deckDataLength(activeDeck);
  const now = Date.now();
  for (const word of words) {
    const st = state[word.word];
    if (!st || st.del) continue;
    learned += 1;
    if (st.mastered && (!st.due || st.due > now)) mastered += 1;
    if (st.mastered && st.due && st.due <= now) dueReview += 1;
  }
  $('sTotal').textContent = total;
  $('sLearned').textContent = learned;
  $('sMastered').textContent = mastered;
  $('sDue').textContent = Math.max(total - learned, 0);
  if ($('sReview')) $('sReview').textContent = dueReview;
}
const LIST_PAGE_SIZE = 100;
let listLimit = LIST_PAGE_SIZE;
let listKey = '';
let listRendered = 0;
let listMatches = [];
function renderList(reset) {
  if (reset) listLimit = LIST_PAGE_SIZE;
  const list = $('wordList');
  if (WEB_MODE && !deckDataReady(activeDeck)) {
    const target = activeDeck;
    const loading = document.createElement('li');
    loading.className = 'list-meaning';
    loading.textContent = '正在加载完整词库，加载一次后会长期缓存…';
    list.replaceChildren(loading);
    listRendered = 0;
    listKey = '';
    listMatches = [];
    ensureDeckData(target).then(() => {
      if (activeDeck === target && !$('viewList').classList.contains('hidden')) renderList(reset);
    }).catch(() => {
      if (activeDeck === target) {
        loading.textContent = '词库加载失败，请检查网络后重新进入词表。';
        list.replaceChildren(loading);
      }
    });
    return;
  }
  const q = searchText.trim().toLowerCase();
  const signature = activeDeck + '|' + priorityFilter + '|' + q + '|' + stateRevision;
  const matches = listQueryCache.key === signature
    ? listQueryCache.matches
    : (() => {
        const inMasteredDeck = activeDeck === 'mastered';
        const rows = [];
        for (const word of deckWords()) {
          const mastered = isMastered(word);
          if (!inMasteredDeck) {
            if (priorityFilter === 'mastered') {
              if (!mastered) continue;
            } else {
              if (mastered) continue;
              const p = (word.priority || 'C').charAt(0);
              if (priorityFilter !== 'all' && p !== priorityFilter) continue;
            }
          }
          if (q && !word.word.toLowerCase().includes(q) && !word.meaning.toLowerCase().includes(q) && !(word.forms || []).some(form => form.toLowerCase().includes(q)) && !(word.family || '').toLowerCase().includes(q)) continue;
          rows.push(word);
        }
        listQueryCache = { key: signature, matches: rows };
        return rows;
      })();
  const upto = Math.min(listLimit, matches.length);
  // 「显示更多」只追加新增的那一页：每次都重建全部已渲染条目是 O(n²)，
  // 连点十次就要重建上千个节点。签名和已渲染前缀都对得上才敢追加。
  const previousKey = listKey;
  const previousMatches = listMatches;
  // 「显示更多」只追加已渲染前缀之后的新页。签名变化或状态变化导致前缀不同，
  // 就整批重绘，绝不能把旧结果和新结果拼在一起。
  let canAppend = !reset && signature === previousKey && listRendered > 0
    && listRendered <= upto && listRendered <= previousMatches.length
    && previousMatches.slice(0, listRendered).every((w, i) => w === matches[i]);
  if (!canAppend) {
    list.replaceChildren();
    listRendered = 0;
  }
  const staleMore = list.querySelector('.list-more');
  if (staleMore) staleMore.remove();
  const fragment = document.createDocumentFragment();
  const from = canAppend ? listRendered : 0;
  for (const word of matches.slice(from, upto)) {
    const mastered = isMastered(word);
    const li = document.createElement('li');
    const no = document.createElement('span'); no.className = 'list-no'; no.textContent = '#' + word.id;
    const main = document.createElement('div');
    const w = document.createElement('div'); w.className = 'list-word'; w.lang = 'en'; w.textContent = word.word;
    const m = document.createElement('div'); m.className = 'list-meaning'; m.textContent = word.meaning;
    main.append(w, m);
    if (word.family) {
      const fm = document.createElement('div'); fm.className = 'list-meaning'; fm.textContent = '词族：' + word.family;
      main.append(fm);
    }
    if (word.forms && word.forms.length) {
      const f = document.createElement('div'); f.className = 'list-meaning'; f.textContent = word.forms.join(' / ');
      main.append(f);
    }
    let badge;
    if (mastered) {
      const owner = deckOfWord(word.word);
      badge = document.createElement('button');
      badge.className = 'restore-btn';
      badge.textContent = '恢复';
      badge.title = owner ? (DECKS[owner].label + ' 第' + (Math.floor(ownerIndex(owner, word.word) / CHAPTER_SIZE) + 1) + '章') : '';
      badge.onclick = () => {
        if (state[word.word]) {
          const st = liveEntry(word.word);
          st.mastered = false; st.due = 0; st.t = Date.now();
          saveStateRecord(word.word);
        }
        if (owner) {
          const ch = Math.floor(ownerIndex(owner, word.word) / CHAPTER_SIZE);
          const ck = owner + ':' + ch;
          if (chapterData[ck]) chapterData[ck].done = false;   // 清掉「已过完」，恢复的词才会出现
          switchDeck(owner);
          // gotoChapter 会同时写回 conf.deckChapter，否则刷新后又跳回上次的章节
          gotoChapter(ch);
        } else {
          renderList(); updateStats(); gotoChapter(curChapter);
        }
      };
    } else {
      badge = document.createElement('span');
      badge.className = 'list-priority priority ' + priorityClass(word.priority);
      badge.textContent = priorityLevel(word.priority);
      badge.title = PRIORITY_LABELS[priorityLevel(word.priority)];
    }
    li.append(no, main, badge);
    fragment.append(li);
  }
  list.append(fragment);
  listRendered = upto;
  listKey = signature;
  listMatches = matches;
  if (matches.length > listLimit) {
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'list-more';
    more.textContent = '显示更多（还剩 ' + (matches.length - listLimit) + ' 个）';
    more.onclick = () => { listLimit += LIST_PAGE_SIZE; renderList(false); };
    list.append(more);
  }
}
