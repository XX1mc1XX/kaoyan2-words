# -*- coding: utf-8 -*-
import csv
import io
import json

R = r"c:\my_project\单词"
kfreq = json.load(io.open(R + r"\data\ky2_freq.json", encoding="utf-8"))
rows = json.load(io.open(R + r"\data\words.json", encoding="utf-8"))
by = {x["word"]: x for x in rows}

for w in ("development", "develop", "agreement", "treatment", "achievement", "improvement"):
    k = kfreq.get(w)
    print(f'{w:<15} 真题={k["count"] if k else "未出现":<5} 在表={"是" if w in by else "否"}')

print("\n=== 词频分布 ===")
for lo, hi in [(50, 9999), (30, 49), (20, 29), (10, 19), (5, 9), (3, 4), (2, 2), (1, 1)]:
    n = sum(1 for r in rows if lo <= r["freq"] <= hi)
    print(f"  {lo:>3}-{hi:<5} {n:>5}")

print("\n=== 只出现 1 次的词，抽 40 个 ===")
once = [r["word"] for r in rows if r["freq"] == 1]
print("  ", " ".join(once[:40]))

print("\n=== 前 25 ===")
for r in rows[:25]:
    print(f'  {r["id"]:>4} {r["freq"]:>4} {r["word"]:<16} {r["meaning"]}')
