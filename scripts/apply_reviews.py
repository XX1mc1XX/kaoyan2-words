# -*- coding: utf-8 -*-
"""应用两轮核对结果：删噪声 forms、删词根词条、补 129 个真题漏收词。"""
import csv
import io
import json

D = r"c:\my_project\单词\data"
DECKS = ("words", "derivatives", "basic", "insurance")
data = {d: json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")) for d in DECKS}

# ---------- 1. 删噪声 forms ----------
review = json.load(io.open(D + r"\forms_review.json", encoding="utf-8"))
to_delete = {tuple(p) for p in review["delete"]}
# 人工追加：同源但现代语义已分化，留着会混淆
to_delete |= {("content", "contain"), ("respect", "respectively"),
              ("fair", "faired"), ("fair", "fairing")}

removed_forms = 0
for d in DECKS:
    for x in data[d]:
        forms = x.get("forms") or []
        kept = [f for f in forms if (x["word"], f) not in to_delete]
        if len(kept) != len(forms):
            removed_forms += len(forms) - len(kept)
            x["forms"] = kept

# ---------- 2. 删词根当词条的（clar -> 让 clarity 独立）----------
root_entries = {"clar"}
dropped_entries = []
for d in DECKS:
    before = len(data[d])
    data[d] = [x for x in data[d] if x["word"] not in root_entries]
    if len(data[d]) != before:
        dropped_entries.append(d)

# ---------- 3. 补 129 个真题漏收词 ----------
gap = json.load(io.open(D + r"\gap_review.json", encoding="utf-8"))
add_list = gap["add"]
have = {x["word"] for d in DECKS for x in data[d]}

# ECDICT 取音标/释义备用
ecdict = {}
need = {a["word"] for a in add_list} - have
with io.open(D + r"\ecdict.csv", encoding="utf-8", errors="replace", newline="") as f:
    r = csv.reader(f)
    next(r, None)
    for row in r:
        if len(row) < 11:
            continue
        w = row[0].lower()
        if w in need:
            ecdict[w] = {"phonetic": row[1], "trans": row[3], "forms": row[10]}

ky1 = {}
try:
    k = json.load(io.open(D + r"\ky1_freq.json", encoding="utf-8"))
    ky1 = k.get("words", k)
except Exception:
    pass


def prio(cnt):
    if cnt >= 20:
        return "S"
    if cnt >= 10:
        return "A"
    return "B"


added = []
insurance = data["insurance"]
next_id = max(x["id"] for x in insurance) + 1
base_rank = max(x.get("priority_rank", 0) for x in insurance) + 1

for item in add_list:
    w = item["word"]
    if w in have:
        continue
    e = ecdict.get(w, {})
    e1 = ky1.get(w, {}) if isinstance(ky1.get(w), dict) else {}
    cnt = item.get("count", 0)
    insurance.append({
        "id": next_id,
        "word": w,
        "family": "",
        "meaning": item.get("meaning") or (e.get("trans", "").split("\n")[0][:20]),
        "forms": [],
        "freq": cnt,
        "coverage": 0,
        "en1_freq": e1.get("count", 0),
        "en1_coverage": e1.get("coverage", 0),
        "weighted_coverage": 0,
        "book_rank": 0,
        "source_tier": "真题补充",
        "band": "真题补漏",
        "priority": prio(cnt),
        "priority_rank": base_rank,
    })
    next_id += 1
    base_rank += 1
    added.append(w)

# ---------- 4. 重新编号 ----------
for d in DECKS:
    for i, x in enumerate(data[d], 1):
        x["id"] = i
    with io.open(D + "\\" + d + ".json", "w", encoding="utf-8") as f:
        json.dump(data[d], f, ensure_ascii=False, separators=(",", ":"))

print("删除噪声 forms: %d 条" % removed_forms)
print("删除词根词条: %s" % (dropped_entries or "无"))
print("补入新词: %d 个" % len(added))
print("各库词数:", {d: len(data[d]) for d in DECKS})
print("总计:", sum(len(data[d]) for d in DECKS))
