# -*- coding: utf-8 -*-
"""重做左右滑手势：降低阈值 + 跟随位移 + 左绿右红反馈。"""
import io
import re

P = r"c:\my_project\单词\software\template.html"
t = io.open(P, encoding="utf-8").read()
log = []

OLD_MOVE = """card.addEventListener('touchmove', event => {
  if (!touchStart || event.touches.length !== 1) return;
  const t = event.touches[0];
  const dx = t.clientX - touchStart.x, dy = t.clientY - touchStart.y;
  if (Math.abs(dx) > 8 || Math.abs(dy) > 8) touchStart.moved = true;
  if (Math.abs(dy) > 12 && Math.abs(dy) > Math.abs(dx) * 1.15) event.preventDefault();
}, { passive: false });"""

NEW_MOVE = """card.addEventListener('touchmove', event => {
  if (!touchStart || event.touches.length !== 1) return;
  const t = event.touches[0];
  const dx = t.clientX - touchStart.x, dy = t.clientY - touchStart.y;
  if (Math.abs(dx) > 6 || Math.abs(dy) > 6) touchStart.moved = true;
  const absX = Math.abs(dx), absY = Math.abs(dy);
  if (absX > absY) {
    // 横向：跟手位移 + 颜色提示，同时阻止浏览器横向手势
    event.preventDefault();
    const shift = Math.max(-130, Math.min(130, dx));
    card.style.transition = 'none';
    card.style.transform = 'translateX(' + shift + 'px)';
    card.style.opacity = String(1 - Math.min(absX / 420, 0.28));
    card.style.borderColor = absX > 30 ? (dx < 0 ? 'var(--ok)' : 'var(--bad)') : '';
  } else if (absY > 10) {
    event.preventDefault();
  }
}, { passive: false });"""

OLD_END = """  if (!moved && elapsed < 450) { toggleMeaning(); return; }
  const absX = Math.abs(dx), absY = Math.abs(dy);
  // 横向优先判断：左滑认识 / 右滑不认识
  if (absX >= 50 && absX > absY) {
    const word = queue[idx];
    if (word) mark(word, dx < 0);
    return;
  }
  // 纵向翻词
  if (absY >= 40 && absY > absX) navigate(dy < 0 ? 1 : -1);"""

NEW_END = """  // 先把跟手位移弹回去
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
  if (absY >= 34 && absY > absX) navigate(dy < 0 ? 1 : -1);"""

for old, new, label in ((OLD_MOVE, NEW_MOVE, "touchmove 跟手反馈"), (OLD_END, NEW_END, "touchend 阈值+回弹")):
    if old in t:
        t = t.replace(old, new, 1)
        log.append("OK    " + label)
    else:
        log.append("MISS  " + label)

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
print("absX >= 34 出现:", t.count("absX >= 34"), "| translateX:", t.count("translateX"))
