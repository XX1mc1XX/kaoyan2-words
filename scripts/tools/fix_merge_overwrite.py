# -*- coding: utf-8 -*-
"""修 codex 复核的合并覆盖问题：所有本地写入补时间戳；章节按时间合并；重置/导入可强制覆盖云端；同步不跳词不空转。"""
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


# 1. 词表「恢复」按钮补时间戳
rep("      if (st) { st.mastered = false; state[word.word] = st; save(LS_STATE, state); }",
    "      if (st) { st.mastered = false; st.due = 0; st.t = Date.now(); state[word.word] = st; save(LS_STATE, state); }",
    "词表恢复补时间戳")

# 2. 打乱顺序前清掌握（两处）补时间戳
rep("    for (const w of slice) if (state[w.word]) state[w.word].mastered = false;",
    "    for (const w of slice) if (state[w.word]) { state[w.word].mastered = false; state[w.word].t = Date.now(); }",
    "打乱清掌握补时间戳")

rep("""    for (const w of chapterSlice(curChapter)) {
      if (state[w.word]) state[w.word].mastered = false;
    }""",
    """    for (const w of chapterSlice(curChapter)) {
      if (state[w.word]) { state[w.word].mastered = false; state[w.word].t = Date.now(); }
    }""", "重背清掌握补时间戳")

# 3. 章节记录也带时间戳
rep("""  chapterData[key].pos = idx;
  chapterData[key].posWord = idx < queue.length ? queue[idx].word : null;""",
    """  chapterData[key].pos = idx;
  chapterData[key].posWord = idx < queue.length ? queue[idx].word : null;
  chapterData[key].t = Date.now();""", "savePos 打时间戳")

rep("""  if (mode === 'shuffle') {
    rec = chapterData[key] = { order: shuffleByWeight(pending).map(w => w.word), pos: 0, shuffled: true };""",
    """  if (mode === 'shuffle') {
    rec = chapterData[key] = { order: shuffleByWeight(pending).map(w => w.word), pos: 0, shuffled: true, t: Date.now() };""",
    "打乱记录时间戳")

rep("""  } else if (mode === 'natural' || !rec || !Array.isArray(rec.order)) {
    rec = chapterData[key] = { order: naturalOrder(pending).map(w => w.word), pos: 0 };""",
    """  } else if (mode === 'natural' || !rec || !Array.isArray(rec.order)) {
    rec = chapterData[key] = { order: naturalOrder(pending).map(w => w.word), pos: 0, t: Date.now() };""",
    "原序记录时间戳")

# 4. 章节合并改成按时间
rep("""    const pa = (a.order || []).length ? (a.pos || 0) : 0;
    const pb = (b.order || []).length ? (b.pos || 0) : 0;
    out[k] = pa >= pb ? a : b;""",
    """    // 按最后修改时间取，退回按进度位置
    const ta = a.t || 0, tb = b.t || 0;
    if (ta !== tb) { out[k] = tb > ta ? b : a; continue; }
    const pa = (a.order || []).length ? (a.pos || 0) : 0;
    const pb = (b.order || []).length ? (b.pos || 0) : 0;
    out[k] = pa >= pb ? a : b;""", "章节按时间合并")

# 5. 重置全部 / 导入：记录强制覆盖点，同步时以本机为准
rep("""  state = {};
  save(LS_STATE, state);
  chapterData = {};""",
    """  state = {};
  save(LS_STATE, state);
  conf.forceAt = Date.now();     // 本地清空过，同步时以本机为准，避免云端把词补回来
  save(LS_CONF, conf);
  chapterData = {};""", "重置记录强制点")

rep("""      if (d.conf && typeof d.conf === 'object') {""",
    """      conf.forceAt = Date.now();   // 导入是覆盖式操作
      save(LS_CONF, conf);
      if (d.conf && typeof d.conf === 'object') {""", "导入记录强制点")

# 6. 同步：强制覆盖 / 无变化不写
rep("""    const remote = await api('/state');
    const local = snapshot();
    if (!remote.payload) {""",
    """    const remote = await api('/state');
    const local = snapshot();
    // 本机刚清空或刚导入：直接覆盖云端，不参与合并
    if (local.conf.forceAt && local.conf.forceAt > (remote.updatedAt || 0)) {
      await putState(local);
      if (!quiet) authSay('已把本机进度同步到云端', 'ok');
      return;
    }
    if (!remote.payload) {""", "同步支持强制覆盖")

rep("""      const merged = mergeSnapshots(local, remote.payload);
      const changedLocally = !sameJson(merged.state, local.state) || !sameJson(merged.chapterData, local.chapterData);
      if (changedLocally) applySnapshot(merged);
      await putState(merged);
      if (!quiet) authSay(changedLocally ? '已合并云端进度' : '进度已同步', 'ok');""",
    """      const merged = mergeSnapshots(local, remote.payload);
      const changedLocally = !sameJson(merged.state, local.state) || !sameJson(merged.chapterData, local.chapterData);
      if (changedLocally) applySnapshot(merged);
      // 没有变化就不要回写，避免每 40 秒空转一次写库
      if (!sameJson(merged, remote.payload)) await putState(merged);
      else lastSyncAt = remote.updatedAt || lastSyncAt;
      if (!quiet) authSay(changedLocally ? '已合并云端进度' : '进度已同步', 'ok');""", "无变化不回写")

# 7. 登录后同步不要静默，否则状态卡在「正在同步…」
rep("""  authSay('正在同步…');
  scheduleCloudSync(0);""",
    """  authSay('正在同步…');
  setTimeout(() => syncNow(false), 0);""", "登录后同步给反馈")

# 8. 应用云端快照时不要跳词
rep("""    activeDeck = DECKS[conf.deck] ? conf.deck : 'core';
    $('deckSelect').value = activeDeck;
    updateDeckMeta();
    loadChapter((conf.deckChapter && conf.deckChapter[activeDeck]) || 0);
    renderChapters();
  }
  updateStats();
  renderList();""",
    """    activeDeck = DECKS[conf.deck] ? conf.deck : 'core';
    $('deckSelect').value = activeDeck;
    updateDeckMeta();
  }
  // 同步回来的数据不能让用户正在背的词跳走：记住当前词，重载后再定位回去
  const keepWord = (queue[idx] && queue[idx].word) || null;
  loadChapter((conf.deckChapter && conf.deckChapter[activeDeck]) || curChapter);
  if (keepWord) {
    const j = queue.findIndex(w => w.word === keepWord);
    if (j >= 0) { idx = j; savePos(); renderStudy(); }
  }
  renderChapters();
  updateStats();
  renderList();""", "同步不跳词")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
