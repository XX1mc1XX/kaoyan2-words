# -*- coding: utf-8 -*-
"""修 codex 报的 UI 问题：touchcancel 复位 / 翻面按钮只作用当前卡 / 记住章节 /
存储失败提示 / 搜索防抖 / 点按容差 / iOS 边缘手势 / 已掌握库右滑移出。"""
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


# 1. touchcancel：把卡片从半滑状态复位
rep("card.addEventListener('touchcancel', () => { touchStart = null; }, { passive: true });",
    """card.addEventListener('touchcancel', () => {
  touchStart = null;
  card.style.transition = 'transform .16s ease, opacity .16s ease, border-color .16s ease';
  card.style.transform = '';
  card.style.opacity = '';
  card.style.borderColor = '';
  setTimeout(() => { card.style.transition = ''; }, 220);
}, { passive: true });""", "touchcancel 复位卡片")

# 2. 顶部按钮只翻当前卡（原来改的是持久化全局开关）
rep("""$('meaningToggle').onclick = () => {
  conf.autoShow = !conf.autoShow;
  save(LS_CONF, conf);
  revealed = null;
  renderStudy();
};""",
    "$('meaningToggle').onclick = toggleMeaning;", "翻面按钮只作用当前卡")

# 3. 按钮文字反映当前卡状态
rep("""  $('meaningToggle').textContent = conf.autoShow ? '始终显示' : '点击翻面';
  $('meaningToggle').setAttribute('aria-pressed', String(!!conf.autoShow));""",
    """  $('meaningToggle').textContent = show ? '隐藏释义' : '点击翻面';
  $('meaningToggle').setAttribute('aria-pressed', String(show));""", "翻面按钮文案跟随当前卡")

# 4. 记住上次所在章节
rep("""function gotoChapter(i) {
  savePos();
  loadChapter(i);
}""",
    """function gotoChapter(i) {
  savePos();
  conf.chapter = i;
  save(LS_CONF, conf);
  loadChapter(i);
}""", "切章时记住章节")

rep("loadChapter(0);\nrenderChapters();", "loadChapter(conf.chapter || 0);\nrenderChapters();", "启动恢复上次章节")

# 5. 点按容差放宽：6px -> 12px，400ms -> 600ms
rep("  if (Math.abs(dx) > 6 || Math.abs(dy) > 6) touchStart.moved = true;",
    "  if (Math.abs(dx) > 12 || Math.abs(dy) > 12) touchStart.moved = true;", "点按抖动容差 6->12px")
rep("  if (!moved && elapsed < 400) {",
    "  if (!moved && elapsed < 600) {", "点按时限 400->600ms")

# 6. iOS 左边缘返回手势：起点太靠边就不判横滑
rep("""  const absX = Math.abs(dx), absY = Math.abs(dy);
  const word = queue[idx];
  if (word && absX >= 34 && absX >= absY) {""",
    """  const absX = Math.abs(dx), absY = Math.abs(dy);
  const word = queue[idx];
  if (word && absX >= 34 && absX >= absY && startX > 26) {""", "左边缘 26px 内不判横滑")

rep("""  const elapsed = Date.now() - touchStart.time;
  const moved = touchStart.moved;
  touchStart = null;""",
    """  const elapsed = Date.now() - touchStart.time;
  const moved = touchStart.moved;
  const startX = touchStart.x;
  touchStart = null;""", "记录起手 x 坐标")

# 7. 已掌握库里右滑：取消掌握后同步移出当前列表
rep("""  } else if (navigator.vibrate) {
    navigator.vibrate(22);                             // 不认识：留在当前词，只震一下
  }""",
    """  } else {
    if (activeDeck === 'mastered') {                   // 已掌握库里取消掌握 -> 立即移出列表
      queue = queue.filter(w => w.word !== word.word);
      if (idx >= queue.length) idx = Math.max(queue.length - 1, 0);
      revealed = null;
      savePos();
      renderStudy();
    }
    if (navigator.vibrate) navigator.vibrate(22);
  }""", "已掌握库右滑移出列表")

# 8. 搜索防抖
rep("$('searchInput').oninput = event => { searchText = event.target.value; renderList(); };",
    """let searchTimer = null;
$('searchInput').oninput = event => {
  searchText = event.target.value;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(renderList, 120);
};""", "搜索防抖 120ms")

# 9. 存储失败要提示，而不是静默吞掉
rep("const save = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} };",
    """let storageWarned = false;
const save = (key, value) => {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (e) {
    if (!storageWarned) {
      storageWarned = true;
      const el = document.getElementById('storageWarn');
      if (el) el.classList.remove('hidden');
    }
  }
};""", "存储失败提示")

# 10. 加提示条元素
rep("</header>",
    """</header>
<div class="storage-warn hidden" id="storageWarn">进度保存失败：浏览器存储已满或处于隐私模式，刷新后可能丢失。</div>""", "存储警告条 HTML")

rep(".deck-bar{",
    """.storage-warn{padding:8px 14px;background:var(--bad);color:#fff;font-size:12.5px;line-height:1.5;flex-shrink:0}
.deck-bar{""", "存储警告条样式")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
