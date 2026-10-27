# -*- coding: utf-8 -*-
"""构建考研英语二核心词表（仿陶然《2050核心词汇》体例）。

数据源：
  1. 真题词频  data/ky2_freq.json —— 2010-2024 英语二真题 17 套统计出的真实出现次数
  2. 释义      ref/redbook_words.json（红宝书，贴近考试）
  3. 词形/音标 data/ecdict.csv + data/lemma.en.txt
  4. 派生关系  data/derived.json（WordNet）

体例：序号 | 词频(真题出现次数) | 单词 | 释义(只留核心义) | 考查形式
"""
import csv
import io
import json
import os
import re
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
REF = os.path.join(ROOT, "ref")
MAX_FAMILY = 10
MIN_COLLINS = 3
MAX_ROWS = 3000

POS_RE = re.compile(
    r"(?<![A-Za-z])(vt\.?|vi\.?|v\.?|n\.?|adj\.?|adv\.?|prep\.?|conj\.?|pron\.?|num\.?"
    r"|art\.?|det\.?|int\.?|aux\.?|link\.?|modal\.?|suff\.?|pref\.?|abbr\.?"
    r"|pl\.?|sing\.?|comp\.?|sup\.?|a\.|ad\.)\s*",
    re.I,
)

SUFFIXES = [
    "s", "es", "ed", "ing", "er", "ers", "est",
    "ly", "ness", "ful", "fully", "less", "lessly", "lessness",
    "able", "ably", "ability", "ible", "ive", "ively",
    "al", "ally", "ous", "ously", "ity", "tion", "ation", "ition", "sion",
    "ment", "ments", "ance", "ence", "ant", "ent", "ist", "ists",
    "ism", "ize", "ise", "ization", "ship", "hood", "dom", "ish",
]
SAFE_PREFIXES = ["un", "dis", "in", "im", "non", "mis", "over", "under", "en", "em"]

# 试卷说明里的模板词，出现次数再高也不是考点
TEMPLATE_WORDS = set("""
text paragraph sheet direction numbered blank answer question mark essay
translate composition section part passage read choose select option letter
""".split())

# 词源相关但现代语义已分化的，不能折到一起
FOLD_BLACKLIST = {
    ("entail", "tail"), ("banish", "ban"), ("grave", "gravel"),
    ("number", "numb"), ("crew", "crow"), ("sweater", "sweat"),
    ("polish", "pole"), ("comment", "come"), ("income", "come"),
    ("overcome", "come"), ("mistake", "take"), ("intake", "take"),
    ("overtake", "take"), ("undertake", "take"),
    ("feed", "fee"), ("feeding", "fee"), ("fatest", "fate"),
    ("plainest", "plain"), ("plained", "plain"), ("plaining", "plain"),
    ("raring", "rare"), ("evening", "even"), ("liver", "live"),
}

STOPWORDS = set("""
a an the and or but nor so if then than that this these those there here
of to in on at by for with from as into onto upon within without about above
below under over between among through during before after since until while
because though although unless whether
is am are was were be been being do does did done doing have has had having
will would shall should can could may might must
i you he she it we they me him her us them my your his its our their mine
yours hers ours theirs myself yourself himself herself itself ourselves
themselves who whom whose which what when where why how
not no yes very too also just only both each every all some any few many
more most much other another such own same
up down off out again once ever never always often sometimes usually
""".split())

NUMBERS = set("""
zero one two three four five six seven eight nine ten eleven twelve thirteen
fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty
sixty seventy eighty ninety hundred thousand million billion trillion dozen
half quarter percent percentage
first second third fourth fifth sixth seventh eighth ninth tenth eleventh
twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth
nineteenth twentieth thirtieth
""".split())

PROPER_NOUNS = set("""
christmas christian catholic latin christ jew jewish muslim buddhist
monday tuesday wednesday thursday friday saturday sunday
january february march april may june july august september october november december
america american china chinese english britain british france french german germany
japan japanese russia india africa europe asia london paris tokyo
""".split())

