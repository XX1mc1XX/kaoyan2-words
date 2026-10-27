# -*- coding: utf-8 -*-
"""右滑不跳词 + 左滑快速滑出 + 新建「已认识」词库。"""
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


# 1. 词库下拉加「已认识」
rep('    <option value="insurance">高/中频保险库</option>',
    '    <option value="insurance">高/中频保险库</option>\n    <option value="mastered">已认识</option>',
    "下拉加已认识")

# 2. DECKS + 动态 deckWords
rep("""  insurance: { label: '高/中频保险库', note: '高/中频保险库：收入闪过中未进主线的词，只用于补漏，不建议一开始通背。', words: INSURANCE }
};
let activeDeck = Object.prototype.hasOwnProperty.call(DECKS, conf.deck) ? conf.deck : 'core';
const deckWords = () => DECKS[activeDeck].words;""",
    """  insurance: { label: '高/中频保险库', note: '高/中频保险库：收入闪过中未进主线的词，只用于补漏，不建议一开始通背。', words: INSURANCE },
  mastered: { label: '已认识', note: '左滑认识的词都收进这里，不会被删除。去「词表」页点「恢复」可以放回原词库。', words: [] }
};
let activeDeck = Object.prototype.hasOwnProperty.call(DECKS, conf.deck) ? conf.deck : 'core';
const ALL_WORDS = (() => {
  const seen = new Set(), list = [];
  for (const w of [...WORDS, ...DERIVATIVES, ...BASIC, ...INSURANCE]) {
    if (!seen.has(w.word)) { seen.add(w.word); list.push(w); }
  }
  return list;
})();
const deckWords = () => (activeDeck === 'mastered'
  ? ALL_WORDS.filter(w => isMastered(w))
  : DECKS[activeDeck].words);""", "DECKS 加 mastered")

# 3. mark：左滑前进，右滑原地
rep("""  if (known) st.mastered = true;
  else st.w = (st.w || 0) + 1;
  state[word.word] = st;
  save(LS_STATE, state);
  idx += 1;
  revealed = null;
  savePos();
  renderStudy();
  updateStats();
}""",
    """  if (known) st.mastered = true;
  else st.w = (st.w || 0) + 1;
  state[word.word] = st;
  save(LS_STATE, state);
  if (known) {
    idx += 1;                                          // 认识：前进
    revealed = null;
    savePos();
    renderStudy();
  } else if (navigator.vibrate) {
    navigator.vibrate(22);                             // 不认识：留在当前词，只震一下
  }
  updateStats();
}""", "mark 右滑不前进")

# 4. touchend：左滑滑出动画 / 右滑回弹
rep("""  // 先把跟手位移弹回去
  card.style.transition = 'transform .16s ease, opacity .16s ease, border-color .16s ease';
  card.style.transform = '';
  card.style.opacity = '';
  card.style.borderColor = '';
  setTimeout(() => { card.style.transition = ''; }, 200);

  if (!moved && elapsed < 400) { toggleMeaning(); return; }
  const absX = Math.abs(dx), absY = Math.abs(dy);
  // 横向优先：左滑认识 / 右滑不认识
  if (absX >= 34 && absX >= absY) {
    const word = queue[idx];
    if (word) mark(word, dx < 0);
    return;
  }
  // 纵向翻词
  if (absY >= 34 && absY > absX) navigate(dy < 0 ? 1 : -1);""",
    """  if (!moved && elapsed < 400) {
    card.style.transform = ''; card.style.opacity = ''; card.style.borderColor = ''; card.style.transition = '';
    toggleMeaning();
    return;
  }
  const absX = Math.abs(dx), absY = Math.abs(dy);
  const word = queue[idx];
  if (word && absX >= 34 && absX >= absY) {
    if (dx < 0) {
      // 左滑：跟手 → 130ms 滑出 → 切下一词
      card.style.transition = 'transform .13s ease-out, opacity .13s ease-out';
      card.style.transform = 'translateX(-110%)';
      card.style.opacity = '0';
      setTimeout(() => {
        card.style.transition = 'none';
        card.style.transform = '';
        card.style.opacity = '';
        card.style.borderColor = '';
        mark(word, true);
        requestAnimationFrame(() => { card.style.transition = ''; });
      }, 130);
    } else {
      // 右滑：回弹 + 权重 +1，停在当前词
      card.style.transition = 'transform .16s ease, opacity .16s ease, border-color .16s ease';
      card.style.transform = '';
      card.style.opacity = '';
      card.style.borderColor = 'var(--bad)';
      setTimeout(() => { card.style.borderColor = ''; card.style.transition = ''; }, 260);
      mark(word, false);
    }
    return;
  }
  // 纵向翻词：先弹回再翻
  card.style.transition = 'transform .16s ease, opacity .16s ease, border-color .16s ease';
  card.style.transform = ''; card.style.opacity = ''; card.style.borderColor = '';
  setTimeout(() => { card.style.transition = ''; }, 200);
  if (absY >= 34 && absY > absX) navigate(dy < 0 ? 1 : -1);""", "touchend 动画重写")

# 5. done 分支支持「已认识」词库
rep("""    const left = chapterSlice(curChapter).filter(w => !isMastered(w)).length;
    $('doneTitle').textContent = left ? '本轮过完了' : '这一章全部掌握';""",
    """    if (activeDeck === 'mastered') {
      $('doneTitle').textContent = '这里是已认识的词';
      $('doneHint').textContent = '共 ' + deckWords().length + ' 个。去「词表」页点「恢复」可以放回原词库。';
      $('doneAction').textContent = '去看词表';
      $('doneAction').dataset.mode = 'list';
      return;
    }
    const left = chapterSlice(curChapter).filter(w => !isMastered(w)).length;
    $('doneTitle').textContent = left ? '本轮过完了' : '这一章全部掌握';""", "done 分支 mastered")

# 6. doneAction 支持跳词表
rep("""  const mode = $('doneAction').dataset.mode;
  if (mode === 'reshuffle') {""",
    """  const mode = $('doneAction').dataset.mode;
  if (mode === 'list') { switchView('List'); return; }
  if (mode === 'reshuffle') {""", "doneAction 跳词表")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
