# -*- coding: utf-8 -*-
"""应用子代理逐条审校结果（已人工逐条过一遍，少量覆盖）。"""
import io
import json
import os
import shutil

ROOT = r"c:\my_project\单词"
DECKS = ("words", "derivatives", "basic", "insurance")

changes = {}
for i in range(1, 6):
    for x in json.load(io.open(os.path.join(ROOT, "output", "review", "result_%d.json" % i), encoding="utf-8")):
        changes[x["word"]] = (x["old"], x["new"])

# 人工覆盖：子代理判断偏离考研高频义
OVERRIDE = {
    "offer": "提供",
    "text": "文本",
    "group": "群体",
    "back": "背部；向后",
}
for w, new in OVERRIDE.items():
    if w in changes:
        changes[w] = (changes[w][0], new)

bak = os.path.join(ROOT, "output", "review", "backup")
os.makedirs(bak, exist_ok=True)

applied = 0
mismatch = []
for d in DECKS:
    p = os.path.join(ROOT, "data", d + ".json")
    shutil.copyfile(p, os.path.join(bak, d + ".json"))
    rows = json.load(io.open(p, encoding="utf-8"))
    for x in rows:
        fix = changes.get(x["word"])
        if not fix:
            continue
        old, new = fix
        if x["meaning"] != old:
            mismatch.append((d, x["word"], x["meaning"], old))
            continue
        x["meaning"] = new
        applied += 1
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))

print("应用", applied, "条；跳过", len(mismatch), "条")
for m in mismatch:
    print("  MISMATCH", m)