# 红宝书源数据混入的「CJK 部首」兼容字符，NFKC 不处理，手工归一
RADICAL_FIX = {
    "⺠": "民", "⺟": "母", "⻅": "见", "⻆": "角", "⻉": "贝", "⻋": "车",
    "⻓": "长", "⻔": "门", "⻘": "青", "⻚": "页", "⻛": "风",
    "⻜": "飞", "⻝": "食", "⻢": "马", "⻣": "骨", "⻤": "鬼",
    "⻥": "鱼", "⻦": "鸟", "⻨": "麦", "⻩": "黄", "⻬": "齐",
    "⻮": "齿", "⻰": "龙",
}


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    for k, v in RADICAL_FIX.items():
        s = s.replace(k, v)
    return s


def clean_meaning(raw):
    """陶然体例：只留一个核心义；若首个义项过短（拿/赢）再补一个。"""
    s = norm(raw)

    def _paren(m):
        inner = m.group(1)
        # 「集中(注意力等)于」如果保留括号内容会粘成「注意力等于」，这类概括性括注直接丢
        if any(k in inner for k in ("等", "某", "之类", "尤指", "通常")):
            return ""
        return inner
    s = re.sub(r"[（(]([^）)]*)[）)]", _paren, s)
    s = s.replace("...", "…").replace("。。。", "…")
    s = re.sub(r"\b(v|n|adj|adv|vt|vi|aux|link)link\.", "；", s, flags=re.I)
    s = POS_RE.sub("；", s)
    s = re.sub(r"[；;]+", "；", s)
    s = re.sub(r"\s+", " ", s).strip(" .,，、;；")
    s = re.sub(r"\s*…\s*", "…", s)
    s = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", s)

    senses = []
    for seg in re.split(r"[；;]", s):
        seg = seg.strip(" .,，、")
        if not seg:
            continue
        taken = 0
        for sub in re.split(r"[,，、/]", seg):
            sub = sub.strip(" .,，、 ")
            if sub.endswith(("使", "将", "把")) and len(sub) > 2:
                sub = sub[:-1]
            if not sub:
                continue
            if not any(sub.startswith(x) or x.startswith(sub) for x in senses):
                senses.append(sub)
                taken += 1
            if taken >= 2:
                break
        if len(senses) >= 3:
            break

    if not senses:
        return s[:14]
    # 一个义项足够，除非它太短（「拿」「赢」这种）才补第二个，且第二个也不能太长
    out = senses[:1]
    if len(senses) > 1 and len(senses[0]) <= 3 and len(senses[1]) <= 6:
        out = senses[:2]
    return "、".join(dict.fromkeys(out))


def load_redbook():
    items = json.load(io.open(os.path.join(REF, "redbook_words.json"), encoding="utf-8"))
    out = {}
    for it in items:
        w = norm(it.get("word") or "").strip().lower()
        if not w or not w.isalpha() or " " in w:
            continue
        out[w] = {"word": w, "raw_meaning": norm(it.get("meaning", ""))}
    for v in out.values():
        v["core"] = clean_meaning(v["raw_meaning"])
    return out


def load_ky2_freq():
    return json.load(io.open(os.path.join(DATA, "ky2_freq.json"), encoding="utf-8"))


def load_lemma():
    out = {}
    with io.open(os.path.join(DATA, "lemma.en.txt"), encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";") or "->" not in line:
                continue
            left, right = line.split("->", 1)
            lemma = left.split("/")[0].strip().lower()
            for form in right.split(","):
                form = form.strip().lower()
                if form.isalpha() and form != lemma:
                    out.setdefault(form, lemma)
    return out


def load_ecdict(wanted):
    rec, vocab = {}, set()
    with io.open(os.path.join(DATA, "ecdict.csv"), encoding="utf-8", errors="replace", newline="") as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            if len(row) < 11:
                continue
            w = row[0].lower()
            vocab.add(w)
            if w in wanted:
                rec[w] = {
                    "phonetic": row[1].strip(),
                    "definition": row[2].strip().lower(),
                    "trans": row[3].strip(),
                    "collins": row[5].strip(),
                    "oxford": row[6].strip(),
                    "tag": row[7].strip(),
                    "bnc": row[8].strip(),
                    "frq": row[9].strip(),
                    "exchange": row[10].strip(),
                }
    return rec, vocab


