# -*- coding: utf-8 -*-
"""修：进度条不随认识变化、已认识词库为空、恢复后找不到原章节。"""
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


# --- 1. 左滑后把词从当前队列移除，进度条总数跟着变 ---
rep("""  if (known) {
    idx += 1;                                          // 认识：前进
    revealed = null;
    savePos();
    renderStudy();
  } else if (navigator.vibrate) {""",
    """  if (known) {
    // 移出当前队列：进度条总数同步减少，下一个词自动顶上原位
    queue = queue.filter(w => w.word !== word.word);
    if (idx >= queue.length) idx = Math.max(queue.length - 1, 0);
    revealed = null;
    savePos();
    renderStudy();
  } else if (navigator.vibrate) {""", "左滑重建队列")

# --- 2. 「已认识」词库：不再被 mastered 过滤掉 ---
rep("""  for (const word of deckWords()) {
    const mastered = isMastered(word);
    if (priorityFilter === 'mastered') {
      if (!mastered) continue;
    } else {
      if (mastered) continue;
      const p = (word.priority || 'C').charAt(0);
      if (priorityFilter !== 'all' && p !== priorityFilter) continue;
    }""",
    """  const inMasteredDeck = activeDeck === 'mastered';
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
    }""", "已认识词库可见")

# --- 3. 恢复按钮：标注原词库和章节，点了跳回去 ---
rep("""    let badge;
    if (mastered) {
      badge = document.createElement('button');
      badge.className = 'restore-btn';
      badge.textContent = '恢复';
      badge.onclick = () => {
        const st = state[word.word];
        if (st) { st.mastered = false; state[word.word] = st; save(LS_STATE, state); }
        renderList(); updateStats(); loadChapter(curChapter);
      };
    } else {""",
    """    let badge;
    if (mastered) {
      const owner = deckOfWord(word.word);
      badge = document.createElement('button');
      badge.className = 'restore-btn';
      badge.textContent = '恢复';
      badge.title = owner ? (DECKS[owner].label + ' 第' + (Math.floor(ownerIndex(owner, word.word) / CHAPTER_SIZE) + 1) + '章') : '';
      badge.onclick = () => {
        const st = state[word.word];
        if (st) { st.mastered = false; state[word.word] = st; save(LS_STATE, state); }
        if (owner) {
          const ch = Math.floor(ownerIndex(owner, word.word) / CHAPTER_SIZE);
          switchDeck(owner);
          savePos();
          loadChapter(ch);
        } else {
          renderList(); updateStats(); loadChapter(curChapter);
        }
      };
    } else {""", "恢复按钮跳回原章节")

# --- 4. 辅助函数：找词所属词库和序号 ---
rep("""function updateDeckMeta() {""",
    """function deckOfWord(name) {
  for (const key of ['core', 'derivative', 'foundation', 'insurance']) {
    if (DECKS[key].words.some(w => w.word === name)) return key;
  }
  return null;
}
function ownerIndex(deckKey, name) {
  return DECKS[deckKey].words.findIndex(w => w.word === name);
}
function updateDeckMeta() {""", "新增 deckOfWord/ownerIndex")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
