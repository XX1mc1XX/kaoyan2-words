# -*- coding: utf-8 -*-
"""最终收口释义：
- freq < 20 只留 1 个义项
- freq >= 20 保留最多 2 个，且尽量不同词性
- 最后统一清理空格/词性残留/重复
"""
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


def tidy(s):
    s = norm(s)
    s = re.sub(r"(?<![A-Za-z])(vlink|link|vt|vi|v|n|adj|adv|prep|conj|pron|num|art|det|int|aux|modal|a|ad)\.\s*",
               "", s, flags=re.I)
    s = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ；;、,，.")
    out = []
    for p in re.split(r"[、；;]", s):
        p = p.strip()
        if p and not any(p == q or q.startswith(p) or p.startswith(q) for q in out):
            out.append(p)
    return "、".join(out)


def parse_blocks(raw):
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
    return [b for b in merged if b[1]]


def first_word(chunk):
    for sub in re.split(r"[,，、/]", re.split(r"[；;]", chunk)[0]):
        sub = sub.strip(" .,，、 ")
        if sub:
            return sub
    return ""


redbook = {}
for x in json.load(io.open(REF, encoding="utf-8")):
    w = norm(x.get("word") or "").strip().lower()
    if w:
        redbook[w] = x.get("meaning", "")

stats = {"trim1": 0, "keep2": 0, "fixed_pos": 0}
for d in DECKS:
    p = D + "\\" + d + ".json"
    data = json.load(io.open(p, encoding="utf-8"))
    for x in data:
        cur = tidy(x.get("meaning", ""))
        parts = [q for q in cur.split("、") if q]
        if not parts:
            continue
        high = (x.get("freq") or 0) >= THRESHOLD
        if not high:
            if len(parts) > 1:
                stats["trim1"] += 1
            x["meaning"] = parts[0]
            continue
        # 高频：保留 1-2 个，优先不同词性
        if len(parts) >= 2:
            raw = redbook.get(x["word"])
            if raw:
                blocks = parse_blocks(raw)
                pos_of = {}
                for pos, chunk in blocks:
                    w = first_word(chunk)
                    if w and w not in pos_of:
                        pos_of[w] = pos
                if pos_of.get(parts[0]) and pos_of.get(parts[0]) == pos_of.get(parts[1]):
                    for pos, chunk in blocks:
                        w = first_word(chunk)
                        if w and pos and pos != pos_of.get(parts[0]) and not any(
                                w == q or q.startswith(w) or w.startswith(q) for q in parts[:1]):
                            parts[1] = w
                            stats["fixed_pos"] += 1
                            break
            x["meaning"] = "、".join(parts[:2])
        else:
            stats["keep2"] += 1
            x["meaning"] = parts[0]
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

print(stats)
for w in ("approach", "offer", "state", "energy", "focus", "call", "know", "become", "social"):
    for d in DECKS:
        hit = [x for x in json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")) if x["word"] == w]
        if hit:
            print("  %-10s %-20s freq=%s" % (w, hit[0]["meaning"], hit[0].get("freq")))
            break
