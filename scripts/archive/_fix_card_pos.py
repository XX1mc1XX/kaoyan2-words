# -*- coding: utf-8 -*-
"""把卡片内容位置改回垂直居中：手势提示改成绝对定位，不再挤压布局。"""
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


rep(".swipe-hint{margin-top:auto;font-size:11.5px;color:var(--muted);padding-top:12px}",
    ".swipe-hint{position:absolute;left:0;right:0;bottom:10px;text-align:center;\n"
    "  font-size:11px;color:var(--muted);opacity:.8;pointer-events:none}",
    "手势提示改绝对定位")

# 卡片内容保持垂直居中，并给底部提示留出空间
rep(".card{position:relative;flex:1;min-height:0;background:var(--card);border:1px solid var(--line);border-radius:22px;\n  box-shadow:var(--shadow);padding:18px;",
    ".card{position:relative;flex:1;min-height:0;background:var(--card);border:1px solid var(--line);border-radius:22px;\n  box-shadow:var(--shadow);padding:36px 18px 40px;",
    "卡片内边距为徽章和提示留位")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
