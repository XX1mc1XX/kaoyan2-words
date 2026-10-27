# -*- coding: utf-8 -*-
"""一次性打完剩余改动：去框、已掌握分区、进度拖动、打乱按钮、释义按钮改全局。"""
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


# --- 1. 去掉「考查形式」方框和标题 ---
rep(".forms-title{padding:4px 9px;background:var(--brand);color:#fff;font-size:11.5px;font-weight:800;line-height:1.35;letter-spacing:.08em}\n", "", "CSS forms-title", False)
rep(".forms-box{width:min(100%,460px);border:1px solid var(--line);border-radius:11px;overflow:hidden;background:color-mix(in srgb,var(--bg) 58%,var(--card))}",
    ".forms-box{width:min(100%,460px)}", "CSS forms-box 去边框", False)
rep('        <div class="forms-title">考查形式</div>\n', "", "HTML forms-title", False)

# --- 2. 恢复按钮样式 ---
rep(".list-priority{",
    ".restore-btn{border:1px solid var(--line);background:transparent;color:var(--brand);border-radius:8px;"
    "padding:4px 8px;font:inherit;font-size:11px;cursor:pointer;white-space:nowrap}\n.list-priority{",
    "CSS restore-btn")

# --- 3. 词表：已掌握单独分区 ---
rep("""  for (const word of deckWords()) {
    const p = (word.priority || 'C').charAt(0);
    if (priorityFilter !== 'all' && p !== priorityFilter) continue;""",
    """  for (const word of deckWords()) {
    const mastered = isMastered(word);
    if (priorityFilter === 'mastered') {
      if (!mastered) continue;
    } else {
      if (mastered) continue;
      const p = (word.priority || 'C').charAt(0);
      if (priorityFilter !== 'all' && p !== priorityFilter) continue;
    }""", "词表 已掌握过滤")

rep("    const badge = document.createElement('span'); badge.className = 'list-priority priority ' + priorityClass(word.priority); badge.textContent = word.priority;",
    """    let badge;
    if (mastered) {
      badge = document.createElement('button');
      badge.className = 'restore-btn';
      badge.textContent = '恢复';
      badge.onclick = () => {
        const st = state[word.word];
        if (st) { st.mastered = false; state[word.word] = st; save(LS_STATE, state); }
        renderList(); updateStats(); loadChapter(curChapter);
      };
    } else {
      badge = document.createElement('span');
      badge.className = 'list-priority priority ' + priorityClass(word.priority);
      badge.textContent = word.priority;
    }""", "词表 恢复按钮")

# --- 4. 释义按钮：改为全局「始终显示 / 点击翻面」 ---
rep("$('meaningToggle').onclick = toggleMeaning;",
    """$('meaningToggle').onclick = () => {
  conf.autoShow = !conf.autoShow;
  save(LS_CONF, conf);
  revealed = null;
  renderStudy();
};""", "释义按钮改全局")

# --- 5. 进度条可拖动 + 打乱本章 ---
rep("$('prevWord').onclick = () => navigate(-1);",
    """$('progressBar').onchange = event => {
  if (!queue.length) return;
  idx = Math.min(Math.max(Number(event.target.value), 0), queue.length - 1);
  revealed = null;
  savePos();
  renderStudy();
};
$('shuffleChapter').onclick = () => {
  const slice = chapterSlice(curChapter);
  if (slice.every(w => isMastered(w))) {
    if (!confirm('本章已全部掌握。打乱会清空掌握记录、重新背一遍，继续？')) return;
    for (const w of slice) if (state[w.word]) state[w.word].mastered = false;
    save(LS_STATE, state);
  }
  loadChapter(curChapter, true);
  updateStats();
};
$('prevWord').onclick = () => navigate(-1);""", "进度拖动 + 打乱绑定")

# --- 6. 删除统计页已废弃的 displayOpts 调用 ---
rep("renderDisplayOpts();\n", "", "移除 renderDisplayOpts 调用", False)

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
print("\n剩余检查：")
for k in ("forms-title", "考查形式", "displayOpts", "shuffleChapter", "restore-btn", "progressBar').max"):
    print(f"  {k}: {t.count(k)}")
