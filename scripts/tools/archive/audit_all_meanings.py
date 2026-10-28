# -*- coding: utf-8 -*-
"""释义全量体检：筛出所有可疑条目，输出可读清单供逐条判断。"""
import io
import json
import re

D = r"c:\my_project\单词\data"
DECKS = ("words", "derivatives", "basic", "insurance")

CJK_RE = re.compile(r"[一-鿿]")
POS_LEFT = re.compile(r"\b(vt|vi|v|n|adj|adv|prep|conj|pron|num|art|det|int|aux|link|modal|a|ad)\.", re.I)

rows = []
for d in DECKS:
    for x in json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")):
        rows.append((d, x["word"], x.get("meaning", ""), x.get("freq", 0)))

issues = {
    "空释义": [], "含英文": [], "含数字": [], "词性残留": [],
    "省略号": [], "重复义项": [], "疑似截断": [], "过短(1字)": [],
    "括号残留": [], "含杂符": [],
}

for d, w, m, f in rows:
    m = m or ""
    if not m.strip():
        issues["空释义"].append((d, w, m, f)); continue
    if re.search(r"[A-Za-z]{2,}", m):
        issues["含英文"].append((d, w, m, f))
    if re.search(r"\d", m):
        issues["含数字"].append((d, w, m, f))
    if POS_LEFT.search(m):
        issues["词性残留"].append((d, w, m, f))
    if "…" in m or "..." in m:
        issues["省略号"].append((d, w, m, f))
    parts = [p for p in m.split("、") if p]
    if len(parts) != len(set(parts)):
        issues["重复义项"].append((d, w, m, f))
    if m.endswith(("的", "了", "和", "与", "于", "在", "为", "把", "将", "使")):
        issues["疑似截断"].append((d, w, m, f))
    if len(m) == 1:
        issues["过短(1字)"].append((d, w, m, f))
    if re.search(r"[（(][^）)]*$", m):
        issues["括号残留"].append((d, w, m, f))
    if re.search(r"[*#@\\|/\[\]{}]", m):
        issues["含杂符"].append((d, w, m, f))

total_issues = sum(len(v) for v in issues.values())
print("词条总数 %d，各类可疑项合计 %d 条次\n" % (len(rows), total_issues))
for k, v in issues.items():
    if not v:
        continue
    print("=== %s: %d ===" % (k, len(v)))
    for d, w, m, f in sorted(v, key=lambda r: -r[3])[:40]:
        print("  %-16s %-30s [%s freq=%s]" % (w, m[:30], d, f))
    if len(v) > 40:
        print("  ... 其余 %d 条" % (len(v) - 40))
    print()
