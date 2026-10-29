function deckOfWord(name) {
  const found = wordLocation().get(name);
  return found ? found.deck : null;
}
function ownerIndex(deckKey, name) {
  const found = wordLocation().get(name);
  return found && found.deck === deckKey ? found.index : -1;
}

function deckKnownLength(deckKey) {
  return deckKey === 'mastered' ? deckWords().length : deckDataLength(deckKey);
}
function updateDeckMeta() {
  const total = deckKnownLength(activeDeck);
  $('deckSelect').value = activeDeck;
  $('deckMeta').textContent = total + ' 词';
}
async function switchDeck(value) {
  if (!Object.prototype.hasOwnProperty.call(DECKS, value)) return;
  const previous = activeDeck;
  // 先切当前词书，再保存旧章节位置：savePos() 内也不能把 activeDeck 写回旧值。
  activeDeck = value;
  conf.deck = value;
  conf.deckChapter = conf.deckChapter || {};
  // 每本词书各记各的章号，没记过就从第 0 章开始，不要沿用上一本的章号
  const resume = Number.isInteger(conf.deckChapter[value]) ? conf.deckChapter[value] : 0;
  conf.chapter = resume;
  conf.deckChapter[value] = resume;
  conf.progressAt = Date.now();
  save(LS_CONF, conf);
  if (WEB_MODE && !deckCanShowChapter(value, resume)) {
    showStudyLoading('正在加载所选词库，首次只需下载这一套词。');
    try {
      await ensureDeckData(value);
    } catch (err) {
      // 只有当前仍是这次失败的目标词库时才回滚；旧请求不能覆盖后来成功的选择。
      if (activeDeck === value) {
        activeDeck = previous;
        conf.deck = previous;
        save(LS_CONF, conf);
        updateDeckMeta();
        showStudyLoadError();
      }
      return;
    }
    if (activeDeck !== value) return;
  }
  loadChapter(resume);
  bus.emit('deck:change');
  if (!$('viewList').classList.contains('hidden')) renderList(true);
}
function switchView(name) {
  for (const v of ['Study','List','Stat']) $('view' + v).classList.toggle('hidden', v !== name);
  document.querySelectorAll('.tab').forEach(tab => {
    const selected = tab.id === 'tab' + name;
    tab.classList.toggle('active', selected);
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  if (name === 'List') renderList();
  if (name === 'Stat') updateStatsNow();
}
const CHAPTER_SIZE = 200;

// 启动阶段也清洗本地数据：损坏的 JSON、数组、旧版本时间戳不能等到联网同步才处理。
{
  const now = Date.now();
  state = validateStateStore(state, now);
  chapterData = validateChapterStore(chapterData, now);
  daily = validateDailyStore(daily, now);
  conf = validateConfStore(conf);
  activeDeck = Object.prototype.hasOwnProperty.call(DECKS, conf.deck) ? conf.deck : 'core';
}
function chapterCount() { return Math.ceil(deckKnownLength(activeDeck) / CHAPTER_SIZE); }
function currentChapter() { return curChapter; }
function renderChapters() {
  const sel = $('chapterSelect');
  const total = deckKnownLength(activeDeck);
  sel.replaceChildren();
  for (let i = 0; i < chapterCount(); i++) {
    const start = i * CHAPTER_SIZE + 1;
    const end = Math.min((i + 1) * CHAPTER_SIZE, total);
    const opt = document.createElement('option');
    opt.value = String(i);
    opt.textContent = '第' + (i + 1) + '章';
    opt.title = start + '-' + end;
    sel.append(opt);
  }
  sel.value = String(currentChapter());
}
function gotoChapter(i) {
  savePos();
  conf.deck = activeDeck;
  conf.chapter = i;
  conf.deckChapter = conf.deckChapter || {};
  conf.deckChapter[activeDeck] = i;
  conf.progressAt = Date.now();
  save(LS_CONF, conf);
  loadChapter(i);
}
let undoTimer = null, undoWord = null, undoKind = 'mastered', undoChapter = null, undoIdx = 0;
let undoDelta = null;
let undoBefore = undefined;   // 这一步给 daily 加了多少，撤销时要原样减回去
function clearUndoBar() {
  clearTimeout(undoTimer);
  undoWord = null;
  undoChapter = null;
  undoDelta = null;
  const bar = document.getElementById('undoBar');
  if (bar) bar.classList.add('hidden');
}
function showUndo(word, kind, delta, before, pos) {
  undoWord = word;
  undoKind = kind || 'mastered';
  undoDelta = delta ? { day: dayKey(Date.now()), ...delta } : null;
  undoBefore = before === undefined ? undefined : { ...before };
  undoChapter = chapterKey(curChapter);
  undoIdx = Number.isInteger(pos) ? pos : Math.min(idx, queue.length);
  $('undoText').textContent = (undoKind === 'restored' ? '已恢复：' : '已认识：') + word.word;
  $('undoBar').classList.remove('hidden');
  clearTimeout(undoTimer);
  undoTimer = setTimeout(() => { $('undoBar').classList.add('hidden'); undoWord = null; undoBefore = undefined; }, 5000);
}
function doUndo() {
  const word = undoWord;
  if (!word) return;
  const before = undoBefore, pos = undoIdx, delta = undoDelta, now = Date.now();
  const key = undoChapter;
  const cut = key ? key.lastIndexOf(':') : -1;
  const undoDeck = cut > 0 ? key.slice(0, cut) : activeDeck;
  const undoCh = cut > 0 ? Number(key.slice(cut + 1)) : curChapter;
  // 跨章后撤销仍应有效：先回到动作发生的章节，再恢复记录。
  const needsNavigate = key !== chapterKey(curChapter);
  if (needsNavigate && (undoDeck !== activeDeck || !Number.isInteger(undoCh))) {
    clearUndoBar();
    showSessionNotice('撤销窗口已过期，请重新操作。', 5000);
    return;
  }
  const previous = state[word.word];
  state[word.word] = before === undefined ? tombstone(now) : { ...before, t: now };
  if (!saveStateRecord(word.word)) {
    if (previous === undefined) delete state[word.word]; else state[word.word] = previous;
    showSessionNotice('保存失败：浏览器存储空间不足，撤销未完成。', 8000);
    return;
  }
  undoWord = null; undoBefore = undefined; undoDelta = null; undoChapter = null;
  revertDaily(delta);
  $('undoBar').classList.add('hidden');
  clearTimeout(undoTimer);
  revealed = null;
  // 必须重建队列并优先定位被撤销的词；直接 render 会让已移出队列的词仍然消失。
  loadChapter(needsNavigate ? undoCh : curChapter, undefined, pos, word.word, true, true);
  savePos();
}
$('undoBtn').onclick = doUndo;
