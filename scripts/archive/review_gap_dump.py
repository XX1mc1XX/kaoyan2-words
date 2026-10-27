# -*- coding: utf-8 -*-
"""导出全部缺口候选（含 ECDICT 元信息）到 TSV，供人工/规则复核。"""
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
                    "oxford": row[6] == "1",
                    "tag": row[7].strip(),
                    "pos": row[4].strip(),
                    "zh": row[3].strip().replace("\n", " | "),
                    "en": row[2].strip().replace("\n", " | ")[:80],
                }

rows = []
for w, info in freq.items():
    if w in have or info["proper"] or len(w) < 3:
        continue
    m = meta.get(w)
    if not m:
        continue
    rows.append((w, info["count"], info["coverage"], m["collins"], m["tag"], m["pos"], m["zh"], m["en"]))

rows.sort(key=lambda x: (-x[1], -x[2], x[0]))

with io.open(r"c:\my_project\单词\scripts\review_gap_candidates.tsv", "w", encoding="utf-8", newline="") as f:
    f.write("word\tcount\tcoverage\tcollins\ttags\tpos\tzh\ten\n")
    for r in rows:
        f.write("\t".join(str(x) for x in r) + "\n")

print(len(rows))