def load_derived():
    p = os.path.join(DATA, "derived.json")
    if not os.path.exists(p):
        return {}
    return {k: set(v) for k, v in json.load(io.open(p, encoding="utf-8")).items()}


def freq_rank(rec):
    vals = []
    for key in ("frq", "bnc"):
        try:
            v = int(rec.get(key) or 0)
            if v > 0:
                vals.append(v)
        except ValueError:
            pass
    return min(vals) if vals else 999999


def frq_only(rec):
    """只用当代语料库排名。bnc 排名偏早，会把 development(frq448/bnc200) 误判成极常见基础词。"""
    try:
        v = int(rec.get("frq") or 0)
        return v if v > 0 else 999999
    except ValueError:
        return 999999


def parse_exchange(ex):
    out = {}
    for seg in (ex or "").split("/"):
        if ":" in seg:
            k, v = seg.split(":", 1)
            v = v.strip().lower()
            if v.isalpha() and len(v) > 2:
                out.setdefault(k.strip(), v)
    return out


def inflections(w):
    """屈折变化候选。safe 可直接收；risky（比较级/最高级）易撞独立词。"""
    safe = [w + "s"]
    if w.endswith(("s", "x", "z", "ch", "sh", "o")):
        safe.append(w + "es")
    if w.endswith("y") and len(w) > 2 and w[-2] not in "aeiou":
        safe += [w[:-1] + "ies", w[:-1] + "ied"]
        risky = [w[:-1] + "ier", w[:-1] + "iest"]
    else:
        safe += [w + "ed", w + "ing"]
        risky = [w + "er", w + "est"]
    if w.endswith("e"):
        safe += [w + "d", w[:-1] + "ing"]
        risky = [w[:-1] + "er", w[:-1] + "est"]
    return safe, risky


def derive_candidates(w):
    """母词可能派生出的词形（用于捞表外派生词）。"""
    stems = {w}
    if w.endswith("e"):
        stems.add(w[:-1])
    if w.endswith("y"):
        stems.add(w[:-1] + "i")
        stems.add(w[:-1])
    out = set()
    for st in stems:
        for suf in SUFFIXES:
            if suf not in ("s", "es", "ed", "ing", "est", "ers"):
                out.add(st + suf)
    for pre in SAFE_PREFIXES:
        out.add(pre + w)
    out.discard(w)
    return out


