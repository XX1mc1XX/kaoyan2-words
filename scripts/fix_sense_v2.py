# -*- coding: utf-8 -*-
"""修正 parse_blocks 的词性归属，然后重算高频词的第二义。"""
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
    """词性标记在前、内容在后：内容归属于紧邻其前的词性。"""
    s = norm(raw)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    toks, last = [], 0
    for m in POS_RE.finditer(s):
        if last < m.start():
            toks.append(("C", s[last:m.start()].strip(" .,，、;；")))
        toks.append(("P", m.group(1).lower().replace(" ", "").replace(".", "")))
        last = m.end()
    if last < len(s):
        toks.append(("C", s[last:].strip(" .,，、;；")))

    out, cur = [], None
    for kind, val in toks:
        if kind == "P":
            cur = val
        elif val:
            out.append([cur, val])
    return out


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
        cur = tidy(x.get("meaning", ""))
        parts = [q for q in cur.split("、") if q]
        if not parts:
            continue
        blocks = parse_blocks(raw)
        pos_of = {}
        for pos, chunk in blocks:
            w = first_word(chunk)
            if w and w not in pos_of:
                pos_of[w] = pos

        if len(parts) >= 2:
            p0, p1 = pos_of.get(parts[0]), pos_of.get(parts[1])
            if p0 and p1 and p0 == p1:
                for pos, chunk in blocks:
                    w = first_word(chunk)
                    if w and pos and pos != p0 and not any(
                            w == q or q.startswith(w) or w.startswith(q) for q in parts[:1]):
                        fixed.append((x["word"], cur, parts[0] + "、" + w))
                        x["meaning"] = parts[0] + "、" + w
                        break
            else:
                x["meaning"] = "、".join(parts[:2])
        else:
            p0 = pos_of.get(parts[0])
            for pos, chunk in blocks:
                w = first_word(chunk)
                if w and pos and pos != p0 and not (w == parts[0] or parts[0].startswith(w) or w.startswith(parts[0])) and len(w) <= 8:
                    fixed.append((x["word"], cur, parts[0] + "、" + w))
                    x["meaning"] = parts[0] + "、" + w
                    break
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

print("修正 %d 条" % len(fixed))
for w, o, n in fixed[:25]:
    print("  %-16s %-20s -> %s" % (w, o, n))
print()
for w in ("approach", "offer", "state", "energy", "focus", "call", "know", "become", "social"):
    for d in DECKS:
        hit = [x for x in json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")) if x["word"] == w]
        if hit:
            print("  %-10s %-20s freq=%s" % (w, hit[0]["meaning"], hit[0].get("freq")))
            break
