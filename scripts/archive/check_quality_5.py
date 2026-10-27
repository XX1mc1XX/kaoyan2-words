# -*- coding: utf-8 -*-
"""定稿：insurance 词根污染、forms 语义冲突、freq 漏算、覆盖率缺口分层"""
import json, csv, re
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
han=lambda s:set(re.findall(r"[一-鿿]",s))

P("=== insurance 短词全表 (<=5) ===")
short=[e for e in ins if len(e["word"])<=5]
P("数量",len(short))
for e in sorted(short,key=lambda x:len(x["word"])):
    P(f"  {e['word']:6s} {e['meaning']:12s} tags={sorted(tag.get(e['word'],[]))} freq={e['freq']} en1={e['en1_freq']}")

P("\n=== insurance 明显错义（词根义/他词义）===")
for w in ["colon","cult","tract","cite","fer","fid","ject","lect","mit","mot","nom","pos","reg","rupt","sect","sent","spec","struct","vert","vid"]:
    e=next((x for x in ins if x["word"]==w),None)
    if e: P("  ",w,e["meaning"],"| ecdict:",trans.get(w,"")[:60].replace("\n"," "))

P("\n=== forms 与主词语义零重合（最误导）===")
loc={e["word"].lower():(n,e) for n,arr in libs.items() for e in arr}
zero=[]
for n,arr in libs.items():
    for e in arr:
        for f in (e.get("forms") or []):
            t=loc.get(f.lower())
            if t and f.lower()!=e["word"].lower():
                a,b=han(e["meaning"]),han(t[1]["meaning"])
                if a and b and len(a&b)==0:
                    zero.append((round(len(a&b)/len(a|b),2),n,e["word"],e["meaning"],f,t[0],t[1]["meaning"]))
P("零重合对数",len(zero))
for z in zero[:30]: P("  ",z)
# 跨库且零重合
crosszero=[z for z in zero if z[1]!=z[5]]
P("其中跨库",len(crosszero),crosszero[:20])

P("\n=== 因 top_form 不对齐而 freq=0 的条目 ===")
infl=defaultdict(list)
for lemma,v in K.items():
    tf=v.get("top_form","")
    if tf and tf!=lemma: infl[tf].append((lemma,v["count"],v["coverage"]))
rows=[]
for n,arr in libs.items():
    for e in arr:
        w=e["word"].lower()
        if e["freq"]==0 and w in infl:
            rows.append((n,w,e["meaning"],e["en1_freq"],infl[w]))
P("条目数",len(rows))
for r in rows[:35]: P("  ",r)

P("\n=== 优先级全局 ===")
for n,arr in libs.items():
    P(n,"S",sum(1 for e in arr if e["priority"][0]=="S"),"A",sum(1 for e in arr if e["priority"][0]=="A"),"B",sum(1 for e in arr if e["priority"][0]=="B"),"C",sum(1 for e in arr if e["priority"][0]=="C"))
allr=Counter(e["priority_rank"] for arr in libs.values() for e in arr)
P("rank=1 出现次数",allr[1],"rank<=100 出现次数",sum(v for k,v in allr.items() if k<=100))
# insurance priority_rank 与 score 单调?
for n in ["insurance","basic"]:
    arr=libs[n]; rs=[(e["priority_rank"],e.get("priority_score",e.get("freq"))) for e in arr]
    P(n,"rank单调",all(rs[i][1]>=rs[i+1][1] for i in range(len(rs)-1)),"score空",sum(1 for e in arr if "priority_score" not in e))

P("\n=== 覆盖率缺口分层 ===")
union=set(loc)
forms_all=set(f.lower() for arr in libs.values() for e in arr for f in (e.get("forms") or []))
ky=set(w for w,t in tag.items() if "ky" in t)
target=ky & set(K)
lemma_of={}
for line in open(f"{BASE}\\lemma.en.txt",encoding="utf-8",errors="ignore"):
    if line.startswith(";") or "->" not in line: continue
    l,r=line.split("->",1); lem=l.split("/")[0].strip().lower()
    for x in r.split(","):
        x=x.strip().lower()
        if x and x not in lemma_of: lemma_of[x]=lem
union_lemmas={lemma_of[w] for w in union|forms_all if w in lemma_of}|(union|forms_all)
missing=[l for l in target if l not in union_lemmas and not (K[l].get("top_form") and K[l]["top_form"] in (union|forms_all))]
func={"the","be","to","of","and","it","in","that","have","for","they","you","on","as","with","can","i","more","but","not","this","at","by","from","or","we","all","he","she","his","her","their","there","what","which","who","when","one","do","if","will","would","could","should","may","was","were","is","are","has","had","an","a","its","our","your","my","me","him","them","us","these","those","some","any","no","so","than","then","too","very","just","also","only","into","over","after","before","up","out","about","off","own","same","such","both","each","few","most","other","while","where","why","how"}
miss=[l for l in missing if l not in func]
P("归一后缺失",len(missing),"非功能词",len(miss))
def cat(l):
    t=tag.get(l,set())
    if "zk" in t or "gk" in t: return "初高中"
    if "cet4" in t or "cet6" in t: return "四六级"
    return "仅考研/其他"
P("缺失分层",dict(Counter(cat(l) for l in miss)))
P("缺失初高中词 top30",[(l,K[l]["count"]) for l in sorted(miss,key=lambda x:-K[x]["count"]) if cat(l)=="初高中"][:30])
P("缺失仅考研 top20",[(l,K[l]["count"]) for l in sorted(miss,key=lambda x:-K[x]["count"]) if cat(l)=="仅考研/其他"][:20])
P("大纲总词",len(ky),"并集∩大纲",len(union&ky),f"{len(union&ky)/len(ky):.1%}")
# 真题覆盖（按词次）而非词种
tot=sum(v["count"] for w,v in K.items() if w in ky)
cov=sum(v["count"] for w,v in K.items() if w in ky and (w in union_lemmas or (v.get("top_form") and v["top_form"] in (union|forms_all))))
P("按词次覆盖率",f"{cov/tot:.2%}",cov,tot)

open(r"C:\my_project\单词\scripts\check_out5.txt","w",encoding="utf-8").write("\n".join(out))
print("done")