def main():
    print("== 读数据 ==")
    words = load_redbook()
    kfreq = load_ky2_freq()
    form2lemma = load_lemma()
    derived = load_derived()
    rec, vocab = load_ecdict(set(words) | set(kfreq))
    print(f"   红宝书 {len(words)}  真题词目 {len(kfreq)}  ECDICT命中 {len(rec)}")

    # ---------- 选词：只收真题真出现过的词 ----------
    kept = {}
    dropped = {"proper": 0, "stop": 0, "short": 0, "no_ecdict": 0, "not_syllabus": 0, "middle": 0, "rare": 0}
    middle_out = []
    for lem, info in kfreq.items():
        cnt = info.get("count", 0)
        if info.get("proper"):
            dropped["proper"] += 1
            continue
        if lem in STOPWORDS or lem in NUMBERS or lem in PROPER_NOUNS or lem in TEMPLATE_WORDS:
            dropped["stop"] += 1
            continue
        if len(lem) <= 2 or "'" in lem or "-" in lem:
            dropped["short"] += 1
            continue
        r = rec.get(lem)
        if not r:
            dropped["no_ecdict"] += 1
            continue
        tag = set(r.get("tag", "").split())
        col = int(r.get("collins") or 0)
        in_rb = lem in words
        is_ky = "ky" in tag
        # 必须在考研大纲词表 / 红宝书 / 柯林斯 3 星以上
        if not (in_rb or is_ky or col >= MIN_COLLINS):
            dropped["not_syllabus"] += 1
            continue
        # 初中/高中就该会的基础词（ECDICT 标签只挂了 zk/gk，且通用语料里极常见）
        if (tag & {"zk", "gk"}) and not (tag & {"cet4", "cet6", "ky"}) and frq_only(r) <= 300:
            middle_out.append((cnt, lem, r.get("tag", ""), col))
            dropped["middle"] += 1
            continue
        # 只出现一次且不是大纲词的生僻长尾
        if cnt <= 1 and not is_ky and col < MIN_COLLINS:
            dropped["rare"] += 1
            continue
        meaning = clean_meaning(words[lem]["raw_meaning"]) if in_rb else clean_meaning(r.get("trans", ""))
        kept[lem] = {
            "word": lem,
            "phonetic": r.get("phonetic", ""),
            "meaning": meaning,
            "count": cnt,
            "collins": col,
            "tag": r.get("tag", ""),
            "in_redbook": in_rb,
        }

    print(f"   入选 {len(kept)}   剔除 {dropped}")
    print("   -- 被当成中学词剔除的（按真题次数，排查误杀）--")
    for cnt, w, tg, cl in sorted(middle_out, reverse=True)[:40]:
        print(f'      {cnt:>4} {w:<16} tag={tg:<28} collins={cl}')

    rows = sorted(kept.values(), key=lambda x: (-x["count"], x["word"]))
    if len(rows) > MAX_ROWS:
        rows = rows[:MAX_ROWS]
    heads = {r["word"] for r in rows}

    # ---------- 考查形式：同族但不在核心表里的变形/派生 ----------
    # 先抓全库派生候选，再逐一做语义校验
    all_c = set()
    for r in rows:
        all_c |= derive_candidates(r["word"])
    extra = {}
    with io.open(os.path.join(DATA, "ecdict.csv"), encoding="utf-8", errors="replace", newline="") as f:
        rr = csv.reader(f)
        next(rr, None)
        for row in rr:
            if len(row) < 11:
                continue
            w = row[0].lower()
            if w in all_c:
                extra[w] = (row[2].strip().lower(), freq_rank({"frq": row[9], "bnc": row[8]}))

    for r in rows:
        h = r["word"]
        ex = parse_exchange(rec.get(h, {}).get("exchange", ""))
        ex_forms = [v for k, v in ex.items() if k not in ("0", "r", "t")]
        safe, risky = inflections(h)
        infl = [c for c in safe + risky if c in vocab and form2lemma.get(c) == h and c not in heads]
        found = []
        for c in derive_candidates(h):
            if c in heads or c in infl:
                continue
            info = extra.get(c)
            if not info or not info[0] or info[1] > 15000:
                continue
            if not re.search(r"\b" + re.escape(h) + r"\b", info[0]):
                continue
            found.append((info[1], c))
        found.sort()
        cand = [c for _, c in found] + ex_forms + infl
        merged = [c for c in dict.fromkeys(cand)
                  if c not in heads and c != h and (c, h) not in FOLD_BLACKLIST]
        r["forms"] = merged[:MAX_FAMILY]

    for i, r in enumerate(rows, 1):
        r["id"] = i

    os.makedirs(DATA, exist_ok=True)
    out_rows = [{"id": r["id"], "word": r["word"], "phonetic": r["phonetic"],
                 "meaning": r["meaning"], "forms": r["forms"], "freq": r["count"],
                 "collins": r["collins"], "tag": r["tag"]} for r in rows]
    json.dump(out_rows, io.open(os.path.join(DATA, "words.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    with io.open(os.path.join(DATA, "words.csv"), "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["序号", "真题次数", "单词", "音标", "释义", "考查形式", "柯林斯", "标签"])
        for r in out_rows:
            wr.writerow([r["id"], r["freq"], r["word"], r["phonetic"], r["meaning"],
                         ", ".join(r["forms"]), r["collins"], r["tag"]])

    print(f"\n== 结果 ==")
    print(f"词条 {len(rows)}  带考查形式 {sum(1 for r in rows if r['forms'])}  "
          f"覆盖词形 {len(rows) + sum(len(r['forms']) for r in rows)}")
    print(f"词频区间 {rows[0]['count']} - {rows[-1]['count']}")
    print("\n-- 前 40 --")
    for r in rows[:40]:
        print(f'{r["id"]:>4} {r["count"]:>4} {r["word"]:<16} {r["meaning"][:18]:<20} {" ".join(r["forms"][:6])}')
    print("\n-- 尾部 15 --")
    for r in rows[-15:]:
        print(f'{r["id"]:>4} {r["count"]:>4} {r["word"]:<16} {r["meaning"][:18]}')


if __name__ == "__main__":
    main()
