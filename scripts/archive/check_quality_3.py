# -*- coding: utf-8 -*-
"""释义异常、S级分布、basic 合理性、覆盖率精算（含 top_form 映射）"""
import json, csv, re, random
from collections import Counter, defaultdict
BASE = r"C:\my_project\单词\data"
load = lambda n: json.load(open(f"{BASE}\\{n}.json", encoding="utf-8"))
words, deriv, basic, ins = load("words"), load("derivatives"), load("basic"), load("insurance")
K = load("ky2_freq")["words"]
libs = {"words": words, "derivatives": deriv, "basic": basic, "insurance": ins}
out=[]; P=lambda *a: out.append(" ".join(map(str,a)))

# ecdict
tag={}; trans={}
with open(f"{BASE}\\ecdict.csv",encoding="utf-8",newline="") as f:
    for row in csv.DictReader(f):
        w=row["word"].strip().lower()
        if w and w not in tag:
            tag[w]=set((row.get("tag") or "").split()); trans[w]=row.get("translation") or ""
P("ecdict loaded",len(tag))

# --- 4 释义异常扫描 ---
allE=[(n,e) for n,arr in libs.items() for e in arr]
posbad=[(n,e["word"],e["meaning"]) for n,e in allE if re.search(r"(^|[；;，,\s])(t|v|n|adj|adv|vt|vi|prep|conj)\.",e["meaning"])]
ascii_in=[(n,e["word"],e["meaning"]) for n,e in allE if re.search(r"[A-Za-z]",e["meaning"])]
dupseg=[]; leadpunct=[]; ellipsis=[]; trail=[]
for n,e in allE:
    m=e["meaning"]
    segs=[s.strip() for s in re.split(r"[；;，,]",m) if s.strip()]
    if len(segs)!=len(set(segs)): dupseg.append((n,e["word"],m))
    if re.match(r"^[；;，,、]",m) or "…" in m: ellipsis.append((n,e["word"],m))
    if re.search(r"[；;，,]$",m): trail.append((n,e["word"],m))
P("\n=== 4 释义结构异常 ===")
P("词性标注残留",len(posbad),posbad[:15])
P("释义含英文",len(ascii_in),ascii_in[:15])
P("重复义项",len(dupseg),dupseg[:15])
P("省略号/开头标点",len(ellipsis),ellipsis[:15])
P("结尾标点",len(trail),trail[:10])
# 与 ecdict 释义汉字重合度过低
def han(s): return set(re.findall(r"[一-鿿]",s))
low=[]
for n,e in allE:
    w=e["word"].lower(); t=trans.get(w,"")
    if not t: continue
    a=han(e["meaning"]); b=han(t)
    j=len(a&b)/max(len(a),1)
    if len(a)<=3 or j<0.10: low.append((round(j,2),n,e["word"],e["meaning"],t.replace("\n"," ")[:40]))
low.sort()
P("与ecdict重合低/过短",len(low))
for x in low[:35]: P("  ",x)

# --- 5 优先级 ---
P("\n=== 5 优先级 ===")
for nm,arr in [("words",words),("derivatives",deriv)]:
    ps=[e["priority"][0] for e in arr]; sc=[e["priority_score"] for e in arr]
    P(nm,dict(Counter(ps)),"score range",min(sc),max(sc))
    for g in "SAB":
        v=[e for e in arr if e["priority"][0]==g]
        if v: P(f"  {g}: n={len(v)} score {min(x['priority_score'] for x in v):.2f}-{max(x['priority_score'] for x in v):.2f} freq中位{sorted(x['freq'] for x in v)[len(v)//2]}")
    # 越界
    S=[e for e in arr if e["priority"][0]=="S"]; A=[e for e in arr if e["priority"][0]=="A"]
    if S and A: P("  minS",min(x['priority_score'] for x in S),"maxA",max(x['priority_score'] for x in A))
