# -*- coding: utf-8 -*-
"""彻底移除 autoShow 机制：只保留「当前词是否翻面」一个状态，翻词自动收起。"""
import io

P = r"c:\my_project\单词\software\template.html"
t = io.open(P, encoding="utf-8").read()
log = []


def rep(old, new, label, required=True):
    global t
    if old in t:
        t = t.replace(old, new, 1)
        log.append("OK    " + label)
    else:
        log.append(("MISS  " if required else "skip  ") + label)


# 1. conf 里删掉 autoShow，并主动清掉 localStorage 里的旧值
rep("let conf = Object.assign({ autoShow: false, deck: 'core' }, load(LS_CONF, {}));",
    "let conf = Object.assign({ deck: 'core' }, load(LS_CONF, {}));\ndelete conf.autoShow;   // 旧版本遗留的全局开关，彻底废弃",
    "conf 移除 autoShow")

# 2. revealed 改回普通布尔
rep("let revealed = null;", "let revealed = false;", "revealed 改布尔")

# 3. 显示判断只看 revealed
rep("  const show = revealed === null ? !!conf.autoShow : revealed;",
    "  const show = revealed;", "显示判断只看 revealed")

# 4. 切换就是取反
rep("""function toggleMeaning() {
  const current = revealed === null ? !!conf.autoShow : revealed;
  revealed = !current;
  renderStudy();
}""",
    """function toggleMeaning() {
  revealed = !revealed;
  renderStudy();
}""", "toggleMeaning 简化")

# 5. 所有重置点改成 false
t = t.replace("revealed = null;", "revealed = false;")
log.append("OK    revealed 重置点统一为 false")

# 6. 导出/导入里的 autoShow 去掉
rep("    conf: { autoShow: conf.autoShow, deck: conf.deck, chapter: conf.chapter || 0 }",
    "    conf: { deck: conf.deck, chapter: conf.chapter || 0 }", "导出移除 autoShow")
rep("        conf.autoShow = !!d.conf.autoShow;\n", "", "导入移除 autoShow")

# 7. 隐藏时那行占位文字缩小、不抢戏
rep("    meaning.textContent = '点卡片翻面看中文';",
    "    meaning.textContent = '点一下看释义';", "占位文案精简")
rep(".meaning-placeholder{font-size:14px;color:var(--muted);font-weight:400}",
    ".meaning-placeholder{font-size:12px;color:var(--muted);font-weight:400;opacity:.75}", "占位文字更小")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
print("残留 autoShow:", t.count("autoShow"), "| 残留 revealed = null:", t.count("revealed = null"))
