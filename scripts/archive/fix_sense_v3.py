# -*- coding: utf-8 -*-
"""按词性大类（v/n/adj/adv）比较，修正高频词第二义；同时清理空格。"""
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


def pos_group(p):
    """vt/vi/v/vivt/vlink 都算动词。"""
    if not p:
        return None
    if "v" in p:
        return "v"
    if p.startswith("n"):
        return "n"
    if p.startswith("adj") or p == "a":
        return "adj"
    if p.startswith("adv") or p == "ad":
        return "adv"
    return p


def parse_blocks(raw):
    s = norm(raw)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    toks, last = [], 0
    for m in POS_RE.finditer(s):
        if last < m.start():
            toks.append(("C", s[last:m.start()].strip(" .,，、;；")))
        toks.append(("P", pos_group(m.group(1).lower().replace(" ", "").replace(".", ""))))
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
            return tidy(sub)
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
        x["meaning"] = tidy(x.get("meaning", ""))
        if (x.get("freq") or 0) < THRESHOLD:
            continue
        raw = redbook.get(x["word"])
        if not raw:
            continue
        parts = [q for q in x["meaning"].split("、") if q]
        if not parts:
            continue
        blocks = parse_blocks(raw)
        pos_of = {}
        for pos, chunk in blocks:
            w = first_word(chunk)
            if w and w not in pos_of:
                pos_of[w] = pos

        if len(parts) >= 2:
            if pos_of.get(parts[0]) and pos_of.get(parts[0]) == pos_of.get(parts[1]):
                for pos, chunk in blocks:
                    w = first_word(chunk)
                    if w and pos and pos != pos_of.get(parts[0]) and not any(
                            w == q or q.startswith(w) or w.startswith(q) for q in parts[:1]) and len(w) <= 8:
                        new = parts[0] + "、" + w
                        if new != x["meaning"]:
                            fixed.append((x["word"], x["meaning"], new))
                            x["meaning"] = new
                        break
        else:
            p0 = pos_of.get(parts[0])
            for pos, chunk in blocks:
                w = first_word(chunk)
                if w and pos and pos != p0 and not (w == parts[0] or parts[0].startswith(w) or w.startswith(parts[0])) and len(w) <= 8:
                    new = parts[0] + "、" + w
                    fixed.append((x["word"], x["meaning"], new))
                    x["meaning"] = new
                    break
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

print("修正 %d 条" % len(fixed))
for w, o, n in fixed[:25]:
    print("  %-16s %-20s -> %s" % (w, o, n))
print()
for w in ("approach", "offer", "state", "energy", "focus", "call", "know", "become", "social", "support"):
    for d in DECKS:
        hit = [x for x in json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")) if x["word"] == w]
        if hit:
            print("  %-10s %-20s freq=%s" % (w, hit[0]["meaning"], hit[0].get("freq")))
            break
