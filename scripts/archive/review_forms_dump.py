# -*- coding: utf-8 -*-
"""导出全部 forms 疑似配对及完整释义，供人工逐条核对。只读，不修改数据。"""
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
            defs[w] = re.sub(r"\s+", " ", row[2].lower()).strip()

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
            short, long_ = (ha, ta) if len(ha) <= len(ta) else (ta, ha)
            overlap = any(short[i:i + 2] in long_ for i in range(len(short) - 1))
            in_def = (head in td) if td else False
            if not overlap and not in_def:
                suspect.append((head, fm, ha, ta, hd, td, d))

out = io.open(r"c:\my_project\单词\scripts\review_forms_dump.txt", "w", encoding="utf-8")
out.write("checked=%d suspect=%d\n" % (checked, len(suspect)))
for i, (head, fm, ha, ta, hd, td, d) in enumerate(suspect, 1):
    out.write("%03d\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" % (i, head, fm, d, ha[:40], ta[:40], hd[:100], td[:100]))
out.close()
print("checked=%d suspect=%d -> scripts/review_forms_dump.txt" % (checked, len(suspect)))
