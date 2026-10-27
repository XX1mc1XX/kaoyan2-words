# -*- coding: utf-8 -*-
"""抽样检查释义：短释义、单字释义、疑似丢失主要义项的词。"""
import io
import json

D = r"c:\my_project\单词\data"
DECKS = ("words", "derivatives", "basic", "insurance")

allw = []
for d in DECKS:
    for x in json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")):
        allw.append((d, x["word"], x.get("meaning", ""), x.get("freq", 0)))

short = [r for r in allw if len(r[2]) <= 2]
print("释义 <=2 字的词: %d 个（共 %d）" % (len(short), len(allw)))
for d, w, m, f in sorted(short, key=lambda r: -r[3])[:25]:
    print("  %-14s %-8s freq=%s" % (w, m, f))

print("\n--- 高频词释义抽查（freq 最高的 30 个）---")
for d, w, m, f in sorted(allw, key=lambda r: -r[3])[:30]:
    print("  %-16s %-22s freq=%s" % (w, m, f))
