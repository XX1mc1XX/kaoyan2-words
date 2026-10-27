# -*- coding: utf-8 -*-
"""找出真题高频、但四个库都没收录的词。"""
import csv
import io
import json

D = r"c:\my_project\单词\data"
DECKS = ("words", "derivatives", "basic", "insurance")

have = set()
for d in DECKS:
    for x in json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")):
        have.add(x["word"])

freq = json.load(io.open(D + r"\ky2_freq.json", encoding="utf-8"))["words"]

# ECDICT 元信息（判是否正经大纲词）
meta = {}
with io.open(D + r"\ecdict.csv", encoding="utf-8", errors="replace", newline="") as f:
    r = csv.reader(f)
    next(r, None)
    for row in r:
        if len(row) > 9:
            w = row[0].lower()
            if w in freq and w not in have:
                meta[w] = {
                    "collins": int(row[5]) if row[5].isdigit() else 0,
                    "tag": set(row[7].split()),
                    "meaning": row[3].strip().split("\n")[0][:24],
                }

rows = []
for w, info in freq.items():
    if w in have or w in meta and False:
        continue
    m = meta.get(w)
    if not m:
        continue
    if info["proper"]:
        continue
    if len(w) < 3:
        continue
    rows.append((w, info["count"], info["coverage"], m["collins"], "ky" in m["tag"], m["meaning"]))

rows.sort(key=lambda x: (-x[1], -x[2]))

print("缺口中：有 ECDICT 记录的词 %d 个，下面按真题次数排序取前 60" % len(rows))
print("%-14s %5s %4s %3s %4s  %s" % ("word", "次数", "套数", "星", "考研", "释义"))
for w, c, cov, col, ky, mean in rows[:60]:
    print("%-14s %5d %4d %3d %4s  %s" % (w, c, cov, col, "Y" if ky else "-", mean))
