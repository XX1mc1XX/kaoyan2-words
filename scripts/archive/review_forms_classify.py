# -*- coding: utf-8 -*-
"""按人工判定把 343 对候选分成 delete/keep/doubt，写出 forms_review.json。
只读 dump 并写一个审查结果文件，不触碰任何词库数据。"""
import io
import json

DUMP = r"c:\my_project\单词\scripts\review_forms_dump.txt"
OUT = r"c:\my_project\单词\data\forms_review.json"

# 语义完全无关 / 同形异义：会误导用户
DELETE = [
    ("industry", "diligent"),   # 工业 vs 勤勉
    ("rise", "rose"),           # 上升 vs 玫瑰，同形异义（rose 也是过去式）
    ("unlike", "unlikely"),     # 不像 vs 不太可能；unlikely=un+likely
    ("rare", "raring"),         # 稀罕 vs 渴望；raring 源自 rear
    ("corn", "corner"),         # 玉米 vs 角落，语源不同
    ("care", "career"),         # 关心 vs 事业，语源不同
    ("flow", "flower"),         # 流动 vs 花，语源不同
    ("drift", "drive"),         # 漂流 vs 驱动，语源不同
    ("better", "bet"),          # 较好(good 比较级) vs 打赌
]

# 同源但现代语义/形态已分化、或主词本身有问题，留给人决定
DOUBT = [
    ("content", "contain"),     # 内容 vs 包含，同源但已分化
    ("respect", "respectively"),# 尊敬 vs 分别地，副词义脱离
    ("fair", "faired"),         # 公平/集市 vs 整流（fair 冷僻动词义）
    ("fair", "fairing"),        # 同上，整流罩
    ("clar", "clarity"),        # 主词 clar 不是独立英文单词（词条本身可疑）
    ("base", "basement"),       # 基础 vs 地下室，-ment 派生但语义专门化
    ("depart", "department"),   # 离开 vs 部门，同源但语义转移
    ("commit", "committee"),    # 委托 vs 委员会，同源但形态/语义变化
    ("custom", "customer"),     # 习惯 vs 顾客，同源但语义转移
    ("attend", "attention"),    # 参加/照料 vs 注意，同源但语义分化
]

pairs = []
with io.open(DUMP, encoding="utf-8") as f:
    next(f, None)
    for line in f:
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 3:
            continue
        pairs.append((cols[1], cols[2]))

assert len(pairs) == 343, len(pairs)

del_set = set(DELETE)
doubt_set = set(DOUBT)
for p in DELETE + DOUBT:
    assert p in pairs, "not in candidates: %r" % (p,)
assert not (del_set & doubt_set), del_set & doubt_set

keep = [p for p in pairs if p not in del_set and p not in doubt_set]

result = {
    "delete": [list(p) for p in DELETE],
    "keep": [list(p) for p in keep],
    "doubt": [list(p) for p in DOUBT],
    "stats": {
        "total": len(pairs),
        "delete": len(DELETE),
        "keep": len(keep),
        "doubt": len(DOUBT),
    },
}
with io.open(OUT, "w", encoding="utf-8") as f:
    f.write(json.dumps(result, ensure_ascii=False, indent=1))
print(result["stats"])
