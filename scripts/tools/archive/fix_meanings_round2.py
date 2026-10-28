# -*- coding: utf-8 -*-
"""修复释义：删 abbr. 词根碎片、清换行残留、补空释义、清 ... 前后空格。"""
import io
import json
import re

D = r"c:\my_project\单词\data"
DECKS = ("words", "derivatives", "basic", "insurance")

# abbr./comb. 开头的都是词根碎片或缩写，不是正经词条
ABBR_FRAGMENTS = {"bor", "cas", "caut", "cens", "chem", "cred", "theat", "tra",
                  "trai", "typ", "uni", "vers", "vit", "viv", "volunt", "cret", "separately"}

FILL = {
    "separately": "分别地",
}

data = {d: json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")) for d in DECKS}

removed = []
for d in DECKS:
    before = len(data[d])
    keep = []
    for x in data[d]:
        m = (x.get("meaning") or "").strip()
        if x["word"] in ABBR_FRAGMENTS or m.startswith(("abbr.", "comb.")):
            removed.append((x["word"], m[:24]))
            continue
        keep.append(x)
    data[d] = keep

cleaned = []
for d in DECKS:
    for x in data[d]:
        old = x.get("meaning") or ""
        m = old.replace("\\n", "\n")
        # 只留第一段（换行前），去掉后面的词性赘述
        m = m.split("\n")[0].strip()
        # 清理 ... 前后空格
        m = re.sub(r"\s*\.\.\.\s*", "...", m)
        m = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", m)
        m = re.sub(r"\s+", " ", m).strip(" ；;、,，.")
        if not m:
            m = FILL.get(x["word"], "")
        if m and m != old:
            cleaned.append((x["word"], old, m))
        x["meaning"] = m

for d in DECKS:
    for i, x in enumerate(data[d], 1):
        x["id"] = i
    with io.open(D + "\\" + d + ".json", "w", encoding="utf-8") as f:
        json.dump(data[d], f, ensure_ascii=False, separators=(",", ":"))

print("删除碎片/缩写 %d 个:" % len(removed))
for w, m in removed:
    print("  %-14s %s" % (w, m))
print("\n清理释义 %d 条，示例:" % len(cleaned))
for w, o, n in cleaned[:20]:
    print("  %-16s %-32s -> %s" % (w, o[:32], n))
print("\n各库词数:", {d: len(data[d]) for d in DECKS}, "总计", sum(len(data[d]) for d in DECKS))
