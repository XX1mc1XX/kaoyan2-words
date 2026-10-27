# -*- coding: utf-8 -*-
"""精简学习页 + 权重可视化：卡片显示「错 N 次」，右滑实时闪，顶部改为本章进度。"""
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


# --- 1. 卡片徽章区：优先级 + 权重 ---
rep('      <span class="priority b" id="priorityBadge">B 次重点</span>',
    """      <div class="badges">
        <span class="priority b" id="priorityBadge">B 次重点</span>
        <span class="weight-badge hidden" id="weightBadge"></span>
      </div>""", "徽章区 HTML")

rep(".priority{font-size:15px;",
    """.badges{display:flex;gap:6px;align-items:center;justify-content:center;flex-wrap:wrap}
.weight-badge{font-size:11.5px;font-weight:800;color:var(--bad);
  background:color-mix(in srgb,var(--bad) 15%,transparent);border-radius:999px;padding:6px 10px;line-height:1}
@keyframes pulseW{0%{transform:scale(1)}40%{transform:scale(1.3)}100%{transform:scale(1)}}
.weight-badge.pulse{animation:pulseW .45s ease}
.priority{font-size:15px;""", "徽章区 CSS")

# --- 2. 顶部「优先级 #N」改成本章掌握进度（更有用，且不重复）---
rep("  $('wordId').textContent = '优先级 #' + word.priority_rank;",
    """  const slice = chapterSlice(curChapter);
  const done = slice.filter(w => isMastered(w)).length;
  $('wordId').textContent = '本章 ' + done + '/' + slice.length;""", "顶部改为本章进度")

# --- 3. 渲染时显示当前词权重 ---
rep("  setPriority($('priorityBadge'), word.priority);",
    """  setPriority($('priorityBadge'), word.priority);
  const wt = weightOf(word);
  const wb = $('weightBadge');
  wb.textContent = wt > 0 ? '错 ' + wt + ' 次' : '';
  wb.classList.toggle('hidden', wt === 0);""", "渲染权重徽章")

# --- 4. 右滑时实时闪一下，让人看见权重变了 ---
rep("""    if (navigator.vibrate) navigator.vibrate(22);
  }""",
    """    if (navigator.vibrate) navigator.vibrate(22);
    // 实时反馈：当前词还在屏幕上，直接把权重亮出来并闪一下
    if (queue[idx] && queue[idx].word === word.word) {
      const wb = $('weightBadge');
      wb.textContent = '错 ' + st.w + ' 次';
      wb.classList.remove('hidden');
      wb.classList.remove('pulse');
      void wb.offsetWidth;
      wb.classList.add('pulse');
    }
  }""", "右滑实时权重反馈")

# --- 5. 精简：小屏隐藏品牌名，压缩词库栏 ---
rep("@media (max-width:430px){",
    "@media (max-width:430px){.brand{display:none}", "小屏隐藏品牌名")

rep(".deck-bar{display:flex;align-items:center;gap:8px;padding:7px 12px;",
    ".deck-bar{display:flex;align-items:center;gap:8px;padding:4px 12px;", "词库栏压缩")

# --- 6. 统计页补一句权重怎么起作用 ---
rep("<b>S 必背</b> → <b>A 重点</b> → <b>B 次重点</b><br>",
    "<b>S 必背</b> → <b>A 重点</b> → <b>B 次重点</b><br>"
    "右滑（不认识）会给这个词加权重，卡片上显示「错 N 次」；点「打乱本章」时权重越高越可能排前面，"
    "但不会强制置顶。<br>", "统计页补权重说明")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
