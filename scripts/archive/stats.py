# -*- coding: utf-8 -*-
"""词表质量体检。"""
import io
import json
import random
import statistics

ROWS = json.load(io.open(r"c:\my_project\单词\data\words.json", encoding="utf-8"))
n = len(ROWS)
withf = [r for r in ROWS if r["forms"]]
nophon = [r for r in ROWS if not r["phonetic"]]
mlen = [len(r["meaning"]) for r in ROWS]

print("词条", n)
print("有考查形式", len(withf), f"{len(withf)/n*100:.0f}%")
print("考查形式总数", sum(len(r["forms"]) for r in ROWS))
print("无音标", len(nophon), f"{len(nophon)/n*100:.0f}%")
print("释义中位长度", statistics.median(mlen), "最大", max(mlen), "超过20字", sum(1 for x in mlen if x > 20))
print("词频区间", ROWS[0]["freq"], "-", ROWS[-1]["freq"])
print("无音标样例", [r["word"] for r in nophon[:12]])

print("\n=== 随机抽样 30（跨全文）===")
random.seed(7)
for r in sorted(random.sample(ROWS, 30), key=lambda x: x["id"]):
    print(f'{r["id"]:>4} {r["word"]:<16}/{r["phonetic"]:<18}/{r["meaning"][:22]:<24}/{" ".join(r["forms"][:5])}')
