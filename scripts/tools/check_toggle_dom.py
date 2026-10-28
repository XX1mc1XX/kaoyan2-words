# -*- coding: utf-8 -*-
"""检查释义开关按钮是否真的渲染进产物。"""
import io
import re

p = r"c:\my_project\单词\software\考研核心词.html"
t = io.open(p, encoding="utf-8").read()

m = re.search(r'<div class="study-head">.*?</div>', t, re.S)
print("study-head HTML:")
print(m.group(0) if m else "未匹配")
print()
print('class="meaning-toggle" 出现:', t.count('class="meaning-toggle"'))
print('id="meaningToggle" 出现:', t.count('id="meaningToggle"'))
print('释义关/释义开 出现:', t.count("释义关") + t.count("释义开"))

i = t.find('id="meaningToggle"')
if i > 0:
    print("\n上下文:")
    print(t[i - 260:i + 120])
