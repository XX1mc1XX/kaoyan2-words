# -*- coding: utf-8 -*-
"""检查 2 细节、3 缺失原因、4/6 抽样、8 覆盖率与缺失高频词"""
import json, csv, re, random
from collections import Counter, defaultdict
BASE = r"C:\my_project\单词\data"
load = lambda n: json.load(open(f"{BASE}\\{n}.json", encoding="utf-8"))
words, deriv, basic, ins = load("words"), load("derivatives"), load("basic"), load("insurance")
K = load("ky2_freq")["words"]
libs = {"words": words, "derivatives": deriv, "basic": basic, "insurance": ins}
out=[]; P=lambda *a: out.append(" ".join(map(str,a)))

# --- 2 细分 ---
loc = {}
for n,arr in libs.items():
    for e in arr: loc[e["word"].lower()] = n
same=[]; cross=[]
for n,arr in libs.items():
    for e in arr:
        for f in (e.get("forms") or []):
            f2=f.lower()
            if f2 in loc and f2 != e["word"].lower():
                (same if loc[f2]==n else cross).append((n,e["word"],f,loc[f2]))
P("forms命中主词: 同库",len(same),"跨库",len(cross))
P("跨库示例",cross[:20])
P("同库示例",same[:15])
# forms 数量分布
for n,arr in libs.items():
    c=Counter(len(e.get("forms") or []) for e in arr)
    P(f"forms数量 {n}:",dict(sorted(c.items())),"空forms",c[0])
# 词形相似度低（最长公共前缀<=2 且长度差大）
def lcp(a,b):
    i=0
    while i<min(len(a),len(b)) and a[i]==b[i]: i+=1
    return i
low=[(n,e["word"],f) for n,arr in libs.items() for e in arr for f in (e.get("forms") or []) if lcp(e["word"].lower(),f.lower())<=2]
P("低相似forms",len(low),low[:30])

# --- 3 缺失 lemma 的原因 ---
infl = {}
for lemma,v in K.items():
    tf=v.get("top_form","")
    if tf and tf!=lemma: infl.setdefault(tf,[]).append(lemma)
miss=[e for n,arr in libs.items() for e in arr if e["word"].lower() not in K]
P("\n不在ky2的条目",len(miss),"其中freq>0",sum(1 for e in miss if e.get("freq",0)>0))
P("freq>0但缺lemma示例",[(e["word"],e["freq"]) for e in miss if e.get("freq",0)>0][:10])
via=[(e["word"],infl[e["word"].lower()]) for e in miss if e["word"].lower() in infl]
P("可经top_form映射到lemma的",len(via),via[:15])
# freq 分布
P("freq分布",dict(sorted(Counter(e.get("freq") for n,arr in libs.items() for e in arr).items())[:12]))
# 按库 freq=0 比例
for n,arr in libs.items():
    P(f"{n} freq=0:",sum(1 for e in arr if e.get("freq",0)==0),"/",len(arr))

# --- 4 抽样 30 释义 ---
pool=[(n,e) for n,arr in libs.items() for e in arr]
random.seed(2024)
s30=random.sample(pool,30)
P("\n=== 4 释义30抽样 ===")
for n,e in s30: P(f"{n}\t{e['word']}\t{e['meaning']}")
# 释义结构性统计
multi=[(n,e["word"],e["meaning"]) for n,e in pool if re.search(r"[;；/]|，", e["meaning"])]
paren=[(n,e["word"],e["meaning"]) for n,e in pool if re.search(r"[()（）]", e["meaning"])]
pos=[(n,e["word"],e["meaning"]) for n,e in pool if re.search(r"^(n|v|adj|adv|prep|conj|pron)\.", e["meaning"])]
P("含多义分隔",len(multi),multi[:8])
P("含括号",len(paren),paren[:8])
P("含词性标注",len(pos),pos[:8])

# --- 6 basic 抽样 ---
random.seed(99)
P("\n=== 6 basic 20抽样 ===")
for e in random.sample(basic,20): P(f"{e['word']}\t{e['meaning']}\tfreq={e['freq']}")
bf=[e["freq"] for e in basic]
P("basic freq min/max/median", min(bf), max(bf), sorted(bf)[len(bf)//2])
P("basic freq<=5",[(e["word"],e["freq"],e["meaning"]) for e in basic if e["freq"]<=5][:20])
P("basic freq<=5 count",sum(1 for x in bf if x<=5))
P("basic 长词(>10)",[(e["word"],e["meaning"]) for e in basic if len(e["word"])>10][:20])
P("basic 含派生后缀",[(e["word"],e["meaning"]) for e in basic if re.search(r"(tion|ment|ness|ity|ous|ive|ally|ize|ise)$",e["word"])][:20])

# --- 8 大纲 + 覆盖 ---
ky=set(); tags=Counter()
with open(f"{BASE}\\ecdict.csv",encoding="utf-8",newline="") as f:
    r=csv.DictReader(f)
    for row in r:
        t=(row.get("tag") or "").split()
        if "ky" in t: ky.add(row["word"].strip().lower())
        for x in t: tags[x]+=1
P("\n=== 8 覆盖率 ===")
P("ecdict ky大纲词",len(ky),"tag分布top",tags.most_common(8))
union=set(loc)
kywords=set(K)
P("四库并集",len(union),"ky2词",len(kywords),"ky2∩大纲",len(kywords&ky),"ky2中非大纲",len(kywords-ky))
covered=kywords&ky&union
P("覆盖 ky2∩大纲:",len(covered),f"{len(covered)/max(len(kywords&ky),1):.1%}")
# 高频缺失：ky2 ∩ 大纲 ∩ 非proper，不在四库
missing=[(w,v["count"],v["coverage"],v.get("top_form")) for w,v in K.items() if w in ky and not v.get("proper") and w not in union]
missing.sort(key=lambda x:(-x[1],-x[2]))
P("缺失词数",len(missing),"top20:")
for m in missing[:20]: P("  ",m)
# 无大纲过滤的缺失 top
missing2=[(w,v["count"],v.get("proper")) for w,v in K.items() if w not in union and (not v.get("proper"))]
missing2.sort(key=lambda x:-x[1]); P("全部缺失(非proper)top20",missing2[:20])

open(r"C:\my_project\单词\scripts\check_out2.txt","w",encoding="utf-8").write("\n".join(out))
print("done")
