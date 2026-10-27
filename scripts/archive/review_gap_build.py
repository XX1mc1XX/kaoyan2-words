# -*- coding: utf-8 -*-
"""生成 gap_review.json：对 2545 个缺口候选逐条判定 add/skip。"""
import io
import json

D = r"c:\my_project\单词\data"
SRC = r"c:\my_project\单词\scripts\review_gap_candidates.tsv"

rows = []
with io.open(SRC, encoding="utf-8") as f:
    next(f)
    for line in f:
        p = line.rstrip("\n").split("\t")
        rows.append({
            "word": p[0], "count": int(p[1]), "coverage": int(p[2]),
            "collins": int(p[3]), "tags": p[4], "pos": p[5],
            "zh": p[6], "en": p[7],
        })

by_word = {r["word"]: r for r in rows}

# ---- 建议补入的词：词 -> (精简释义, 判定理由) ----
ADD = {
    "accord": ("一致；协定", "考研实词，真题69次，常考搭配 accord with"),
    "study": ("学习；研究", "核心实词，真题66次，词表漏收"),
    "activity": ("活动；活跃", "考研高频实词，真题41次"),
    "might": ("可能；也许", "情态动词兼名词，真题39次，考研高频"),
    "art": ("艺术；技艺", "考研高频实词，真题38次，兼指人文学科"),
    "rather": ("宁可；相当", "考研高频副词，真题36次，rather than 常考"),
    "percent": ("百分比", "考研高频实词，真题31次"),
    "skill": ("技能；技巧", "考研核心实词，真题22次"),
    "toward": ("朝；对于", "真题21次，attitude toward 类搭配常考"),
    "role": ("角色；作用", "考研高频实词，真题20次"),
    "actually": ("实际上；其实", "考研语篇高频副词，真题20次"),
    "task": ("任务；工作", "考研高频实词，真题20次"),
    "adult": ("成年人；成年的", "考研高频实词，真题19次"),
    "plastic": ("塑料；可塑的", "环保类阅读常考，真题19次"),
    "corporate": ("公司的；法人的", "考研实词，真题18次"),
    "area": ("区域；领域", "考研高频实词，真题17次"),
    "guilt": ("内疚；罪责", "考研实词，真题17次"),
    "although": ("虽然；尽管", "让步连词，真题16次，阅读逻辑常考"),
    "gene": ("基因", "科技类阅读高频，真题16次"),
    "recently": ("最近", "考研语篇高频副词，真题16次"),
    "generally": ("通常；普遍地", "考研语篇高频副词，真题15次"),
    "race": ("种族；比赛", "考研实词，真题15次，种族议题常考"),
    "top": ("顶部；最高的", "考研高频实词，真题15次，top researchers 类用法"),
    "teenager": ("青少年", "教育类阅读常考，真题15次"),
    "extracurricular": ("课外的", "教育类阅读关键词，真题15次"),
    "allow": ("允许；承认", "考研实词，真题13次"),
    "psychologist": ("心理学家", "心理类阅读高频，真题13次"),
    "fake": ("假的；伪造", "考研实词，真题12次"),
    "recent": ("最近的", "考研高频形容词，真题12次"),
    "record": ("记录；录制", "考研实词，真题12次"),
    "zone": ("地带；区域", "考研实词，真题11次"),
    "formation": ("形成；构成", "考研实词，真题11次"),
    "workplace": ("工作场所", "职场类阅读关键词，真题11次"),
    "giant": ("巨大的；巨人", "考研实词，真题10次"),
    "weigh": ("权衡；重达", "考研实词，真题10次"),
    "prepare": ("准备", "考研实词，真题10次"),
    "highly": ("高度地；非常", "考研语篇高频副词，真题9次"),
    "purpose": ("目的；意图", "考研高频实词，真题9次"),
    "serious": ("严肃的；严重的", "考研高频形容词，真题9次"),
    "organization": ("组织；机构", "考研高频实词，真题9次"),
    "gender": ("性别", "社会议题高频，真题9次"),
    "interaction": ("互动；相互作用", "考研实词，真题9次"),
    "reader": ("读者；读本", "阅读类高频实词，真题9次"),
    "scale": ("规模；比例", "考研实词，真题9次"),
    "ethic": ("伦理；道德", "考研实词，真题9次"),
    "timber": ("木材", "环保类阅读实词，真题9次"),
    "immigration": ("移民；移入", "社会议题高频，真题9次"),
    "photograph": ("照片；拍照", "考研实词，真题9次"),
    "finding": ("发现；研究结果", "研究类阅读高频名词，真题8次"),
    "therefore": ("因此", "考研语篇逻辑副词，真题8次"),
    "corporation": ("公司；法人", "考研实词，真题8次"),
    "workforce": ("劳动力", "职场类阅读关键词，真题8次"),
    "curiosity": ("好奇心", "考研实词，真题8次"),
    "adolescence": ("青春期", "教育类阅读关键词，真题8次"),
    "selection": ("选择；挑选", "考研实词，真题8次"),
    "lifestyle": ("生活方式", "考研实词，真题8次"),
    "tax": ("税；征税", "考研实词，真题8次"),
    "screen": ("屏幕；筛选", "考研实词，真题8次，screen out 常考"),
    "willing": ("愿意的；乐意的", "考研实词，真题7次"),
    "agricultural": ("农业的", "农业类阅读关键词，真题7次"),
    "manufacturer": ("制造商", "经济类阅读实词，真题7次"),
    "trap": ("陷阱；使陷入", "考研实词，真题7次"),
    "slice": ("薄片；切片", "考研实词，真题7次"),
    "landowner": ("地主；土地所有者", "历史类阅读实词，真题7次"),
    "snap": ("突然折断；快照", "考研实词，真题7次"),
    "visa": ("签证", "考研实词，真题7次"),
    "official": ("官方的；官员", "考研实词，真题7次"),
    "affordable": ("负担得起的", "考研实词，真题7次"),
    "mainly": ("主要地", "考研语篇高频副词，真题7次"),
    "wealth": ("财富", "考研实词，真题6次"),
    "article": ("文章；条款", "考研高频实词，真题6次"),
    "favor": ("支持；恩惠", "考研实词，真题6次"),
    "cooperation": ("合作", "考研实词，真题6次"),
    "historical": ("历史的", "考研实词，真题6次"),
    "widely": ("广泛地", "考研语篇高频副词，真题6次"),
    "acre": ("英亩", "阅读实词，真题6次"),
    "cue": ("提示；线索", "考研实词，真题6次"),
    "protection": ("保护", "考研实词，真题6次"),
    "reaction": ("反应", "考研实词，真题6次"),
    "representative": ("代表；有代表性的", "考研实词，真题6次"),
    "stuff": ("东西；材料", "考研实词，真题6次"),
    "quota": ("配额；限额", "经济类阅读实词，真题6次"),
    "regenerative": ("可再生的", "环保类阅读关键词，真题6次"),
    "producer": ("生产者；制作人", "考研实词，真题6次"),
    "wildfire": ("野火", "环保类阅读实词，真题6次"),
    "passage": ("段落；通道", "阅读高频实词，真题6次"),
    "prairie": ("大草原", "生态类阅读实词，真题6次"),
    "con": ("缺点；骗局", "考研实词，真题6次，pros and cons"),
    "clothe": ("给(人)穿衣；覆盖", "考研实词，真题6次"),
    "rapidly": ("迅速地", "考研语篇高频副词，真题6次"),
    "temporarily": ("暂时地", "考研语篇副词，真题6次"),
    "recall": ("回忆；召回", "考研实词，真题5次"),
    "active": ("积极的；活跃的", "考研实词，真题5次"),
    "favorite": ("最喜欢的", "考研实词，真题5次"),
    "grind": ("磨碎；苦干", "考研实词，真题5次"),
    "poll": ("民意调查；投票", "社会类阅读实词，真题5次"),
    "prevent": ("阻止；预防", "考研高频动词，真题5次"),
    "roughly": ("大约；粗略地", "考研语篇高频副词，真题5次"),
    "seldom": ("很少；不常", "考研高频副词，真题5次"),
    "stimulus": ("刺激；激励", "经济/心理类实词，真题5次"),
    "biodiversity": ("生物多样性", "生态类阅读关键词，真题5次"),
    "governance": ("治理；管理", "社会类阅读实词，真题5次"),
    "motivate": ("激励；促使", "考研实词，真题5次"),
    "sex": ("性别；性", "社会议题实词，真题5次"),
    "genetic": ("基因的；遗传的", "科技类阅读关键词，真题5次"),
    "lawn": ("草坪", "考研实词，真题5次"),
    "passenger": ("乘客", "考研实词，真题5次"),
    "rebellious": ("叛逆的；反抗的", "教育类阅读实词，真题5次"),
    "species": ("物种", "生态类高频词，词形还原为 specie 漏收"),
    "thought": ("想法；思想", "考研高频名词，真题5次"),
    "warn": ("警告", "考研实词，真题5次"),
    "pack": ("打包；一包", "考研实词，真题5次"),
    "rapid": ("快速的", "考研实词，真题5次"),
    "satisfy": ("满足；使满意", "考研实词，真题5次"),
    "conceptual": ("概念的", "考研实词，真题5次"),
    "fitness": ("健康；适合", "健康类阅读实词，真题5次"),
    "frequently": ("频繁地", "考研语篇高频副词，真题5次"),
    "middle-class": ("中产阶级的", "社会类阅读关键词，真题5次"),
    "truly": ("真正地", "考研语篇副词，真题5次"),
    "western": ("西方的", "考研实词，真题5次"),
    "wildlife": ("野生动植物", "生态类阅读关键词，真题5次"),
    "prosocial": ("亲社会的", "社会心理类阅读关键词，真题5次"),
    "coworker": ("同事", "职场类阅读实词，真题5次"),
    "part-time": ("兼职的", "职场类阅读关键词，真题5次"),
    "sympathy": ("同情", "考研实词，真题5次"),
    "long-term": ("长期的", "考研高频复合形容词，真题5次"),
    "first-generation": ("第一代的", "社会类阅读关键词，真题9次"),
    "being": ("存在；生物", "考研名词，真题5次，human being 常考"),
    "occasionally": ("偶尔", "考研语篇副词，真题5次"),
    "simply": ("简单地；仅仅", "考研高频副词，真题17次"),
}

