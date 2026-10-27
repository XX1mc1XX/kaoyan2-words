# -*- coding: utf-8 -*-
"""三个增强：左滑撤销条 / 认识的词 7 天后重新出现 / 进度导出导入。"""
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


# ============ A. 撤销条：HTML + CSS ============
rep("</main>",
    """</main>
<div class="undo-bar hidden" id="undoBar">
  <span id="undoText">已认识</span>
  <button id="undoBtn">撤销</button>
</div>""", "撤销条 HTML")

rep(".storage-warn{",
    """.undo-bar{position:fixed;left:50%;transform:translateX(-50%);
  bottom:calc(76px + env(safe-area-inset-bottom));background:var(--ink);color:var(--bg);
  border-radius:12px;padding:10px 12px 10px 14px;display:flex;gap:12px;align-items:center;
  font-size:13.5px;box-shadow:0 6px 24px rgba(0,0,0,.3);z-index:60;max-width:92vw}
.undo-bar button{border:0;background:var(--brand);color:#fff;border-radius:8px;
  padding:7px 13px;font:inherit;font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap}
.storage-warn{""", "撤销条 CSS")

# ============ B. 认识的词 7 天后重新出现 ============
rep("  if (known) st.mastered = true;\n  else { st.w = (st.w || 0) + 1; st.mastered = false; }",
    "  if (known) { st.mastered = true; st.due = todayTs() + 7 * DAY; }\n"
    "  else { st.w = (st.w || 0) + 1; st.mastered = false; st.due = 0; }",
    "认识后 7 天到期")

rep("  const pending = chapterSlice(ch).filter(w => !isMastered(w));",
    """  const now = todayTs();
  // 未掌握的照常出现；已掌握但到了 7 天复习期的，也重新出现
  const pending = chapterSlice(ch).filter(w => {
    if (!isMastered(w)) return true;
    const st = state[w.word];
    return !!(st && st.due && st.due <= now);
  });""", "到期词重新进队列")

# ============ C. 撤销逻辑 ============
rep("  if (known) {\n    // 移出当前队列：进度条总数同步减少，下一个词自动顶上原位",
    "  if (known) {\n    showUndo(word);\n    // 移出当前队列：进度条总数同步减少，下一个词自动顶上原位",
    "左滑后显示撤销条")

rep("let touchStart = null;",
    """let undoTimer = null, undoWord = null;
function showUndo(word) {
  undoWord = word;
  $('undoText').textContent = '已认识：' + word.word;
  $('undoBar').classList.remove('hidden');
  clearTimeout(undoTimer);
  undoTimer = setTimeout(() => { $('undoBar').classList.add('hidden'); undoWord = null; }, 5000);
}
function doUndo() {
  const word = undoWord;
  if (!word) return;
  const st = state[word.word];
  if (st) { st.mastered = false; st.due = 0; state[word.word] = st; save(LS_STATE, state); }
  queue.splice(Math.min(idx, queue.length), 0, word);
  $('undoBar').classList.add('hidden');
  clearTimeout(undoTimer);
  undoWord = null;
  revealed = null;
  savePos();
  renderStudy();
  updateStats();
}
$('undoBtn').onclick = doUndo;
let touchStart = null;""", "撤销逻辑")

# ============ D. 导出 / 导入 ============
rep('<div class="panel"><button class="danger" id="resetAll">清空全部学习记录</button></div>',
    """<div class="panel">
      <div class="panel-title">进度备份</div>
      <div class="daily">
        <button id="exportProgress">导出进度</button>
        <button id="importProgress">导入进度</button>
      </div>
      <div class="note">换手机、清缓存前先导出。导入会覆盖当前进度。</div>
      <input type="file" id="importFile" accept=".json" class="hidden">
    </div>
    <div class="panel"><button class="danger" id="resetAll">清空全部学习记录</button></div>""",
    "备份面板 HTML")

rep("$('resetAll').onclick = () => {",
    """$('exportProgress').onclick = () => {
  const dump = {
    v: 1,
    exported: new Date().toISOString(),
    state,
    chapterData,
    conf: { autoShow: conf.autoShow, deck: conf.deck, chapter: conf.chapter || 0 }
  };
  const blob = new Blob([JSON.stringify(dump)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'kaoyan-progress-' + new Date().toISOString().slice(0, 10) + '.json';
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
};
$('importProgress').onclick = () => $('importFile').click();
$('importFile').onchange = event => {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const d = JSON.parse(reader.result);
      if (d.state && typeof d.state === 'object') { state = d.state; save(LS_STATE, state); }
      if (d.chapterData && typeof d.chapterData === 'object') { chapterData = d.chapterData; save('ky_chapter_v1', chapterData); }
      if (d.conf) {
        conf.autoShow = !!d.conf.autoShow;
        if (d.conf.deck && DECKS[d.conf.deck]) { activeDeck = d.conf.deck; conf.deck = d.conf.deck; }
        conf.chapter = d.conf.chapter || 0;
        save(LS_CONF, conf);
      }
      updateDeckMeta();
      renderChapters();
      loadChapter(conf.chapter || 0);
      updateStats();
      alert('进度已导入');
    } catch (e) {
      alert('文件格式不对，导入失败');
    } finally {
      event.target.value = '';
    }
  };
  reader.readAsText(file);
};
$('resetAll').onclick = () => {""", "导出导入逻辑")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
