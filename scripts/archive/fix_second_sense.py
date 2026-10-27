# -*- coding: utf-8 -*-
"""修正第二义选取：把「无词性归属」的内容块并入前一个词性，避免同词性重复取。"""
import io
import json
import re
import unicodedata

D = r"c:\my_project\单词\data"
REF = r"c:\my_project\单词\ref\redbook_words.json"
DECKS = ("words", "derivatives", "basic", "insurance")
THRESHOLD = 20

POS_RE = re.compile(
    r"(?<![A-Za-z])(vlink|vt\.?\s*vi\.?|vi\.?\s*vt\.?|vt\.|vi\.|v\.|n\.|adj\.|adv\.|prep\.|conj\.|"
    r"pron\.|num\.|art\.|det\.|int\.|aux\.|link\.|modal\.|a\.|ad\.)\s*", re.I)

RADICAL = {"⺠": "民", "⺟": "母", "⻅": "见", "⻆": "角", "⻉": "贝", "⻋": "车",
           "⻓": "长", "⻔": "门", "⻘": "青", "⻚": "页", "⻛": "风", "⻜": "飞",
           "⻝": "食", "⻢": "马", "⻣": "骨", "⻤": "鬼", "⻥": "鱼", "⻦": "鸟",
           "⻨": "麦", "⻩": "黄", "⻬": "齐", "⻮": "齿", "⻰": "龙"}


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    for k, v in RADICAL.items():
        s = s.replace(k, v)
    return s


def parse_blocks(raw):
    """切成 [(词性, 内容)]，无词性的内容并入前一个词性。"""
    s = norm(raw)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    raw_blocks, last = [], 0
    for m in POS_RE.finditer(s):
        if last < m.start():
            raw_blocks.append((None, s[last:m.start()].strip(" .,，、;；")))
        raw_blocks.append((m.group(1).lower().replace(" ", "").replace(".", ""), ""))
        last = m.end()
    if last < len(s):
        raw_blocks.append((None, s[last:].strip(" .,，、;；")))

    merged = []
    for pos, chunk in raw_blocks:
        if pos:
            merged.append([pos, chunk])
        elif chunk:
            if merged:
                merged[-1][1] = (merged[-1][1] + "；" + chunk).strip("；")
            else:
                merged.append([None, chunk])
    return merged


def first_word(chunk):
    seg = re.split(r"[；;]", chunk)[0]
    for sub in re.split(r"[,，、/]", seg):
        sub = sub.strip(" .,，、 ")
        if sub:
            return sub
    return ""


redbook = {}
for x in json.load(io.open(REF, encoding="utf-8")):
    w = norm(x.get("word") or "").strip().lower()
    if w:
        redbook[w] = x.get("meaning", "")

fixed = []
for d in DECKS:
    p = D + "\\" + d + ".json"
    data = json.load(io.open(p, encoding="utf-8"))
    for x in data:
        if (x.get("freq") or 0) < THRESHOLD:
            continue
        raw = redbook.get(x["word"])
        if not raw:
            continue
        cur = x.get("meaning", "")
        parts = [p.strip() for p in cur.split("、") if p.strip()]
        if len(parts) >= 2:
            # 已有两义，检查是否为同一词性的重复
            blocks = parse_blocks(raw)
            pos_of = {}
            for pos, chunk in blocks:
                w = first_word(chunk) if chunk else ""
                if w:
                    pos_of.setdefault(w, pos)
            p0, p1 = pos_of.get(parts[0]), pos_of.get(parts[1])
            if p0 and p1 and p0 == p1:
                # 同词性，换一个不同词性的
                for pos, chunk in blocks:
                    w = first_word(chunk) if chunk else ""
                    if w and pos and pos != p0 and not (w == parts[0] or parts[0].startswith(w) or w.startswith(parts[0])):
                        fixed.append((x["word"], cur, parts[0] + "、" + w))
                        x["meaning"] = parts[0] + "、" + w
                        break
        else:
            blocks = parse_blocks(raw)
            first = parts[0] if parts else ""
            p0 = None
            for pos, chunk in blocks:
                w = first_word(chunk) if chunk else ""
                if w and (w == first or first.startswith(w) or w.startswith(first)):
                    p0 = pos
                    break
            for pos, chunk in blocks:
                w = first_word(chunk) if chunk else ""
                if w and (pos != p0) and not (w == first or first.startswith(w) or w.startswith(first)) and len(w) <= 8:
                    fixed.append((x["word"], cur, first + "、" + w))
                    x["meaning"] = first + "、" + w
                    break
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

print("修正 %d 条" % len(fixed))
for w, o, n in fixed[:30]:
    print("  %-16s %-20s -> %s" % (w, o, n))
