# -*- coding: utf-8 -*-
"""修 codex 报的问题：单词上起手的滑动被吞、撤销跨章错插、跨章翻页朗读两次。"""
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


# 1. 单词的 touchend 不再拦截整条手势链
rep("""let wordTouchedAt = 0;
$('word').addEventListener('touchend', event => {
  event.stopPropagation();
  touchStart = null;      // 防止残留导致下一次手势误判
  const w = queue[idx];
  if (w) { wordTouchedAt = Date.now(); speak(w.word); }
});""",
    """let wordTouchedAt = 0;""", "移除单词 touchend 拦截")

# 2. 点击命中单词时朗读，否则翻面（对手势不产生影响）
rep("""  if (!moved && elapsed < 600) {
    card.style.transform = ''; card.style.opacity = ''; card.style.borderColor = ''; card.style.transition = '';
    toggleMeaning();
    return;
  }""",
    """  if (!moved && elapsed < 600) {
    card.style.transform = ''; card.style.opacity = ''; card.style.borderColor = ''; card.style.transition = '';
    // 点词朗读，点别处翻面；起点落在单词上也只是「点」，不影响手势
    if (event.target.closest && event.target.closest('#word')) {
      const w = queue[idx];
      if (w) { wordTouchedAt = Date.now(); speak(w.word); }
      return;
    }
    toggleMeaning();
    return;
  }""", "点词朗读并入卡片")

# 3. 撤销只对当前章节有效
rep("""let undoTimer = null, undoWord = null, undoKind = 'mastered';
function showUndo(word, kind) {
  undoWord = word;
  undoKind = kind || 'mastered';""",
    """let undoTimer = null, undoWord = null, undoKind = 'mastered', undoChapter = null;
function showUndo(word, kind) {
  undoWord = word;
  undoKind = kind || 'mastered';
  undoChapter = chapterKey(curChapter);""", "撤销记录章节")

rep("""function doUndo() {
  const word = undoWord;
  if (!word) return;""",
    """function doUndo() {
  const word = undoWord;
  if (!word) return;
  // 已经切到别的章节/词库，撤销插回会把别章的词塞进当前队列
  if (undoChapter !== chapterKey(curChapter)) {
    $('undoBar').classList.add('hidden');
    undoWord = null;
    return;
  }""", "撤销校验章节")

rep("""function loadChapter(ch, mode) {   // mode: 'shuffle' 打乱 / 'natural' 原序 / 省略=沿用上次
  curChapter = ch;""",
    """function loadChapter(ch, mode, idxAt) {   // mode: 'shuffle' 打乱 / 'natural' 原序 / 省略=沿用上次
  curChapter = ch;
  clearUndoBar();""", "切章清撤销")

rep("""  queue = ordered;
  if (rec.done && queue.length) {""",
    """  queue = ordered;
  if (typeof idxAt === 'number' && queue.length) {
    idx = idxAt < 0 ? queue.length - 1 : Math.min(idxAt, queue.length - 1);
  } else if (rec.done && queue.length) {""", "支持指定落点")

# 4. 跨章翻页只渲染一次，避免先读上一个位置的词
rep("""  loadChapter(target);
  idx = dir < 0 ? Math.max(queue.length - 1, 0) : 0;
  savePos();
  renderStudy();
  renderChapters();
  return true;""",
    """  loadChapter(target, undefined, dir < 0 ? -1 : 0);
  savePos();
  renderChapters();
  return true;""", "跨章只渲染一次")

# 5. 撤销条的清理函数
rep("""let undoTimer = null, undoWord = null, undoKind = 'mastered', undoChapter = null;""",
    """let undoTimer = null, undoWord = null, undoKind = 'mastered', undoChapter = null;
function clearUndoBar() {
  clearTimeout(undoTimer);
  undoWord = null;
  undoChapter = null;
  const bar = document.getElementById('undoBar');
  if (bar) bar.classList.add('hidden');
}""", "撤销清理函数")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
