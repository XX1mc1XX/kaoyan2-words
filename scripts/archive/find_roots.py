# -*- coding: utf-8 -*-
"""定位词根碎片 + 统计 freq=0 分布。"""
import io
import json

D = r"c:\my_project\单词\data"
DECKS = ("words", "derivatives", "basic", "insurance")
data = {d: json.load(io.open(D + "\\" + d + ".json", encoding="utf-8")) for d in DECKS}

suspects = ["ali", "amb", "auct", "cip", "tract", "voc", "etc", "colon", "cult", "veal", "flour", "heart"]
print("=== 可疑词定位 ===")
for s in suspects:
    hits = [(d, x.get("meaning", ""), x.get("freq")) for d in DECKS for x in data[d] if x["word"] == s]
    print("  %-8s %s" % (s, hits if hits else "-- 不在库中"))

print("\n=== freq=0 各库统计 ===")
for d in DECKS:
    z = [x for x in data[d] if (x.get("freq") or 0) == 0]
    print("  %-12s 共 %4d, freq=0 有 %4d (%.0f%%)" % (d, len(data[d]), len(z), len(z) * 100 / len(data[d])))

print("\n=== freq=0 且长度<=4 的词（高疑似碎片）===")
for d in DECKS:
    frag = [x["word"] for x in data[d] if (x.get("freq") or 0) == 0 and len(x["word"]) <= 4]
    if frag:
        print("  %-12s %s" % (d, " ".join(frag[:40])))
