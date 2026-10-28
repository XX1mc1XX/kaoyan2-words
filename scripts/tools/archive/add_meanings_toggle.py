# -*- coding: utf-8 -*-
"""学习页右上角加回释义开关：控制「默认显示 / 默认隐藏」，点卡片仍可单次翻面。"""
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


# 1. study-head 加回第三列按钮
rep('<select class="chapter-select" id="chapterSelect" aria-label="跳转章节"></select>',
    '<select class="chapter-select" id="chapterSelect" aria-label="跳转章节"></select>\n'
    '      <button class="meaning-toggle" id="meaningToggle" aria-pressed="false">释义关</button>',
    "study-head 加按钮")

rep(".study-head{display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px;align-items:center;flex-shrink:0}",
    ".study-head{display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:6px;align-items:center;flex-shrink:0}",
    "study-head 恢复三列")

rep(".chapter-select{",
    """.meaning-toggle{justify-self:end;border:1px solid color-mix(in srgb,var(--brand) 45%,var(--line));
  background:var(--card);color:var(--brand);font:inherit;font-size:12px;font-weight:700;
  border-radius:999px;padding:7px 10px;cursor:pointer;white-space:nowrap}
.meaning-toggle[aria-pressed="true"]{background:var(--brand);color:#fff}
@media (prefers-color-scheme:dark){.meaning-toggle[aria-pressed="true"]{color:#0b1714}}
.chapter-select{""", "按钮样式")

# 2. conf 增加默认显示开关（替代已废弃的 autoShow）
rep("let conf = Object.assign({ deck: 'core', deckChapter: {} }, load(LS_CONF, {}));\ndelete conf.autoShow;   // 旧版本遗留的全局开关，彻底废弃",
    "let conf = Object.assign({ deck: 'core', deckChapter: {}, showByDefault: false }, load(LS_CONF, {}));\ndelete conf.autoShow;   // 旧版本遗留的全局开关，彻底废弃",
    "conf 增加 showByDefault")

# 3. revealed 恢复三态：null=跟随默认，true/false=当前词覆盖
rep("let revealed = false;", "let revealed = null;   // null=跟随「默认显示」设置；true/false=当前词手动覆盖",
    "revealed 改三态")

rep("  const show = revealed;", "  const show = revealed === null ? !!conf.showByDefault : revealed;",
    "显示判断跟随默认值")

# 4. 翻词/切章重置为「跟随默认」
t = t.replace("revealed = false;", "revealed = null;")
log.append("OK    revealed 重置点改为 null")

# 5. 点卡片：切换当前词
rep("""function toggleMeaning() {
  revealed = !revealed;
  renderStudy();
}""",
    """function toggleMeaning() {
  const cur = revealed === null ? !!conf.showByDefault : revealed;
  revealed = !cur;
  renderStudy();
}""", "点卡片切换当前词")

# 6. 按钮：切换默认值
rep("$('chapterSelect').onchange = event => gotoChapter(Number(event.target.value));",
    """$('chapterSelect').onchange = event => gotoChapter(Number(event.target.value));
$('meaningToggle').onclick = () => {
  conf.showByDefault = !conf.showByDefault;
  save(LS_CONF, conf);
  revealed = null;
  renderStudy();
};""", "按钮切默认值")

# 7. 渲染时更新按钮文案
rep("  $('chapterSelect').value = String(currentChapter());",
    """  $('meaningToggle').textContent = conf.showByDefault ? '释义开' : '释义关';
  $('meaningToggle').setAttribute('aria-pressed', String(!!conf.showByDefault));
  $('chapterSelect').value = String(currentChapter());""", "按钮文案更新")

# 8. 导出/导入带上 showByDefault
rep("    conf: { deck: conf.deck, chapter: conf.chapter || 0, deckChapter: conf.deckChapter || {} }",
    "    conf: { deck: conf.deck, chapter: conf.chapter || 0, deckChapter: conf.deckChapter || {}, showByDefault: !!conf.showByDefault }",
    "导出带 showByDefault")
rep("        if (d.conf.deckChapter) conf.deckChapter = d.conf.deckChapter;",
    "        if (d.conf.deckChapter) conf.deckChapter = d.conf.deckChapter;\n        conf.showByDefault = !!d.conf.showByDefault;",
    "导入带 showByDefault")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
