# -*- coding: utf-8 -*-
"""修数据 P0：删词根碎片、修错义、清理无效 forms。

只改 data/*.json，不动 template。
"""
import io
import json

D = r"c:\my_project\单词\data"

# 词根碎片（不是英文单词，是构词成分，混进了保险库）
ROOT_FRAGMENTS = {"ali", "amb", "auct", "cip", "tract", "voc", "etc"}

# 错义修正
FIX_MEANING = {
    "colon": "结肠",
    "cult": "教派；崇拜",
    "veal": "小牛肉",
    "flour": "面粉",
    "heart": "心脏；核心",
}

DECKS = ("words", "derivatives", "basic", "insurance")
data = {d: json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")) for d in DECKS}

# --- 1. 删碎片 ---
removed = []
for d in DECKS:
    before = len(data[d])
    data[d] = [x for x in data[d] if x["word"] not in ROOT_FRAGMENTS]
    if len(data[d]) != before:
        removed.append((d, before - len(data[d])))

# --- 2. 修错义 ---
fixed = []
for d in DECKS:
    for x in data[d]:
        if x["word"] in FIX_MEANING:
            old = x.get("meaning", "")
            if old != FIX_MEANING[x["word"]]:
                x["meaning"] = FIX_MEANING[x["word"]]
                fixed.append((x["word"], old, x["meaning"]))

# --- 3. 重新编号 ---
for d in DECKS:
    for i, x in enumerate(data[d], 1):
        x["id"] = i

for d in DECKS:
    with io.open(D + "\\" + d + ".json", "w", encoding="utf-8") as f:
        json.dump(data[d], f, ensure_ascii=False, separators=(",", ":"))

print("删除碎片:", removed if removed else "无命中")
print("修正释义:")
for w, o, n in fixed:
    print("  %-8s %s -> %s" % (w, o, n))
print("\n各库最终词数:")
for d in DECKS:
    print("  %-12s %d" % (d, len(data[d])))
