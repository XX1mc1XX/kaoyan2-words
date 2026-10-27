# -*- coding: utf-8 -*-
"""最终核对：伪词计数、错义样例、insurance 基础词/空频、释义英文残留"""
import json, csv, re
from collections import Counter
BASE = r"C:\my_project\单词\data"
load = lambda n: json.load(open(f"{BASE}\\{n}.json", encoding="utf-8"))
words, deriv, basic, ins = load("words"), load("derivatives"), load("basic"), load("insurance")
K = load("ky2_freq")["words"]
libs={"words":words,"derivatives":deriv,"basic":basic,"insurance":ins}
out=[]; P=lambda *a: out.append(" ".join(map(str,a)))
tag={}; trans={}
with open(f"{BASE}\\ecdict.csv",encoding="utf-8",newline="") as f:
    for row in csv.DictReader(f):
        w=row["word"].strip().lower()
        if w and w not in tag: tag[w]=set((row.get("tag") or "").split()); trans[w]=row.get("translation") or ""

roots="ali amb auct bol bon bor bord cas caut cel cens chem chron cip cit clar cosm cred cret cult cur curr dens tra tract trai typ uni vers viol vit viv voc theat toler vari".split()
r=[e for e in ins if e["word"] in roots]
P("insurance 词根碎片精确数",len(r))
P("列表",[(e["word"],e["meaning"],e["priority"],e["en1_freq"]) for e in r])
P("insurance 中 zk/gk 基础词",sum(1 for e in ins if tag.get(e["word"],set()) & {"zk","gk"}),
  [(e["word"],e["meaning"],e["freq"]) for e in ins if tag.get(e["word"],set()) & {"zk","gk"}][:30])
P("insurance freq=0且en1=0",sum(1 for e in ins if e["freq"]==0 and e["en1_freq"]==0))
P("insurance freq=0且en1>0",sum(1 for e in ins if e["freq"]==0 and e["en1_freq"]>0))

P("\n错义核对:")
for w in ["colon","cult","veal","flour","ice","van","heart","question","part","dear","read","move","instruct","chalk","cheek","china","flour"]:
    e=next(((n,x) for n,arr in libs.items() for x in arr if x["word"]==w),None)
    if e: P(f"  {w}: {e[1]['meaning']} | ecdict: {trans.get(w,'')[:50]}")

# 真英文残留（排除词性标记 t./i./d./v./n./a. 等）
eng=[]
for n,arr in libs.items():
    for e in arr:
        s=re.sub(r"(^|[；;，,\s/])(t|i|d|v|n|a|adj|adv|vt|vi|prep|conj|pron|num|art|int)\.&?(t|i)?\.?","",e["meaning"])
        s=re.sub(r"[A-Za-z]\.","",s)
        if re.search(r"[A-Za-z]{2,}",s): eng.append((n,e["word"],e["meaning"]))
P("\n真英文残留",len(eng),eng[:20])
P("含截断/异常标点(：或~)",[(n,e["word"],e["meaning"]) for n,arr in libs.items() for e in arr if re.search(r"[：~]",e["meaning"])][:20])

# 优先级总数
for n,arr in libs.items():
    P(n,dict(Counter(e["priority"][0] for e in arr)))
P("总计",dict(Counter(e["priority"][0] for arr in libs.values() for e in arr)))

# forms 冲突受影响主词条 & 唯一 form
loc={e["word"].lower() for arr in libs.values() for e in arr}
aff=set(); forms=set()
for n,arr in libs.items():
    for e in arr:
        for f in (e.get("forms") or []):
            if f.lower() in loc and f.lower()!=e["word"].lower(): aff.add((n,e["word"])); forms.add(f.lower())
P("forms冲突: 受影响主词条",len(aff),"唯一form词",len(forms))
# 被最多引用的 form
cnt=Counter(f.lower() for arr in libs.values() for e in arr for f in (e.get("forms") or []) if f.lower() in loc)
P("被引用最多的form",cnt.most_common(15))

open(r"C:\my_project\单词\scripts\check_out6.txt","w",encoding="utf-8").write("\n".join(out))
print("done")
