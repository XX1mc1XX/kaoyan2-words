# -*- coding: utf-8 -*-
"""用中英释义重叠度找出 forms 里语义无关的配对（如 create->creature）。"""
import csv
import io
import json
import re

D = r"c:\my_project\单词\data"
DECKS = ("words", "derivatives", "basic", "insurance")
CJK = re.compile(r"[一-鿿]")

data = {d: json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")) for d in DECKS}

need = set()
for d in DECKS:
    for x in data[d]:
        need.add(x["word"])
        need.update(x.get("forms") or [])

trans, defs = {}, {}
with io.open(D + r"\ecdict.csv", encoding="utf-8", errors="replace", newline="") as f:
    r = csv.reader(f)
    next(r, None)
    for row in r:
        if len(row) < 11:
            continue
        w = row[0].lower()
        if w in need:
            trans[w] = "".join(CJK.findall(row[3]))
            defs[w] = row[2].lower()

suspect = []
checked = 0
for d in DECKS:
    for x in data[d]:
        head = x["word"]
        ha, hd = trans.get(head, ""), defs.get(head, "")
        for fm in (x.get("forms") or []):
            ta, td = trans.get(fm, ""), defs.get(fm, "")
            if not ha or not ta:
                continue
            checked += 1
            # 中文释义有 2 字连续重叠 或 英文释义互相包含 -> 判为相关
            short, long_ = (ha, ta) if len(ha) <= len(ta) else (ta, ha)
            overlap = any(short[i:i + 2] in long_ for i in range(len(short) - 1))
            in_def = (head in td) if td else False
            if not overlap and not in_def:
                suspect.append((head, fm, ha[:10], ta[:10], d))

print("可校验配对 %d，疑似语义无关 %d" % (checked, len(suspect)))
print("%-16s %-16s %-12s %-12s %s" % ("主词", "form", "主词义", "form义", "库"))
for head, fm, ha, ta, d in suspect[:50]:
    print("%-16s %-16s %-12s %-12s %s" % (head, fm, ha, ta, d))
