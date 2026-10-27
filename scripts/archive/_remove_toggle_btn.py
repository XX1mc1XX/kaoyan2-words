# -*- coding: utf-8 -*-
"""去掉顶部翻面按钮（点卡片即可），并让释义至少保留 2 个义项。"""
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


# 1. 移除顶部按钮
rep('      <button class="meaning-toggle" id="meaningToggle" aria-pressed="false">点击翻面</button>\n', "", "移除顶部翻面按钮")

# 2. study-head 两列就够
rep(".study-head{display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:6px;align-items:center;flex-shrink:0}",
    ".study-head{display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px;align-items:center;flex-shrink:0}",
    "study-head 改两列")

# 3. 清掉按钮相关 JS
rep("""  $('meaningToggle').textContent = show ? '隐藏释义' : '点击翻面';
  $('meaningToggle').setAttribute('aria-pressed', String(show));
""", "", "移除按钮文案更新", )
rep("""    $('meaningToggle').classList.add('hidden');
""", "", "移除隐藏按钮调用", )
rep("""  $('meaningToggle').classList.remove('hidden');
""", "", "移除显示按钮调用", )
rep("$('meaningToggle').onclick = toggleMeaning;\n", "", "移除按钮事件")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
print("残留 meaningToggle:", t.count("meaningToggle"))
