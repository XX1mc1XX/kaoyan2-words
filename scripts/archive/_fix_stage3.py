# -*- coding: utf-8 -*-
"""第三阶段：统计口径改为「待学」、修正过时文案。"""
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


rep("    meaning.textContent = '点卡片或「显示释义」查看中文';",
    "    meaning.textContent = '点卡片翻面看中文';", "释义占位文案")

rep("  $('sDue').textContent = learned - mastered;",
    "  $('sDue').textContent = deckWords().length - mastered;", "未掌握 -> 待学（总数-已掌握）")

rep('<div class="stat"><b id="sDue">0</b><span>未掌握</span></div>',
    '<div class="stat"><b id="sDue">0</b><span>待学</span></div>', "统计标签改名")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