# ---- 需单独说明的跳过词 ----
MANUAL_SKIP = {
    "les": "词形还原错误（less），且 less 属基础词",
    "pas": "词形还原错误（pass），词表已收 pass",
    "datum": "词形还原错误（data），词表已收 data",
    "specie": "词形还原错误，实际为 species，已按 species 补入",
    "tum": "疑似 OCR/拼写噪声，非规范词汇",
    "fbr": "缩写，非考试词汇",
    "ifs": "缩写，非考试词汇",
    "tech": "口语缩略（technology），非考点",
    "app": "缩写（application），非考点",
    "euro": "货币专名",
    "programme": "英式拼写，词表已收同义拼写",
    "behaviour": "英式拼写，词表已收 behavior",
    "center": "美式拼写，词表已有 centre/central",
    "worker": "基础词，已作为 work 的变形收录",
    "user": "基础词，已作为 use 的变形收录",
    "phone": "极基础中学词",
    "email": "极基础中学词",
    "video": "极基础中学词",
    "fast-food": "极基础复合词",
    "visitor": "极基础中学词",
    "stranger": "极基础中学词",
    "supermarket": "极基础中学词",
    "newspaper": "极基础中学词",
    "food": "幼儿园级具体名词",
    "park": "幼儿园级具体名词",
    "tree": "幼儿园级具体名词",
    "wood": "极基础具体名词",
    "rat": "极基础具体名词",
    "train": "极基础具体名词",
    "team": "极基础具体名词",
    "office": "极基础具体名词",
    "week": "极基础时间名词",
    "month": "极基础时间名词",
    "room": "极基础具体名词",
    "water": "极基础具体名词",
    "wear": "极基础动词",
    "name": "极基础具体名词",
    "news": "极基础具体名词",
    "party": "极基础具体名词",
    "picture": "极基础具体名词",
    "sound": "极基础具体名词",
    "war": "极基础具体名词",
    "rich": "极基础形容词",
    "shop": "极基础具体名词",
    "watch": "极基础动词",
    "wind": "极基础具体名词",
    "side": "极基础方位名词",
    "strange": "极基础形容词",
    "smile": "极基础动词",
    "safe": "极基础形容词",
    "size": "极基础名词",
    "speed": "极基础名词",
    "step": "极基础名词",
    "rest": "极基础名词",
    "slow": "极基础形容词",
    "quick": "极基础形容词",
    "whole": "极基础形容词",
    "simple": "极基础形容词",
    "space": "极基础名词",
    "period": "极基础名词",
    "return": "极基础动词",
    "sport": "极基础名词",
    "towards": "toward 的变体，已按 toward 补入",
    "probably": "极基础副词，非考研考点",
    "perhaps": "极基础副词，非考研考点",
    "writer": "极基础名词",
    "web": "极基础名词",
}

