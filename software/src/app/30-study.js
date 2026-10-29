// 等级只用单个字母上卡片，中文全称放 title 和详情里
const PRIORITY_LABELS = { S: 'S 必背', A: 'A 重点', B: 'B 次重点', C: 'C 补充' };
function priorityLevel(priority) {
  const p = String(priority || 'C').trim().charAt(0).toUpperCase();
  return PRIORITY_LABELS[p] ? p : 'C';
}
function priorityClass(priority) {
  return priorityLevel(priority).toLowerCase();
}
function setPriority(el, priority) {
  const level = priorityLevel(priority);
  el.className = 'priority ' + level.toLowerCase();
  el.textContent = level;
  el.title = PRIORITY_LABELS[level];
}
function isMastered(word) {
  const st = state[word.word];
  return !!(st && st.mastered);
}
function weightOf(word) {
  const st = state[word.word];
  return st ? (st.w || 0) : 0;
}
// 墓碑（{ del: 1, t }）不是有效记录。要往这个词写进度时先换成干净的新记录，
// 否则删除标记会跟着新数据一起上传，合并时又被判成「已删除」，词就永远存不住。
function liveEntry(name) {
  const cur = state[name];
  if (cur && !cur.del) return cur;
  const fresh = { w: 0, mastered: false, seen: 0 };
  state[name] = fresh;
  return fresh;
}
// 词表自带的优先度权重（S 最高）
const TIER_SCORE = { S: 3, A: 2, B: 1, C: 0 };
function tierOf(word) {
  const p = String(word.priority || 'C').trim().charAt(0).toUpperCase();
  return TIER_SCORE[p] || 0;
}
// 词表内唯一的 0–100 基础权重 + 用户错题修正
function scoreOf(word) {
  return tierOf(word) + weightOf(word);
}
function displayWeightOf(word) {
  const base = Number(word && word.weight);
  const fallback = tierOf(word);
  return Math.round(((Number.isFinite(base) ? base : fallback) + weightOf(word) * 0.1) * 100) / 100;
}
// 原序：完全按词表顺序，每次打开都一样
function naturalOrder(list) {
  return list.slice().sort((a, b) => a.id - b.id);
}
// 加权洗牌：只影响「靠前的概率」，权重高更可能排在前面，但不强制置顶
function shuffleByWeight(list) {
  const arr = list.map(word => ({
    word,
    key: Math.pow(Math.random(), 1 / (1 + scoreOf(word) * 0.6))
  }));
  arr.sort((a, b) => b.key - a.key);
  return arr.map(x => x.word);
}
function chapterSlice(ch) {
  const start = ch * CHAPTER_SIZE;
  return deckWords().slice(start, start + CHAPTER_SIZE);
}
function chapterKey(ch) { return activeDeck + ':' + ch; }
function savePos(touchProgress) {
  const now = Date.now();
  // 词书 / 章节 / 章内位次三件事必须同时落盘：
  // 恢复时读的是 deckChapter[activeDeck]，只写 conf.chapter 会让刷新后跳回旧章。
  conf.deck = activeDeck;
  conf.chapter = curChapter;
  conf.deckChapter = conf.deckChapter || {};
  conf.deckChapter[activeDeck] = curChapter;
  if (touchProgress !== false) conf.progressAt = now;
  const key = chapterKey(curChapter);
  const rec = chapterData[key];
  if (rec) {
    rec.pos = idx;
    rec.posWord = idx < queue.length ? queue[idx].word : null;
    if (touchProgress !== false) rec.t = now;
    save(LS_POS, positionStoreFromChapters(chapterData));
  }
  save(LS_CONF, conf);
}
// 恢复位置时唯一入口：先看该词书记住的章，再退回 conf.chapter
function resumePosition() {
  const byDeck = conf.deckChapter || {};
  const ch = byDeck[activeDeck];
  return Number.isInteger(ch) ? ch : (Number(conf.chapter) || 0);
}
let pendingSeek = null;   // 词库还没补齐时拖到的位次，补齐后再跳过去
let fillDeckPending = null;
// 内嵌词库只够铺首屏，整本要在后台补齐。补完按「当前停留的那个词」重建队列，
// 不能按位次：补齐后整章的排序来源从几十个词变成上千个，位次已经完全对不上。
function fillDeckInBackground(deckKey, attempt) {
  if (deckKey === 'mastered' || deckDataReady(deckKey) || fillDeckPending) return;
  fillDeckPending = deckKey;
  // 整本词库两百多 KB，等页面 load 完再拉：否则它会计入浏览器标签上的加载进度，
  // 首屏明明已经能用了，进度条却一直转。
  const begin = () => setTimeout(() => {
    const targetDeck = deckKey;
    ensureDeckData(deckKey).then(() => {
      fillDeckPending = null;
      if (activeDeck !== targetDeck) { pendingSeek = null; return; }
      const seek = pendingSeek;
      pendingSeek = null;
      // 目标位次要连章带书一起核对：补全期间用户可能已经跳了章，
      // 拿旧章的目标位次套到新章会直接落到错词上
      if (seek && seek.deck === activeDeck && seek.ch === curChapter) {
        loadChapter(curChapter, undefined, seek.idx, seek.word, 'background', true);
      } else {
        loadChapter(curChapter, undefined, undefined, queue[idx] ? queue[idx].word : null, 'background', true);
      }
    }).catch(() => {
      fillDeckPending = null;
      // 一次失败就永久停在 40 张最糟：重试一次，再失败才放弃，等下次进章节重新拉
      if (!attempt) fillDeckInBackground(deckKey, 1);
      else {
        pendingSeek = null;
        if (queue.length) { idx = Math.min(idx, queue.length - 1); renderStudy(); showSessionNotice('完整词库加载失败，继续使用已加载内容。', 8000); }
        else showStudyLoadError();
      }
    });
  }, 300);
  if (document.readyState === 'complete') begin();
  else window.addEventListener('load', begin, { once: true });
}
let studyLoading = false;
function showStudyLoading(message) {
  studyLoading = true;
  $('position').textContent = '正在加载词库…';
  $('swipeStage').classList.remove('hidden');
  $('card').classList.remove('hidden');
  $('done').classList.add('hidden');
  document.querySelector('.nav-row').classList.add('hidden');
  $('word').textContent = '加载中…';
  $('familyNote').classList.add('hidden');
  $('forms').textContent = '';
  $('formsBox').classList.add('hidden');
  $('meaning').className = 'meaning';
  $('meaning').textContent = message || '正在加载当前章节…';
  $('wordId').textContent = '';
  $('prevWord').disabled = true;
  $('nextWord').disabled = true;
}
function showStudyLoadError() {
  showStudyLoading('词库加载失败，请检查网络后刷新页面重试。');
  $('word').textContent = '加载失败';
}
function loadChapter(ch, mode, idxAt, atWord, persistPosition, preserveUndo) {   // mode: 'shuffle' 打乱 / 'natural' 原序 / 省略=沿用上次
  const targetDeck = activeDeck;
  if (!deckCanShowChapter(targetDeck, ch)) {
    showStudyLoading('正在加载这一部分词库，首次加载后会长期缓存。');
    ensureDeckData(targetDeck).then(() => {
      if (activeDeck === targetDeck) loadChapter(ch, mode, idxAt, atWord, persistPosition, preserveUndo);
    }).catch(() => showStudyLoadError());
    return;
  }
  // 网页版首屏只内嵌了几十个词，够立刻背起来；整本词库必须在这之后补齐，
  // 否则这一章永远只有内嵌的那几十个词（进度条总数卡住、后面的词轮不到）。
  if (WEB_MODE && !deckDataReady(targetDeck)) fillDeckInBackground(targetDeck);
  studyLoading = false;
  // 章节数会随「已认识」库的恢复/新增变化，记住的章号可能已经越界，先夹到有效范围
  ch = Math.min(Math.max(ch, 0), Math.max(chapterCount() - 1, 0));
  curChapter = ch;
  if (!preserveUndo) clearUndoBar();
  const key = chapterKey(ch);
  const now = Date.now();
  // 未掌握的照常出现；已掌握但到了 7 天复习期的，也重新出现
  // 「已认识」库里所有词本来就是已掌握，不能再过滤，否则一章 0 词
  const pending = activeDeck === 'mastered'
    ? chapterSlice(ch).slice()
    : chapterSlice(ch).filter(w => {
        if (!isMastered(w)) return true;
        const st = state[w.word];
        return !!(st && st.due && st.due <= now);
      });
  let rec = chapterData[key];
  if (mode === 'shuffle') {
    const now = Date.now();
    rec = chapterData[key] = { order: shuffleByWeight(pending).map(w => w.word), pos: 0, shuffled: true, t: now };
    conf.deck = activeDeck;
    conf.chapter = ch;
    conf.deckChapter = conf.deckChapter || {};
    conf.deckChapter[activeDeck] = ch;
    conf.progressAt = now;
    save('ky_chapter_v1', chapterData);
    save(LS_CONF, conf);
  } else if (mode === 'natural' || !rec || !Array.isArray(rec.order)) {
    const now = Date.now();
    rec = chapterData[key] = { order: naturalOrder(pending).map(w => w.word), pos: 0, t: now };
    if (mode === 'natural') {
      conf.deck = activeDeck;
      conf.chapter = ch;
      conf.deckChapter = conf.deckChapter || {};
      conf.deckChapter[activeDeck] = ch;
      conf.progressAt = now;
      save(LS_CONF, conf);
    }
    save('ky_chapter_v1', chapterData);
  }
  const byName = new Map(pending.map(w => [w.word, w]));
  const seen = new Set();
  const ordered = [];
  for (const name of rec.order) {
    if (byName.has(name) && !seen.has(name)) { ordered.push(byName.get(name)); seen.add(name); }
  }
  for (const w of pending) if (!seen.has(w.word)) ordered.push(w);
  queue = ordered;
  // 恢复优先级：显式词 > 显式位次 > 章节保存的词 > 章节保存的位次。
  const targetWord = atWord || (typeof idxAt !== 'number' && rec.posWord) || null;
  if (targetWord) {
    const j = queue.findIndex(w => w.word === targetWord);
    if (j >= 0) idx = j;
    else if (deckIncomplete()) {
      pendingSeek = { deck: activeDeck, ch, idx: typeof idxAt === 'number' ? idxAt : (Number(rec.pos) || 0), word: targetWord };
      showStudyLoading('正在恢复上次学习位置…');
      return;
    } else {
      const savedIdx = Number(rec.pos) || 0;
      idx = Math.min(Math.max(savedIdx, 0), Math.max(queue.length - 1, 0));
    }
  } else if (typeof idxAt === 'number' && queue.length) {
    idx = idxAt < 0 ? queue.length - 1 : Math.min(idxAt, queue.length - 1);
  } else if (rec.posWord) {
    const j = queue.findIndex(w => w.word === rec.posWord);
    idx = j >= 0 ? j : 0;
  } else {
    idx = Math.min(Math.max(rec.pos || 0, 0), Math.max(queue.length - 1, 0));
  }
  revealed = null;
  renderStudy();
  if (persistPosition) savePos(persistPosition !== 'background');
}
// 整章应有的词数（按整本词库算，不看当前是否已经解析完）。
// 网页版首屏只内嵌几十个词，直接拿队列长度当分母会露出「只有 40 个」。
function chapterExpectedLength(ch) {
  const all = deckKnownLength(activeDeck);
  return Math.max(0, Math.min(CHAPTER_SIZE, all - ch * CHAPTER_SIZE));
}
function deckIncomplete() {
  return WEB_MODE && !deckDataReady(activeDeck);
}
function renderStudy() {
  studyLoading = false;
  const total = queue.length;
  const current = total ? Math.min(idx + 1, total) : 0;
  // 词库还没补齐时，分母用整章应有的词数：队列只是内嵌的子集，补全后会长回整章
  const shownTotal = deckIncomplete() ? Math.max(chapterExpectedLength(curChapter), total) : total;
  $('position').innerHTML = `第 <b>${current}</b> / ${shownTotal} 个`;
  $('progressBar').max = String(Math.max(shownTotal, 1));
  if (!dragging) $('progressBar').value = String(Math.min(idx, total));
  if (!total || idx >= total) {
    $('swipeStage').classList.add('hidden');
    $('card').classList.add('hidden');
    document.querySelector('.nav-row').classList.add('hidden');
    $('done').classList.remove('hidden');
    if (activeDeck === 'mastered') {
      $('doneTitle').textContent = '这里是已认识的词';
      $('doneHint').textContent = '共 ' + deckWords().length + ' 个。去「词表」页点「恢复」可以放回原词库。';
      $('doneAction').textContent = '去看词表';
      $('doneAction').dataset.mode = 'list';
      return;
    }
    const left = chapterSlice(curChapter).filter(w => !isMastered(w)).length;
    $('doneTitle').textContent = left ? '本轮过完了' : '这一章全部掌握';
    $('doneHint').textContent = left
      ? '还剩 ' + left + ' 个没掌握，可以再过一轮。'
      : '可以打乱顺序重背一遍。';
    $('doneAction').textContent = left ? '再过一轮' : '打乱重背';
    $('doneAction').dataset.mode = left ? 'again' : 'reshuffle';
    return;
  }
  $('swipeStage').classList.remove('hidden');
  $('card').classList.remove('hidden');
  document.querySelector('.nav-row').classList.remove('hidden');
  $('done').classList.add('hidden');
  const word = queue[idx];
  $('word').textContent = word.word;
  $('word').lang = 'en';
  if (!window.__firstCardAt) window.__firstCardAt = Math.round(performance.now());
  // 词族母词和词形变化放同一行，用「/」分隔，不再单独标「词族：」
  const family = word.family || '';
  const forms = Array.isArray(word.forms) ? word.forms.filter(Boolean) : [];
  const line = (family ? [family] : []).concat(forms);
  $('familyNote').classList.add('hidden');
  $('forms').textContent = line.join(' / ');
  $('forms').lang = 'en';
  $('formsBox').classList.toggle('hidden', line.length === 0);
  setPriority($('priorityBadge'), word.priority);
  const wt = weightOf(word);
  const wb = $('weightBadge');
  wb.textContent = wt > 0 ? String(wt) : '';
  wb.classList.toggle('hidden', wt === 0);
  $('wordId').textContent = displayWeightOf(word).toFixed(2);
  const show = revealed === null ? !!conf.showByDefault : revealed;
  const meaning = $('meaning');
  if (show) {
    meaning.className = 'meaning';
    meaning.textContent = word.meaning || '（暂无释义）';
  } else {
    meaning.className = 'meaning meaning-placeholder';
    meaning.textContent = '点一下看释义';
  }
  $('meaningToggle').textContent = conf.showByDefault ? '释义开' : '释义关';
  $('meaningToggle').setAttribute('aria-pressed', String(!!conf.showByDefault));
  const langTag = conf.speakLang === 'zh' ? '中' : '英';
  $('speakToggle').textContent = conf.speak ? '朗读·' + langTag : '朗读关';
  $('speakToggle').setAttribute('aria-pressed', String(!!conf.speak));
  $('speakToggle').title = '轻点开/关朗读，长按切换中英文';
  if (conf.speak && !dragging && lastSpoken !== word.word && speak(word)) lastSpoken = word.word;
  const masteredDeck = activeDeck === 'mastered';
  const leftSwipeCard = $('swipeLeftCard');
  const rightSwipeCard = $('swipeRightCard');
  leftSwipeCard.classList.remove('good', 'bad', 'warn');
  rightSwipeCard.classList.remove('good', 'bad', 'warn');
  leftSwipeCard.classList.add(masteredDeck ? 'warn' : 'good');
  rightSwipeCard.classList.add(masteredDeck ? 'good' : 'bad');
  $('swipeLeftAction').textContent = masteredDeck ? '降权重' : '认识';
  $('swipeLeftDetail').textContent = masteredDeck ? '权重 -1' : '不再出现';
  $('swipeRightAction').textContent = masteredDeck ? '恢复' : '不认识';
  $('swipeRightDetail').textContent = masteredDeck ? '回原词库' : '权重 +1';
  leftSwipeCard.setAttribute('aria-label', masteredDeck ? '左滑：降权重' : '左滑：认识，不再出现');
  rightSwipeCard.setAttribute('aria-label', masteredDeck ? '右滑：恢复到原词库' : '右滑：不认识，权重加一');
  $('swipeHint').textContent = masteredDeck
    ? '左滑 = 降权重 · 右滑 = 恢复到原词库'
    : '左滑 = 认识（不再出现）· 右滑 = 不认识（权重+1）';
  $('chapterSelect').value = String(currentChapter());
  $('prevWord').disabled = idx <= 0 && curChapter <= 0;
  $('nextWord').disabled = idx >= total - 1 && curChapter >= chapterCount() - 1;
  prefetchChapterAudio();
}
function navigate(delta) {
  if (studyLoading) return;
  const next = idx + delta;
  // 到章节边界就翻到相邻章节：上一章停最后一词，下一章停第一词
  if (next < 0) { crossChapter(-1); return; }
  if (next >= queue.length) {
    if (deckIncomplete() && chapterExpectedLength(curChapter) > queue.length) {
      pendingSeek = { deck: activeDeck, ch: curChapter, idx: next };
      showStudyLoading('正在补全本章剩余词，请稍候…');
      fillDeckInBackground(activeDeck);
      return;
    }
    crossChapter(1); return;
  }
  idx = next;
  revealed = null;
  savePos();
  renderStudy();
}
function crossChapter(dir) {
  const target = curChapter + dir;
  if (target < 0 || target >= chapterCount()) return false;
  savePos();
  conf.chapter = target;
  conf.deckChapter = conf.deckChapter || {};
  conf.deckChapter[activeDeck] = target;
  save(LS_CONF, conf);
  loadChapter(target, undefined, dir < 0 ? -1 : 0, undefined, true, true);
  renderChapters();
  return true;
}