P("insurance",dict(Counter(e["priority"][0] for e in ins)))
# S 级中低价值
S=[e for e in words+deriv if e["priority"][0]=="S"]
P("S中freq<=2:",[(e["word"],e["freq"],e["coverage"],e["priority_score"]) for e in S if e["freq"]<=2][:20])
P("S中freq<=2 count",sum(1 for e in S if e["freq"]<=2))
P("S中freq=0",sum(1 for e in S if e["freq"]==0))
P("S中coverage<=2",sum(1 for e in S if e["coverage"]<=2))
# A 中高质量
A=[e for e in words+deriv if e["priority"][0]=="A"]
P("A中freq>=20",sum(1 for e in A if e["freq"]>=20),[(e["word"],e["freq"]) for e in A if e["freq"]>=20][:8])

# --- 6 basic 合理性 ---
P("\n=== 6 basic ===")
def tags(w): return sorted(tag.get(w,set()))
bt={}
for e in basic: bt.setdefault(tuple(tags(e["word"])),0); bt[tuple(tags(e["word"]))]+=1
P("basic tag 组合 top",Counter({k:v for k,v in bt.items()}).most_common(10))
nobasic=[e for e in basic if not (set(tags(e["word"])) & {"zk","gk","cet4"})]
P("basic 中无 zk/gk/cet4 标签",len(nobasic),[(e["word"],e["meaning"],tags(e["word"]),e["freq"]) for e in nobasic][:25])
# basic 词长/难度
P("basic 抽查20个:",[(e["word"],e["meaning"],e["freq"]) for e in random.Random(5).sample(basic,20)])
# 熟词僻义迹象：释义少于3汉字
P("basic 释义<=4汉字",[(e["word"],e["meaning"]) for e in basic if len(re.findall(r"[一-鿿]",e["meaning"]))<=3][:30])

# --- 8 覆盖率精算 ---
P("\n=== 8 覆盖率 ===")
union={e["word"].lower():n for n,arr in libs.items() for e in arr}
forms_all=set(f.lower() for n,arr in libs.items() for e in arr for f in (e.get("forms") or []))
ky=set(w for w,t in tag.items() if "ky" in t)
ky2=set(K)
target=ky2&ky
P("并集",len(union),"ky2∩大纲",len(target),"覆盖",len(target&set(union)),f"{len(target&set(union))/len(target):.1%}")
# 词形归一：若 lemma 的 top_form / 任何变形在并集中，则算覆盖
def covered(lemma):
    if lemma in union: return True
    tf=K[lemma].get("top_form","")
    if tf and (tf in union or tf in forms_all): return True
    return False
lemma_of={}
for line in open(f"{BASE}\\lemma.en.txt",encoding="utf-8",errors="ignore"):
    if "->" not in line or line.startswith(";"): continue
    left,right=line.split("->",1)
    lem=left.split("/")[0].strip().lower()
    for f in right.split(","):
        f=f.strip().lower()
        if f and f not in lemma_of: lemma_of[f]=lem
unionset=set(union)|forms_all
# 只保留并集内单词的 lemma
union_lemmas={lemma_of[w] for w in unionset if w in lemma_of} | unionset
P("并集词形归一后 lemma 数",len(union_lemmas))
cov2={l for l in target if l in union_lemmas or covered(l)}
P("词形归一后覆盖",len(cov2),f"{len(cov2)/len(target):.1%}")
missing=[l for l in target if l not in cov2]
# 常用功能词过滤：ecdict 有 zk 且无 ky? 这些通常是初中词
def is_func(l):
    return l in {"the","be","to","of","and","it","in","that","have","for","they","you","on","as","with","can","i","more","but","not","this","at","by","from","or","we","all","he","she","his","her","their","there","what","which","who","when","one","do","if","will","would","could","should","may","was","were","is","are","has","had","an","a"}
miss2=[(l,K[l]["count"],K[l]["coverage"],K[l].get("top_form"),sorted(tag.get(l,set()))) for l in missing if not is_func(l)]
miss2.sort(key=lambda x:(-x[1],-x[2]))
P("归一后缺失",len(missing),"非功能词",len(miss2))
for m in miss2[:25]: P("  ",m)
# 按词形是否已在并集里（表面词）
miss3=[(l,K[l]["count"],K[l].get("top_form")) for l in missing if K[l].get("top_form") in union]
P("缺失lemma但其top_form在并集",len(miss3),miss3[:10])

open(r"C:\my_project\单词\scripts\check_out3.txt","w",encoding="utf-8").write("\n".join(out))
print("done")
