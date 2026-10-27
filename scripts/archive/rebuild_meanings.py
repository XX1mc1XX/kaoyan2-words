# -*- coding: utf-8 -*-
"""按方案 B 重建释义：
- 先按词性分段（vt./vi./n./adj. ...），每种词性取第一个义项的第一个词
- 真题 >= 20 次的词保留 2 个（优先不同词性），其余 1 个
"""
import csv
import io
import json
import re
import unicodedata

D = r"c:\my_project\单词\data"
REF = r"c:\my_project\单词\ref\redbook_words.json"
DECKS = ("words", "derivatives", "basic", "insurance")
THRESHOLD = 20

POS_RE = re.compile(
    r"(?<![A-Za-z])(vt\.?\s*vi\.?|vi\.?\s*vt\.?|vt\.|vi\.|v\.|n\.|adj\.|adv\.|prep\.|conj\.|"
    r"pron\.|num\.|art\.|det\.|int\.|aux\.|link\.|modal\.|a\.|ad\.)\s*", re.I)
CJK = re.compile(r"[一-鿿]")

RADICAL = {"⺠": "民", "⺟": "母", "⻅": "见", "⻆": "角", "⻉": "贝", "⻋": "车",
           "⻓": "长", "⻔": "门", "⻘": "青", "⻚": "页", "⻛": "风", "⻜": "飞",
           "⻝": "食", "⻢": "马", "⻣": "骨", "⻤": "鬼", "⻥": "鱼", "⻦": "鸟",
           "⻨": "麦", "⻩": "黄", "⻬": "齐", "⻮": "齿", "⻰": "龙"}


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    for k, v in RADICAL.items():
        s = s.replace(k, v)
    return s


def first_word_of(seg):
    seg = seg.strip(" .,，、;；:：")
    if not seg:
        return ""
    for sub in re.split(r"[,，、/]", seg):
        sub = sub.strip(" .,，、 ()（）")
        if sub:
            return sub
    return ""


def build_meaning(raw, n):
    """按词性分段，每段取第一个义项的第一个词。"""
    s = norm(raw)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    # 用词性标记切段
    parts = []
    last = 0
    for m in POS_RE.finditer(s):
        if m.start() > last:
            chunk = s[last:m.start()].strip(" .,，、;；")
            if chunk:
                parts.append((None, chunk))
        parts.append((m.group(1).lower().replace(" ", "").replace(".", ""), ""))
        last = m.end()
    tail = s[last:].strip(" .,，、;；")
    if tail:
        # 接到最后一个词性上
        if parts and parts[-1][0] is not None:
            parts[-1] = (parts[-1][0], tail)
        else:
            parts.append((None, tail))

    picked, seen_pos = [], set()
    for pos, chunk in parts:
        if not chunk:
            continue
        w = first_word_of(re.split(r"[；;]", chunk)[0])
        if not w or any(w == p or p.startswith(w) or w.startswith(p) for p in picked):
            continue
        if pos and pos in seen_pos:
            continue
        picked.append(w)
        if pos:
            seen_pos.add(pos)
        if len(picked) >= n:
            break

    if not picked:
        return s[:14]
    return "、".join(picked[:n])


# 数据源
redbook = {}
for x in json.load(io.open(REF, encoding="utf-8")):
    w = norm(x.get("word") or "").strip().lower()
    if w:
        redbook[w] = x.get("meaning", "")

need = set()
data = {}
for d in DECKS:
    data[d] = json.load(io.open(D + "\\" + d + ".json", encoding="utf-8"))
    for x in data[d]:
        need.add(x["word"])

ecdict = {}
with io.open(D + r"\ecdict.csv", encoding="utf-8", errors="replace", newline="") as f:
    r = csv.reader(f)
    next(r, None)
    for row in r:
        if len(row) < 11:
            continue
        w = row[0].lower()
        if w in need and w not in redbook:
            ecdict[w] = row[3]

changed = []
for d in DECKS:
    for x in data[d]:
        raw = redbook.get(x["word"]) or ecdict.get(x["word"])
        if not raw:
            continue
        n = 2 if (x.get("freq") or 0) >= THRESHOLD else 1
        new = build_meaning(raw, n)
        if new and new != x.get("meaning"):
            changed.append((x["word"], x.get("meaning", ""), new))
            x["meaning"] = new

for d in DECKS:
    with io.open(D + "\\" + d + ".json", "w", encoding="utf-8") as f:
        json.dump(data[d], f, ensure_ascii=False, separators=(",", ":"))

print("更新释义 %d 条" % len(changed))
for w, o, n in changed[:25]:
    print("  %-16s %s  ->  %s" % (w, o, n))
