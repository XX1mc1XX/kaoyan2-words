# -*- coding: utf-8 -*-
"""只读数据质量检查：重复、forms 冲突、freq 一致性、优先级、异常"""
import json, csv, re, random, sys
from collections import Counter, defaultdict

BASE = r"C:\my_project\单词\data"
def load(n):
    return json.load(open(f"{BASE}\\{n}.json", encoding="utf-8"))

words = load("words"); deriv = load("derivatives"); basic = load("basic"); ins = load("insurance")
ky2 = load("ky2_freq")
K = ky2["words"]
libs = {"words": words, "derivatives": deriv, "basic": basic, "insurance": ins}
out = []
P = lambda *a: out.append(" ".join(str(x) for x in a))

# ---------- 1 跨库重复 ----------
loc = defaultdict(set)
entry = {}
for name, arr in libs.items():
    for e in arr:
        w = e["word"].strip().lower()
        loc[w].add(name); entry.setdefault((w), e)
dups = {w: s for w, s in loc.items() if len(s) > 1}
P("=== 1 跨库重复 ===")
P("总唯一词", len(loc), "重复词", len(dups))
P("组合分布", dict(Counter(tuple(sorted(s)) for s in dups.values())))
# 各库内重复
for name, arr in libs.items():
    c = Counter(e["word"].strip().lower() for e in arr)
    d = {k: v for k, v in c.items() if v > 1}
    P(f"库内重复 {name}:", len(d), list(d.items())[:10])
P("重复示例:", list(dups.items())[:15])

# ---------- 2 forms 与主词冲突 ----------
P("\n=== 2 forms 里的词本身是主词 ===")
allwords = set(loc)
hits = []
for name, arr in libs.items():
    for e in arr:
        for f in (e.get("forms") or []):
            f2 = f.strip().lower()
            if f2 in allwords and f2 != e["word"].lower():
                where = loc[f2]
                hits.append((name, e["word"], f, sorted(where)))
P("冲突总数", len(hits), "涉及词条", len({h[1] for h in hits}))
P("示例:", hits[:20])
# forms 是否只是简单变形（粗筛）
def plausible(base, f):
    b, f = base.lower(), f.lower()
    if not f.startswith(b[:max(2, len(b)-3)]):
        return False
    return True
bad = [(n, e["word"], f, e["meaning"]) for n, arr in libs.items() for e in arr for f in (e.get("forms") or []) if not plausible(e["word"], f)]
P("疑似非该词变形的 forms", len(bad), bad[:20])

# ---------- 3 freq 一致性 ----------
P("\n=== 3 freq vs ky2 count ===")
random.seed(42)
pool = [e for arr in libs.values() for e in arr]
samp = random.sample(pool, 20)
for e in samp:
    w = e["word"].lower()
    P(f"{w:18s} freq={e.get('freq')} ky2count={K.get(w,{}).get('count','MISSING')}")
# 全量统计
mismatch = 0; covered = 0; missing = 0
for e in pool:
    w = e["word"].lower()
    if w in K:
        covered += 1
        if e.get("freq") != K[w]["count"]: mismatch += 1
    else:
        missing += 1
P(f"全量: 有对应lemma {covered}, 其中freq不一致 {mismatch} ({mismatch/max(covered,1):.1%}), 真题无此lemma {missing}")
# 不一致示例
ex = [(e["word"], e.get("freq"), K[e["word"].lower()]["count"]) for e in pool if e["word"].lower() in K and e.get("freq") != K[e["word"].lower()]["count"]]
P("不一致示例", ex[:15])

# ---------- 5 优先级 ----------
P("\n=== 5 优先级 ===")
for name, arr in libs.items():
    P(name, dict(Counter(e.get("priority","?").split()[0] for e in arr)))
    ranks = [e.get("priority_rank") for e in arr]
    if all(isinstance(r,int) for r in ranks):
        c = Counter(ranks)
        rr = sorted(ranks)
        P(f"  rank min={rr[0]} max={rr[-1]} n={len(ranks)} 重复={sum(v-1 for v in c.values() if v>1)} 缺失={rr[-1]-rr[0]+1-len(set(ranks))}")
        # 与顺序一致性
        P("  rank 是否随数组递增:", ranks == sorted(ranks))
# S 级抽样（words+deriv）
S = [e for e in words+deriv if e.get("priority","").startswith("S")]
P("S级总数", len(S))
random.seed(7)
P("S级抽样:", [(e["word"], e["meaning"], e.get("freq"), e.get("priority_score")) for e in random.sample(S, min(20,len(S)))])

# ---------- 7 异常 ----------
P("\n=== 7 异常数据 ===")
for name, arr in libs.items():
    empty = [e["word"] for e in arr if not (e.get("meaning") or "").strip()]
    single = [e["word"] for e in arr if len(e["word"].strip()) <= 1]
    num = [e["word"] for e in arr if re.search(r"[0-9]", e["word"])]
    hyph = [e["word"] for e in arr if "-" in e["word"]]
    upper = [e["word"] for e in arr if e["word"] != e["word"].lower()]
    longw = [e["word"] for e in arr if len(e["word"]) > 20]
    weird = [e["word"] for e in arr if not re.fullmatch(r"[A-Za-z][A-Za-z\-' ]*", e["word"])]
    badmean = [e["word"] for e in arr if re.search(r"[\x00-\x1f�]|\\u", e.get("meaning") or "")]
    dupsm = [e["word"] for e in arr if re.search(r"[,，;；]{2,}|^[;；,，]|[;；,，]$", e.get("meaning") or "")]
    P(f"{name}: 空释义{len(empty)}{empty[:8]} 单字母{len(single)}{single[:8]} 数字{len(num)}{num[:8]} 连字符{len(hyph)}{hyph[:8]} 大写{len(upper)}{upper[:8]} >20{len(longw)}{longw[:5]} 非法字符{len(weird)}{weird[:8]} 乱码{len(badmean)}{badmean[:5]}")
long_meaning = [(n,e["word"],e["meaning"]) for n,arr in libs.items() for e in arr if len(e.get("meaning") or "")>40]
P("释义>40字符", len(long_meaning), long_meaning[:10])

open(r"C:\my_project\单词\scripts\check_out1.txt","w",encoding="utf-8").write("\n".join(out))
print("done", len(out))