# 纯功能词（候选里出现的高频虚词），用于给出准确跳过理由
FUNCTION_WORDS = set("""
the and that have for they you with can more but not this from about will than
one other may what when who all would most which how out there should much well
many just also only because such into over while she often after too any before
now through still first where then very same both few down today two off every
between once yet past since without among though always against must whether
themselves why three next each million during under half four until five yourself
whose together along second eight third another nothing whatever someone anyone
ourselves cannot never again almost here soon already within unless against
across above along behind below beside beyond during except inside onto outside
throughout toward towards upon via whose whoever whichever
""".split())


def is_pure_function(r):
    pos = r["pos"]
    keys = {p.split(":")[0] for p in pos.split("/") if p}
    if r["word"] in FUNCTION_WORDS:
        return True
    # 词性只有冠词/连词/代词/介词/助动词/数词/感叹词，没有实义名词动词形容词
    return bool(keys) and keys <= {"art", "conj", "pron", "prep", "aux", "num", "interj", "det"}


add, skip = [], []
for r in rows:
    w = r["word"]
    if w in ADD:
        m, reason = ADD[w]
        add.append({"word": w, "count": r["count"], "meaning": m, "reason": reason})
        continue
    if w in MANUAL_SKIP:
        reason = MANUAL_SKIP[w]
    elif "'" in w or "’" in w:
        reason = "缩略形式（含撇号），不单独收录"
    elif r["count"] < 5:
        reason = "真题仅%d次，不足5次，按标准不补" % r["count"]
    elif is_pure_function(r):
        reason = "纯功能词"
    elif "zk" in r["tags"].split() and not any(t in r["tags"].split() for t in ("cet4", "cet6", "ky")):
        reason = "极基础中学词，非考研考点"
    elif "gk" in r["tags"].split() and not any(t in r["tags"].split() for t in ("cet4", "cet6", "ky")):
        reason = "基础高考词，非考研考点"
    elif "abbr." in r["zh"]:
        reason = "缩写，非考试词汇"
    elif not r["tags"].strip():
        reason = "无大纲标签，非考研核心词"
    else:
        reason = "基础实词，非考研考点"
    skip.append({"word": w, "count": r["count"], "reason": reason})

add.sort(key=lambda x: (-x["count"], x["word"]))
skip.sort(key=lambda x: (-x["count"], x["word"]))

out = {
    "add": add,
    "skip": skip,
    "stats": {"candidates": len(rows), "add": len(add), "skip": len(skip)},
}
with io.open(D + r"\gap_review.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

matched = {a["word"] for a in add} - {"species"}
missing = matched - set(by_word)
print("candidates", len(rows), "add", len(add), "skip", len(skip))
print("add words not in candidates:", sorted(missing))
print("add count>=5 all:", all(a["count"] >= 5 for a in add))
