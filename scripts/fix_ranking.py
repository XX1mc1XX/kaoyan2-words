# -*- coding: utf-8 -*-
"""修 P0/P1 数据问题：
1. 129 个新词破坏 priority_rank 排序 -> 按 priority + freq 重排并重编
2. priority 格式不统一（"S 必背" vs "S"）-> 统一
3. 新词 forms 为空 -> 从 ECDICT exchange 补
"""
import csv
import io
import json
import re

D = r"c:\my_project\单词\data"
DECKS = ("words", "derivatives", "basic", "insurance")

PRIO_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3}
PRIO_LABEL = {"S": "S 必背", "A": "A 重点", "B": "B 次重点", "C": "C 补充"}

data = {d: json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")) for d in DECKS}

# --- 收集新词，补 forms ---
new_words = {x["word"] for d in DECKS for x in data[d] if x.get("source_tier") == "真题补充"}
ex = {}
if new_words:
    with io.open(D + r"\ecdict.csv", encoding="utf-8", errors="replace", newline="") as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            if len(row) < 11:
                continue
            w = row[0].lower()
            if w in new_words:
                ex[w] = row[10]

filled = 0
for d in DECKS:
    for x in data[d]:
        if x.get("source_tier") != "真题补充":
            continue
        if x.get("forms"):
            continue
        forms = []
        for seg in (ex.get(x["word"]) or "").split("/"):
            if ":" not in seg:
                continue
            k, v = seg.split(":", 1)
            v = v.strip().lower()
            if k.strip() in ("0", "r", "t") or not v.isalpha() or len(v) < 3:
                continue
            if v != x["word"] and v not in forms:
                forms.append(v)
        if forms:
            x["forms"] = forms[:8]
            filled += 1

# --- 统一 priority 文案 + 重排 ---
def prio_key(x):
    p = (x.get("priority") or "C").strip()[:1].upper()
    return PRIO_ORDER.get(p, 3)


for d in DECKS:
    items = data[d]
    # 同优先级内按真题次数降序，其次按原 rank
    items.sort(key=lambda x: (prio_key(x), -(x.get("freq") or 0), x.get("priority_rank") or 0))
    for i, x in enumerate(items, 1):
        x["id"] = i
        x["priority_rank"] = i
        p = (x.get("priority") or "C").strip()[:1].upper()
        x["priority"] = PRIO_LABEL.get(p, "C 补充")

for d in DECKS:
    with io.open(D + "\\" + d + ".json", "w", encoding="utf-8") as f:
        json.dump(data[d], f, ensure_ascii=False, separators=(",", ":"))

print("补 forms 的新词: %d / %d" % (filled, len(new_words)))
for d in DECKS:
    items = data[d]
    top = items[:3]
    print("%-12s %4d 词  前3: %s" % (d, len(items), ", ".join("%s(%s)" % (x["word"], x["priority"][:1]) for x in top)))
