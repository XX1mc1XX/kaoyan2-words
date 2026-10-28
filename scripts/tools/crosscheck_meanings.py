# -*- coding: utf-8 -*-
"""释义交叉验证：把我们的中文释义与 ECDICT 的中文释义对撞，找出低重合的可疑条目。"""
import csv
import io
import json
import re

D = r"c:\my_project\单词\data"
DECKS = ("words", "derivatives", "basic", "insurance")
CJK = re.compile(r"[一-鿿]")

mine = {}
for d in DECKS:
    for x in json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")):
        mine[x["word"]] = (x.get("meaning") or "", d, x.get("freq", 0))

ecd = {}
with io.open(D + r"\ecdict.csv", encoding="utf-8", errors="replace", newline="") as f:
    r = csv.reader(f)
    next(r, None)
    for row in r:
        if len(row) < 11:
            continue
        w = row[0].lower()
        if w in mine:
            ecd[w] = row[3]

# 无意义的高频字，不计入重合判断
STOP_CHARS = set("的了是在和与或也都很不有个这那之为以对从到把将被使于其")

def cjk_set(s):
    return {c for c in CJK.findall(s or "") if c not in STOP_CHARS}

suspect = []
compared = 0
for w, (m, deck, freq) in mine.items():
    e = ecd.get(w)
    if not m or not e:
        continue
    a, b = cjk_set(m), cjk_set(e.split("[")[0])
    if not a or not b:
        continue
    compared += 1
    hit = len(a & b)
    ratio = hit / min(len(a), len(b))
    if ratio == 0:
        suspect.append((w, m, e.split("\n")[0][:36], ratio, deck, freq))

suspect.sort(key=lambda r: -r[5])
print("可交叉验证 %d 条，完全无重合 %d 条\n" % (compared, len(suspect)))
print("%-16s %-18s %-36s %s" % ("word", "我们的释义", "ECDICT 释义", "freq"))
for w, m, e, ratio, deck, freq in suspect[:60]:
    print("%-16s %-18s %-36s %s" % (w, m[:16], e, freq))
