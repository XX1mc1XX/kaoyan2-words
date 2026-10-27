# -*- coding: utf-8 -*-
"""进度条：拖动过程中实时同步序号和卡片内容。"""
import io

P = r"c:\my_project\单词\software\template.html"
t = io.open(P, encoding="utf-8").read()

OLD = """$('progressBar').onchange = event => {
  if (!queue.length) return;
  idx = Math.min(Math.max(Number(event.target.value), 0), queue.length - 1);
  revealed = null;
  savePos();
  renderStudy();
};"""

NEW = """$('progressBar').oninput = event => {
  if (!queue.length) return;
  idx = Math.min(Math.max(Number(event.target.value), 0), queue.length - 1);
  revealed = null;
  dragging = true;
  renderStudy();
};
$('progressBar').onchange = event => {
  dragging = false;
  savePos();
};"""

# renderStudy 里拖动时不要回写 value，避免手感跳动
OLD_SYNC = """  $('progressBar').max = String(Math.max(total, 1));
  $('progressBar').value = String(Math.min(idx, total));"""
NEW_SYNC = """  $('progressBar').max = String(Math.max(total, 1));
  if (!dragging) $('progressBar').value = String(Math.min(idx, total));"""

ok1 = OLD in t
ok2 = OLD_SYNC in t
t = t.replace(OLD, NEW, 1).replace(OLD_SYNC, NEW_SYNC, 1)

# dragging 变量声明
if "let dragging = false;" not in t:
    t = t.replace("let revealed = null;", "let revealed = null;\nlet dragging = false;", 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("绑定替换:", ok1, "| 回写保护:", ok2, "| dragging 变量:", t.count("let dragging = false;"))
