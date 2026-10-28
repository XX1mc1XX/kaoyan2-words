# -*- coding: utf-8 -*-
"""补上 touchStart 重置，避免点单词后残留导致手势误判。"""
import io

P = r"c:\my_project\单词\software\template.html"
t = io.open(P, encoding="utf-8").read()

OLD = "$('word').addEventListener('touchend', event => {\n  event.stopPropagation();\n});"
NEW = ("$('word').addEventListener('touchend', event => {\n"
       "  event.stopPropagation();\n"
       "  touchStart = null;      // 防止残留导致下一次手势误判\n"
       "});")

print("找到目标:", OLD in t)
t = t.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("touchStart = null 出现次数:", t.count("touchStart = null"))
