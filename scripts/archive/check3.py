# -*- coding: utf-8 -*-
"""第三轮检查：真题版词表。"""
import io
import json
import statistics

ROWS = json.load(io.open(r"c:\my_project\单词\data\words.json", encoding="utf-8"))
BY = {r["word"]: r for r in ROWS}
print(f"词条 {len(ROWS)}")

print("\n=== 派生词是否独立成条（不再被母词吞）===")
for w in ("statement", "controversial", "controversy", "development", "develop",
          "national", "nation", "professional", "profession", "competition", "compete",
          "government", "govern", "employment", "employ"):
    r = BY.get(w)
    print(f'  {w:<16} {"在表内 #" + str(r["id"]) + " 出现" + str(r["freq"]) + "次" if r else "缺失"}')

print("\n=== 释义长度 ===")
lens = [len(r["meaning"]) for r in ROWS]
print(f"  中位 {statistics.median(lens)}  最大 {max(lens)}  >12字 {sum(1 for x in lens if x > 12)} 条")
print("  最长 10 条:")
for r in sorted(ROWS, key=lambda x: -len(x["meaning"]))[:10]:
    print(f'    {r["word"]:<16} {r["meaning"]}')

print("\n=== 释义抽样 30 ===")
import random
random.seed(11)
for r in sorted(random.sample(ROWS, 30), key=lambda x: x["id"]):
    print(f'  {r["id"]:>4} {r["freq"]:>4} {r["word"]:<16} {r["meaning"]:<18} {" ".join(r["forms"][:4])}')

print("\n=== 词频分布 ===")
for lo, hi in [(50, 9999), (30, 49), (20, 29), (10, 19), (5, 9), (3, 4), (2, 2), (1, 1)]:
    n = sum(1 for r in ROWS if lo <= r["freq"] <= hi)
    print(f'  {lo:>3}-{hi:<5} {n:>5}')
print(f"  区间 {ROWS[0]['freq']} - {ROWS[-1]['freq']}")
