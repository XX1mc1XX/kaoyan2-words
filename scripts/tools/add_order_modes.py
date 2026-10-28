# -*- coding: utf-8 -*-
"""顺序策略：默认原序，打乱用「词表默认权重 + 我的右滑权重」合成权重做加权随机，另加恢复原序。"""
import io

P = r"c:\my_project\单词\software\template.html"
t = io.open(P, encoding="utf-8").read()
log = []


def rep(old, new, label):
    global t
    if old in t:
        t = t.replace(old, new, 1)
        log.append("OK    " + label)
    else:
        log.append("MISS  " + label)


# 1. 两个按钮并排
rep('<button class="shuffle-btn" id="shuffleChapter">↻ 打乱本章顺序</button>',
    '''<div class="order-btns">
      <button class="shuffle-btn" id="shuffleChapter">↻ 打乱顺序</button>
      <button class="shuffle-btn" id="restoreOrder">⟲ 恢复原序</button>
    </div>''', "两个顺序按钮")

rep('.shuffle-btn:active{border-color:var(--brand);color:var(--brand)}',
    '''.shuffle-btn:active{border-color:var(--brand);color:var(--brand)}
.order-btns{display:grid;grid-template-columns:1fr 1fr;gap:8px;flex-shrink:0}''', "按钮布局样式")

# 2. 合并权重：词表默认优先度 + 我的右滑次数
rep('''// 默认顺序：确定性排序，权重高的靠前，同级按词表原序（每次打开完全一致）
function priorityOrder(list) {
  return list.slice().sort((a, b) => (weightOf(b) - weightOf(a)) || (a.id - b.id));
}
// 加权洗牌：仅「打乱本章顺序」按钮使用
function shuffleByWeight(list) {''',
    '''// 词表自带的优先度权重（S 最高）
const TIER_SCORE = { S: 3, A: 2, B: 1, C: 0 };
function tierOf(word) {
  const p = String(word.priority || 'C').trim().charAt(0).toUpperCase();
  return TIER_SCORE[p] || 0;
}
// 合成权重 = 词表默认权重 + 我右滑累计的次数
function scoreOf(word) {
  return tierOf(word) + weightOf(word);
}
// 原序：完全按词表顺序，每次打开都一样
function naturalOrder(list) {
  return list.slice().sort((a, b) => a.id - b.id);
}
// 加权洗牌：只影响「靠前的概率」，权重高更可能排在前面，但不强制置顶
function shuffleByWeight(list) {''', "合并权重函数")

rep("    key: Math.pow(Math.random(), 1 / (1 + weightOf(word) * 0.5))",
    "    key: Math.pow(Math.random(), 1 / (1 + scoreOf(word) * 0.6))", "洗牌用合成权重")

# 3. loadChapter 三种模式：undefined=沿用记录，'shuffle'=打乱，'natural'=恢复原序
rep('''  if (reshuffle) {
    rec = chapterData[key] = { order: shuffleByWeight(pending).map(w => w.word), pos: 0, shuffled: true };
    save('ky_chapter_v1', chapterData);
  } else if (!rec || !Array.isArray(rec.order)) {
    rec = chapterData[key] = { order: priorityOrder(pending).map(w => w.word), pos: 0 };
    save('ky_chapter_v1', chapterData);
  }''',
    '''  if (mode === 'shuffle') {
    rec = chapterData[key] = { order: shuffleByWeight(pending).map(w => w.word), pos: 0, shuffled: true };
    save('ky_chapter_v1', chapterData);
  } else if (mode === 'natural' || !rec || !Array.isArray(rec.order)) {
    rec = chapterData[key] = { order: naturalOrder(pending).map(w => w.word), pos: 0 };
    save('ky_chapter_v1', chapterData);
  }''', "三种顺序模式")

rep("function loadChapter(ch, reshuffle) {", "function loadChapter(ch, mode) {   // mode: 'shuffle' 打乱 / 'natural' 原序 / 省略=沿用上次", "参数改名")

# 4. 调用点
rep("  loadChapter(curChapter, true);\n  updateStats();\n};\n$('prevWord')",
    "  loadChapter(curChapter, 'shuffle');\n  updateStats();\n};\n$('restoreOrder').onclick = () => {\n  loadChapter(curChapter, 'natural');\n  updateStats();\n};\n$('prevWord')", "打乱按钮 + 恢复原序")

rep("  loadChapter(curChapter, true);\n  updateStats();\n};\n$('tabStudy')",
    "  loadChapter(curChapter, mode === 'reshuffle' ? 'shuffle' : 'natural');\n  updateStats();\n};\n$('tabStudy')", "过完一轮按钮")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
