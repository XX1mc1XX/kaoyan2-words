# -*- coding: utf-8 -*-
"""回滚到旧规则重建释义，然后只给高频词（freq>=20）补第二个「不同词性」的义项。"""
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

RADICAL = {"⺠": "民", "⺟": "母", "⻅": "见", "⻆": "角", "⻉": "贝", "⻋": "车",
           "⻓": "长", "⻔": "门", "⻘": "青", "⻚": "页", "⻛": "风", "⻜": "飞",
           "⻝": "食", "⻢": "马", "⻣": "骨", "⻤": "鬼", "⻥": "鱼", "⻦": "鸟",
           "⻨": "麦", "⻩": "黄", "⻬": "齐", "⻮": "齿", "⻰": "龙"}


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    for k, v in RADICAL.items():
        s = s.replace(k, v)
    return s


def clean_old(raw):
    """原来的规则：按分号切，每段取第一个词；第一义太短才补第二义。"""
    s = norm(raw)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    s = POS_RE.sub("；", s)
    s = re.sub(r"[；;]+", "；", s)
    s = re.sub(r"\s+", " ", s).strip(" .,，、;；")
    senses = []
    for seg in re.split(r"[；;]", s):
        seg = seg.strip(" .,，、")
        if not seg:
            continue
        for sub in re.split(r"[,，、/]", seg):
            sub = sub.strip(" .,，、 ")
            if sub and not any(sub == p or p.startswith(sub) or sub.startswith(p) for p in senses):
                senses.append(sub)
                break
        if len(senses) >= 3:
            break
    if not senses:
        return s[:14]
    out = senses[:1]
    if len(senses) > 1 and len(senses[0]) <= 3 and len(senses[1]) <= 6:
        out = senses[:2]
    return "、".join(dict.fromkeys(out))


def second_pos_sense(raw, first):
    """从原文里找「和第一义不同词性」的第二个义项。"""
    s = norm(raw)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    # 切成 (词性, 内容块)
    blocks, last = [], 0
    for m in POS_RE.finditer(s):
        chunk = s[last:m.start()].strip(" .,，、;；")
        if chunk:
            blocks.append((None, chunk))
        blocks.append((m.group(1).lower().replace(" ", "").replace(".", ""), ""))
        last = m.end()
    tail = s[last:].strip(" .,，、;；")
    if tail:
        if blocks and blocks[-1][0] is not None:
            blocks[-1] = (blocks[-1][0], tail)
        else:
            blocks.append((None, tail))

    first_pos = None
    for pos, chunk in blocks:
        if not chunk:
            continue
        w = re.split(r"[,，、/]", re.split(r"[；;]", chunk)[0].strip(" .,，、"))[0].strip(" .,，、 ")
        if w and (w == first or first.startswith(w) or w.startswith(first)):
            first_pos = pos
            break

    for pos, chunk in blocks:
        if not chunk or (pos and pos == first_pos):
            continue
        w = re.split(r"[,，、/]", re.split(r"[；;]", chunk)[0].strip(" .,，、"))[0].strip(" .,，、 ")
        if w and w != first and not (first.startswith(w) or w.startswith(first)) and len(w) <= 8:
            return w
    return None


redbook = {}
for x in json.load(io.open(REF, encoding="utf-8")):
    w = norm(x.get("word") or "").strip().lower()
    if w:
        redbook[w] = x.get("meaning", "")

data, need = {}, set()
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
            ecdict[w] = row[3].split("[")[0]   # 去掉 [经] 这类标注尾巴

restored, extended = 0, []
for d in DECKS:
    for x in data[d]:
        raw = redbook.get(x["word"]) or ecdict.get(x["word"])
        if not raw:
            continue
        base = clean_old(raw)
        if base != x.get("meaning"):
            restored += 1
        final = base
        if (x.get("freq") or 0) >= THRESHOLD and "、" not in base:
            extra = second_pos_sense(raw, base)
            if extra:
                final = base + "、" + extra
                extended.append((x["word"], base, final))
        x["meaning"] = final

for d in DECKS:
    with io.open(D + "\\" + d + ".json", "w", encoding="utf-8") as f:
        json.dump(data[d], f, ensure_ascii=False, separators=(",", ":"))

print("恢复旧规则: %d 条  其中高频补充第二义: %d 条" % (restored, len(extended)))
for w, o, n in extended[:25]:
    print("  %-16s %s -> %s" % (w, o, n))
