# -*- coding: utf-8 -*-
"""扫描 insurance 库里的可疑条目：词根碎片、错义、异常 forms。"""
import io
import json

D = r"c:\my_project\单词\data"
ins = json.load(io.open(D + r"\insurance.json", encoding="utf-8"))

short0 = [x for x in ins if len(x["word"]) <= 5 and (x.get("freq") or 0) == 0]
print("insurance 总数 %d | 长度<=5 且 freq=0: %d" % (len(ins), len(short0)))
for x in short0:
    print("  %-8s %-22s freq=%s band=%s" % (x["word"], (x.get("meaning") or "")[:20], x.get("freq"), x.get("band")))

print("\n--- 已知错义词定位 ---")
targets = {"colon", "cult", "veal", "flour", "heart"}
for deck in ("words", "derivatives", "basic", "insurance"):
    data = json.load(io.open(D + "\\" + deck + ".json", encoding="utf-8"))
    for x in data:
        if x["word"] in targets:
            print("  [%s] %-8s %s" % (deck, x["word"], (x.get("meaning") or "")[:40]))

print("\n--- forms 与其他主词重复（跨库）---")
allwords = {}
for deck in ("words", "derivatives", "basic", "insurance"):
    for x in json.load(io.open(D + "\\" + deck + ".json", encoding="utf-8")):
        allwords.setdefault(x["word"], []).append(deck)

dups = []
for deck in ("words", "derivatives", "basic", "insurance"):
    for x in json.load(io.open(D + "\\" + deck + ".json", encoding="utf-8")):
        for f in (x.get("forms") or []):
            if f in allwords and f != x["word"]:
                dups.append((x["word"], f, deck, allwords[f][0]))
print("forms 指向另一个主词的条目:", len(dups))
for a, b, d1, d2 in dups[:20]:
    print("  %s(%s) -> forms 含 %s(%s)" % (a, d1, b, d2))
