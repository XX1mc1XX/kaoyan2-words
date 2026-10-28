# -*- coding: utf-8 -*-
"""登录按钮移到左上角；跨章翻页；已认识词库可正常背诵（左滑降权重 / 右滑恢复）。"""
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


# ---------- 1. 登录按钮移到最左 ----------
rep('''<header>
  <span class="brand">英语二词汇</span><span class="spacer"></span>''',
    '''<header>
  <button class="account-btn" id="accountBtn">登录</button>
  <span class="brand">英语二词汇</span><span class="spacer"></span>''', "登录按钮左上")

rep('''    <button class="tab" id="tabStat">统计</button>
    <button class="account-btn" id="accountBtn">登录</button>''',
    '''    <button class="tab" id="tabStat">统计</button>''', "移除右侧登录按钮")

# ---------- 2. 已认识库：不过滤，全部可背 ----------
rep('''  // 未掌握的照常出现；已掌握但到了 7 天复习期的，也重新出现
  const pending = chapterSlice(ch).filter(w => {
    if (!isMastered(w)) return true;
    const st = state[w.word];
    return !!(st && st.due && st.due <= now);
  });''',
    '''  // 未掌握的照常出现；已掌握但到了 7 天复习期的，也重新出现
  // 「已认识」库里所有词本来就是已掌握，不能再过滤，否则一章 0 词
  const pending = activeDeck === 'mastered'
    ? chapterSlice(ch).slice()
    : chapterSlice(ch).filter(w => {
        if (!isMastered(w)) return true;
        const st = state[w.word];
        return !!(st && st.due && st.due <= now);
      });''', "已认识库不过滤")

# ---------- 3. 降权重 / 恢复 两个动作 ----------
rep('''function mark(word, known) {''',
    '''// 已认识库：左滑降权重
function lowerWeight(word) {
  if (!word) return;
  const st = state[word.word];
  if (!st || !st.w) return;
  st.w = Math.max(0, st.w - 1);
  save(LS_STATE, state);
  if (navigator.vibrate) navigator.vibrate(18);
  renderStudy();
}
// 已认识库：右滑恢复，放回原词库
function restoreMastered(word) {
  if (!word) return;
  const st = state[word.word];
  if (st) { st.mastered = false; st.due = 0; save(LS_STATE, state); }
  queue = queue.filter(w => w.word !== word.word);
  if (idx >= queue.length) idx = Math.max(queue.length - 1, 0);
  revealed = null;
  savePos();
  renderStudy();
  updateStats();
  showUndo(word, 'restored');
}
function mark(word, known) {''', "新增降权重与恢复")

# ---------- 4. 撤销支持两种动作 ----------
rep('''let undoTimer = null, undoWord = null;
function showUndo(word) {
  undoWord = word;
  $('undoText').textContent = '已认识：' + word.word;''',
    '''let undoTimer = null, undoWord = null, undoKind = 'mastered';
function showUndo(word, kind) {
  undoWord = word;
  undoKind = kind || 'mastered';
  $('undoText').textContent = (undoKind === 'restored' ? '已恢复：' : '已认识：') + word.word;''', "撤销条区分动作")

rep('''  const st = state[word.word];
  if (st) { st.mastered = false; st.due = 0; state[word.word] = st; save(LS_STATE, state); }
  queue.splice(Math.min(idx, queue.length), 0, word);''',
    '''  const st = state[word.word];
  if (st) {
    if (undoKind === 'restored') { st.mastered = true; st.due = todayTs() + 7 * DAY; }
    else { st.mastered = false; st.due = 0; }
    state[word.word] = st;
    save(LS_STATE, state);
  }
  queue.splice(Math.min(idx, queue.length), 0, word);''', "撤销按动作还原")

# ---------- 5. 滑动手势按词库分流 ----------
rep('''  if (word && absX >= 34 && absX >= absY && startX > 26) {
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
  }''',
    '''  if (word && absX >= 34 && absX >= absY && startX > 26) {
    const inMastered = activeDeck === 'mastered';
    const slideOut = action => {
      card.style.transition = 'transform .13s ease-out, opacity .13s ease-out';
      card.style.transform = 'translateX(-110%)';
      card.style.opacity = '0';
      setTimeout(() => {
        card.style.transition = 'none';
        card.style.transform = '';
        card.style.opacity = '';
        card.style.borderColor = '';
        action();
        requestAnimationFrame(() => { card.style.transition = ''; });
      }, 130);
    };
    const bounce = () => {
      card.style.transition = 'transform .16s ease, opacity .16s ease, border-color .16s ease';
      card.style.transform = '';
      card.style.opacity = '';
      card.style.borderColor = dx < 0 ? 'var(--ok)' : 'var(--bad)';
      setTimeout(() => { card.style.borderColor = ''; card.style.transition = ''; }, 260);
    };
    if (dx < 0) {
      // 左滑：普通库=认识；已认识库=降权重（停在当前词）
      if (inMastered) { bounce(); lowerWeight(word); }
      else slideOut(() => mark(word, true));
    } else {
      // 右滑：普通库=不认识（权重+1）；已认识库=恢复原词库
      if (inMastered) slideOut(() => restoreMastered(word));
      else { bounce(); mark(word, false); }
    }
    return;
  }''', "手势按词库分流")

# ---------- 6. 跨章节翻页 ----------
rep('''function navigate(delta) {
  if (!queue.length || idx >= queue.length) return;
  const next = idx + delta;
  if (next < 0 || next >= queue.length) return;
  idx = next;
  revealed = null;
  savePos();
  renderStudy();
}''',
    '''function navigate(delta) {
  const next = idx + delta;
  // 到章节边界就翻到相邻章节：上一章停最后一词，下一章停第一词
  if (next < 0) { crossChapter(-1); return; }
  if (next >= queue.length) { crossChapter(1); return; }
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
  loadChapter(target);
  idx = dir < 0 ? Math.max(queue.length - 1, 0) : 0;
  savePos();
  renderStudy();
  renderChapters();
  return true;
}''', "跨章翻页")

rep('''  $('prevWord').disabled = idx <= 0;
  $('nextWord').disabled = idx >= total - 1;''',
    '''  $('prevWord').disabled = idx <= 0 && curChapter <= 0;
  $('nextWord').disabled = idx >= total - 1 && curChapter >= chapterCount() - 1;''', "按钮边界改按章节")

# ---------- 7. 手势提示随词库变化 ----------
rep('<div class="swipe-hint">左滑 = 认识（不再出现）· 右滑 = 不认识（权重+1）</div>',
    '<div class="swipe-hint" id="swipeHint">左滑 = 认识（不再出现）· 右滑 = 不认识（权重+1）</div>', "提示加 id")

rep('''  $('chapterSelect').value = String(currentChapter());
  $('prevWord').disabled''',
    '''  $('swipeHint').textContent = activeDeck === 'mastered'
    ? '左滑 = 降权重 · 右滑 = 恢复到原词库'
    : '左滑 = 认识（不再出现）· 右滑 = 不认识（权重+1）';
  $('chapterSelect').value = String(currentChapter());
  $('prevWord').disabled''', "提示文案动态")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
