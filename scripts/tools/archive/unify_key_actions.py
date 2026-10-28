# -*- coding: utf-8 -*-
"""键盘与滑动统一动作；弹窗打开时不响应快捷键。"""
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


rep("function mark(word, known) {",
    """// 左滑/左键、右滑/右键统一走这里，滑动和键盘不再各有一套语义
function applyWordAction(word, dir) {
  if (!word) return;
  if (activeDeck === 'mastered') {
    if (dir === 'left') lowerWeight(word);
    else restoreMastered(word);
  } else {
    mark(word, dir === 'left');
  }
}
function mark(word, known) {""", "统一动作函数")

rep("""window.addEventListener('keydown', event => {
  if (event.repeat) return;
  const active = document.activeElement;
  if (active && (['INPUT','TEXTAREA','SELECT'].includes(active.tagName) || active.isContentEditable)) return;
  if ($('viewStudy').classList.contains('hidden')) return;
  if (event.code === 'Space') { event.preventDefault(); toggleMeaning(); return; }
  if (event.key === 'ArrowUp') { event.preventDefault(); navigate(-1); return; }
  if (event.key === 'ArrowDown') { event.preventDefault(); navigate(1); return; }
  if (event.key === 'ArrowLeft') { event.preventDefault(); const w = queue[idx]; if (w) mark(w, true); return; }
  if (event.key === 'ArrowRight') { event.preventDefault(); const w = queue[idx]; if (w) mark(w, false); return; }
});""",
    """window.addEventListener('keydown', event => {
  if (event.repeat) return;
  const active = document.activeElement;
  if (active && (['INPUT','TEXTAREA','SELECT'].includes(active.tagName) || active.isContentEditable)) return;
  // 登录弹窗开着时不要动背后的卡片
  if (!$('authModal').classList.contains('hidden')) return;
  if ($('viewStudy').classList.contains('hidden')) return;
  if (event.code === 'Space') {
    if (active && active.tagName === 'BUTTON') return;   // 让按钮自己响应空格
    event.preventDefault();
    toggleMeaning();
    return;
  }
  if (event.key === 'ArrowUp') { event.preventDefault(); navigate(-1); return; }
  if (event.key === 'ArrowDown') { event.preventDefault(); navigate(1); return; }
  if (event.key === 'ArrowLeft') { event.preventDefault(); applyWordAction(queue[idx], 'left'); return; }
  if (event.key === 'ArrowRight') { event.preventDefault(); applyWordAction(queue[idx], 'right'); return; }
});""", "键盘守卫与统一动作")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
