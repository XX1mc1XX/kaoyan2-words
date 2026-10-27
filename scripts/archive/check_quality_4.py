# -*- coding: utf-8 -*-
"""深挖：insurance 伪词、freq 缺失词、basic 释义偏移、derivatives family、forms 细节"""
import json, csv, re, random
from collections import Counter, defaultdict
BASE = r"C:\my_project\单词\data"
load = lambda n: json.load(open(f"{BASE}\\{n}.json", encoding="utf-8"))
words, deriv, basic, ins = load("words"), load("derivatives"), load("basic"), load("insurance")
K = load("ky2_freq")["words"]
libs = {"words": words, "derivatives": deriv, "basic": basic, "insurance": ins}
out=[]; P=lambda *a: out.append(" ".join(map(str,a)))

tag={}; trans={}
with open(f"{BASE}\\ecdict.csv",encoding="utf-8",newline="") as f:
    for row in csv.DictReader(f):
        w=row["word"].strip().lower()
        if w and w not in tag:
            tag[w]=set((row.get("tag") or "").split()); trans[w]=row.get("translation") or ""

# lemma 词表
known=set()
for line in open(f"{BASE}\\lemma.en.txt",encoding="utf-8",errors="ignore"):
    if line.startswith(";") or "->" not in line: continue
    left,right=line.split("->",1)
    known.add(left.split("/")[0].strip().lower())
    for x in right.split(","):
        x=x.strip().lower()
        if x: known.add(x)

# --- insurance 伪词 ---
P("=== insurance 伪词/词根 ===")
susp=[e for e in ins if not (tag.get(e["word"].lower(),set()) & {"zk","gk","cet4","cet6","ky","toefl","ielts","gre"})]
P("无任何考试标签",len(susp),[(e["word"],e["meaning"],sorted(tag.get(e["word"].lower(),[]))) for e in susp][:60])
notknown=[e for e in ins if e["word"].lower() not in known]
P("不在lemma词表",len(notknown),[(e["word"],e["meaning"],trans.get(e["word"].lower(),"")[:20].replace("\n"," ")) for e in notknown][:60])
short=[e for e in ins if len(e["word"])<=4 and not tag.get(e["word"].lower())]
P("<=4字母且无标签",len(short),[(e["word"],e["meaning"]) for e in short][:50])
# 明确列出的词根类
roots={"ali","amb","auct","bol","bor","bord","cas","cens","cip","cit","cret","cult","cur","curr","dens","fer","fid","flu","grad","gress","ject","lect","log","man","mit","mot","nom","pend","pos","reg","rupt","scrib","sect","sent","spec","struct","tract","vert","vid","voc"}
r=[e for e in ins if e["word"] in roots]
P("词根名单命中",len(r),[(e["word"],e["meaning"]) for e in r])

# --- freq 重点核验 ---
P("\n=== freq 重点核验 ===")
for w in ["analysis","analyze","analysis","university","activity","accord","according","skill","team","role","rather","percent","art","might"]:
    printk = K.get(w)
    entry = next(( (n,e) for n,arr in libs.items() for e in arr if e["word"].lower()==w ), None)
    P(w, "ky2=", (printk["count"],printk["coverage"],printk.get("top_form")) if printk else "MISSING", "entry=", (entry[0],entry[1]["freq"],entry[1].get("en1_freq"),entry[1]["meaning"]) if entry else "ABSENT")
# derivatives freq=0 明细
P("derivatives freq=0:",[(e["word"],e["family"],e["meaning"],e["en1_freq"]) for e in deriv if e["freq"]==0][:30])
# S级 derivatives 明细
P("derivatives S:",[(e["word"],e["meaning"],e["freq"],e["coverage"],e["priority_score"]) for e in deriv if e["priority"][0]=="S"])

# --- basic 释义偏移 ---
P("\n=== basic 释义偏移 ===")
def han(s): return set(re.findall(r"[一-鿿]",s))
bl=[]
for e in basic:
    t=trans.get(e["word"].lower(),"")
    if not t: continue
    a=han(e["meaning"]); b=han(t)
    j=len(a&b)/max(len(a),1)
    if j<0.34: bl.append((round(j,2),e["word"],e["meaning"],t.replace("\n"," ")[:30]))
bl.sort()
P("basic 释义与ecdict重合<34%",len(bl))
for x in bl[:40]: P("  ",x)

# --- derivatives family ---
P("\n=== derivatives family ===")
P("family 空",sum(1 for e in deriv if not e.get("family")))
def lcp(a,b):
    i=0
    while i<min(len(a),len(b)) and a[i]==b[i]: i+=1
    return i
badf=[(e["word"],e["family"],e["meaning"]) for e in deriv if e.get("family") and lcp(e["word"].lower(),e["family"].lower())<3]
P("family 与词首 3 字母不同",len(badf),badf[:25])
P("derivatives 全表:",[(e["word"],e["family"],e["meaning"],e["freq"]) for e in deriv][:40])

# --- forms 细节 ---
P("\n=== forms 细节 ===")
selfref=[]; dupin=[]; odd=[]
for n,arr in libs.items():
    for e in arr:
        fs=[f.lower() for f in (e.get("forms") or [])]
        if e["word"].lower() in fs: selfref.append((n,e["word"],fs))
        if len(fs)!=len(set(fs)): dupin.append((n,e["word"],fs))
        for f in fs:
            if re.search(r"[0-9]|[^a-z\-']",f) or len(f)>25 or len(f)<2: odd.append((n,e["word"],f))
P("forms含自身",len(selfref),selfref[:10])
P("forms内部重复",len(dupin),dupin[:10])
P("forms字符合法性异常",len(odd),odd[:10])
# forms 指向主词的按 owner 库统计
loc={e["word"].lower():n for n,arr in libs.items() for e in arr}
byowner=Counter()
for n,arr in libs.items():
    for e in arr:
        for f in (e.get("forms") or []):
            if f.lower() in loc and f.lower()!=e["word"].lower(): byowner[(n,loc[f.lower()])]+=1
P("forms→主词 组合计数",dict(byowner))

# --- words S 抽样 ---
random.seed(11)
S=[e for e in words if e["priority"][0]=="S"]
P("\nwords S 20抽样:",[(e["word"],e["meaning"],e["freq"],e["coverage"]) for e in random.sample(S,20)])
allranks=[e["priority_rank"] for arr in libs.values() for e in arr]
P("priority_rank 全局: 条目",len(allranks),"不同rank",len(set(allranks)),"重复条目数",len(allranks)-len(set(allranks)))

open(r"C:\my_project\单词\scripts\check_out4.txt","w",encoding="utf-8").write("\n".join(out))
print("done")
