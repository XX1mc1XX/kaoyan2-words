# -*- coding: utf-8 -*-
"""清理释义残留：词性标记 vlink./link.、中文间空格、重复义项。"""
import io
import json
import re
import unicodedata

D = r"c:\my_project\单词\data"
DECKS = ("words", "derivatives", "basic", "insurance")

RADICAL = {"⺠": "民", "⺟": "母", "⻅": "见", "⻆": "角", "⻉": "贝", "⻋": "车",
           "⻓": "长", "⻔": "门", "⻘": "青", "⻚": "页", "⻛": "风", "⻜": "飞",
           "⻝": "食", "⻢": "马", "⻣": "骨", "⻤": "鬼", "⻥": "鱼", "⻦": "鸟",
           "⻨": "麦", "⻩": "黄", "⻬": "齐", "⻮": "齿", "⻰": "龙"}


def tidy(s):
    s = unicodedata.normalize("NFKC", s or "")
    for k, v in RADICAL.items():
        s = s.replace(k, v)
    # 词性残留
    s = re.sub(r"(?<![A-Za-z])(vlink|link|vt|vi|v|n|adj|adv|prep|conj|pron|num|art|det|int|aux|modal|a|ad)\.\s*",
               "", s, flags=re.I)
    # 中文之间的空格 / 多余空白
    s = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", s)
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" ；;、,，.")
    # 去重复义项
    parts, out = re.split(r"[、；;]", s), []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not any(p == q or q.startswith(p) or p.startswith(q) for q in out):
            out.append(p)
    return "、".join(out)


changed = []
for d in DECKS:
    p = D + "\\" + d + ".json"
    data = json.load(io.open(p, encoding="utf-8"))
    for x in data:
        old = x.get("meaning", "")
        new = tidy(old)
        if new and new != old:
            x["meaning"] = new
            changed.append((x["word"], old, new))
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

print("清理释义 %d 条" % len(changed))
for w, o, n in changed[:30]:
    print("  %-16s %-22s -> %s" % (w, o, n))
print()
for w in ("focus", "become", "offer", "approach", "state", "energy"):
    for d in DECKS:
        for x in json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")):
            if x["word"] == w:
                print("  %-10s %s" % (w, x["meaning"]))
                break
