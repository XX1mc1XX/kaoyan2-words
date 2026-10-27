# -*- coding: utf-8 -*-
"""进度条改用原生 accent-color 渲染，保证轨道可见。"""
import io

P = r"c:\my_project\单词\software\template.html"
t = io.open(P, encoding="utf-8").read()

OLD = """.progress{-webkit-appearance:none;appearance:none;width:100%;height:20px;background:transparent;flex-shrink:0;margin:0;cursor:pointer;touch-action:none}
.progress::-webkit-slider-runnable-track{height:5px;border-radius:999px;background:var(--line)}
.progress::-webkit-slider-thumb{-webkit-appearance:none;width:15px;height:15px;margin-top:-5px;border-radius:50%;background:var(--brand);border:2px solid var(--card);box-shadow:0 1px 3px rgba(0,0,0,.35)}
.progress::-moz-range-track{height:5px;border-radius:999px;background:var(--line)}
.progress::-moz-range-thumb{width:15px;height:15px;border-radius:50%;background:var(--brand);border:2px solid var(--card)}"""

NEW = ".progress{width:100%;height:20px;flex-shrink:0;margin:0;cursor:pointer;accent-color:var(--brand);touch-action:none}"

print("找到旧样式:", OLD in t)
t = t.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("写入完成，accent-color 出现次数:", t.count("accent-color"))
