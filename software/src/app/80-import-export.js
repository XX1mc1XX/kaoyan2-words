const IMPORT_MAX_BYTES = 5 * 1024 * 1024;
function newImportOperationId() {
  try {
    if (crypto && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  } catch {}
  return 'import-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 14);
}
function prepareImport(d) {
  if (!objectRecord(d)) throw new Error('bad file');
  const now = Date.now();
  let nextState = state;
  let nextChapters = chapterData;
  let nextDaily = daily;
  let nextConf = { ...conf };
  // 导入是「用这份替换本机进度」。旧记录里没有的词必须写成墓碑，
  // 否则下次同步会被云端按「云端有你没有」原样拼回来。
  if (d.v !== undefined && Number(d.v) !== 1) throw new Error('unsupported backup version');
  if (!['state', 'chapterData', 'daily', 'conf'].some(key => Object.prototype.hasOwnProperty.call(d, key))) throw new Error('empty backup');
  if (d.state !== undefined) {
    if (!objectRecord(d.state)) throw new Error('bad state');
    const incoming = validateStateStore(d.state, now);
    for (const [name, rec] of Object.entries(incoming)) {
      if (!rec.del && !rec.t) incoming[name] = { ...rec, t: now };
    }
    for (const name of Object.keys(state)) {
      if (!Object.prototype.hasOwnProperty.call(incoming, name)) incoming[name] = tombstone(now);
    }
    nextState = incoming;
  }
  if (d.chapterData !== undefined) {
    if (!objectRecord(d.chapterData)) throw new Error('bad chapters');
    const incoming = validateChapterStore(d.chapterData, now);
    for (const [key, rec] of Object.entries(incoming)) {
      if (!rec.del && !rec.t) incoming[key] = { ...rec, t: now };
    }
    for (const key of Object.keys(chapterData)) {
      if (!Object.prototype.hasOwnProperty.call(incoming, key)) incoming[key] = tombstone(now);
    }
    nextChapters = incoming;
  }
  if (d.daily !== undefined) {
    if (!objectRecord(d.daily)) throw new Error('bad daily');
    nextDaily = validateDailyStore(d.daily, now);
  }
  if (d.conf !== undefined) {
    if (!objectRecord(d.conf)) throw new Error('bad conf');
    nextConf = validateConfStore(d.conf);
    if (Object.prototype.hasOwnProperty.call(d.conf, 'icon')) nextConf.iconAt = now;
    nextConf.progressAt = now;
  }
  // 导入是覆盖：云端多出来的词要让服务端补墓碑，否则会被合并回来。
  nextConf.overwritePending = true;
  nextConf.overwriteMode = 'import';
  nextConf.importStartedAt = now;
  nextConf.importOperationId = newImportOperationId();
  // 导入文件的旧服务端 fence 不可信；由 Worker 为本次 import 建立新 fence。
  nextConf.resetAt = 0;
  delete nextConf.serverFenceAt;
  delete nextConf.serverFenceMode;
  delete nextConf.serverFenceOperationId;
  const deck = Object.prototype.hasOwnProperty.call(DECKS, nextConf.deck) ? nextConf.deck : 'core';
  const chapter = Math.max(0, Number(nextConf.deckChapter[deck]) || 0);
  nextConf.deck = deck;
  nextConf.chapter = chapter;
  nextConf.deckChapter = { ...(nextConf.deckChapter || {}), [deck]: chapter };
  return { state: nextState, chapterData: nextChapters, daily: nextDaily, conf: nextConf };
}
$('importFile').onchange = event => {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  // 几十 MB 的 JSON.parse 会把主线程卡死且没有进度条可取消，先按体积挡掉
  if (file.size > IMPORT_MAX_BYTES) {
    alert('文件超过 5MB，不像是进度备份文件。');
    event.target.value = '';
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    const beforeImport = { state, chapterData, daily, conf, activeDeck, curChapter };
    try {
      const next = prepareImport(JSON.parse(reader.result));
      if (!commitStores(next)) {
        alert('导入失败：浏览器存储空间不足，原进度已保留。');
        return;
      }
      state = next.state;
      chapterData = next.chapterData;
      daily = next.daily;
      conf = next.conf;
      activeDeck = conf.deck;
      $('deckSelect').value = activeDeck;
      updateDeckMeta();
      renderChapters();
      loadChapter(resumePosition());
      conf.deckChapter[activeDeck] = curChapter;
      conf.chapter = curChapter;
      // 队列重建后的真实落点也要一起保存；这里若失败，四块数据会回滚到导入前。
      if (!commitStores({ state, chapterData, daily, conf })) {
        state = beforeImport.state;
        chapterData = beforeImport.chapterData;
        daily = beforeImport.daily;
        conf = beforeImport.conf;
        activeDeck = beforeImport.activeDeck;
        curChapter = beforeImport.curChapter;
        commitStores(beforeImport);
        $('deckSelect').value = activeDeck;
        updateDeckMeta();
        renderChapters();
        loadChapter(curChapter);
        updateStats();
        renderList();
        renderIconSettings();
        syncFavicon(currentIcon());
        alert('导入失败：浏览器存储空间不足，原进度已保留。');
        return;
      }
      syncPaused = false;
      if (authUser) scheduleCloudSync(0);
      updateStats();
      renderList();
      renderAuth();
      renderIconSettings();
      syncFavicon(currentIcon());
      alert('进度已导入');
    } catch (e) {
      alert('文件格式不对，导入失败，原进度已保留。');
    } finally {
      event.target.value = '';
    }
  };
  reader.onerror = () => {
    event.target.value = '';
    alert('读取备份文件失败，原进度已保留。');
  };
  reader.readAsText(file);
};
$('resetAll').onclick = () => {
  if (!confirm('确定清空全部学习记录？此操作不可恢复。')) return;
  // 删除写成墓碑（{ del: 1, t }），不能只把本机清空：
  // 逐词合并分不清「这台设备没学过」和「用户删掉了」，
  // 后者会被另一台设备按「云端有、本机没有」原样拼回来。
  const now = Date.now();
  const nextState = {};
  for (const name of Object.keys(state)) nextState[name] = tombstone(now);
  const nextChapters = {};
  for (const key of Object.keys(chapterData)) nextChapters[key] = tombstone(now);
  const nextDaily = {};
  for (const key of Object.keys(daily)) nextDaily[key] = tombstone(now);
  const nextConf = { ...conf, overwritePending: true, overwriteMode: 'clear', resetAt: now };
  delete nextConf.importStartedAt;
  delete nextConf.importOperationId;
  delete nextConf.serverFenceOperationId;
  // 四块数据必须一次提交；任何一块配额失败都要保留清空前状态。
  if (!commitStores({ state: nextState, chapterData: nextChapters, daily: nextDaily, conf: nextConf })) {
    alert('清空失败：浏览器存储空间不足，原进度已保留。');
    return;
  }
  state = nextState;
  chapterData = nextChapters;
  daily = nextDaily;
  conf = nextConf;
  syncPaused = false;
  if (authUser) scheduleCloudSync(0);
  loadChapter(curChapter, 'natural');
  savePos();
  updateStats();
};
window.addEventListener('keydown', event => {
  if (event.repeat) return;
  const active = document.activeElement;
  if (active && (['INPUT','TEXTAREA','SELECT'].includes(active.tagName) || active.isContentEditable)) return;
  if (event.altKey || event.ctrlKey || event.metaKey) return;
  if (active && active.closest && active.closest('button, a, summary, [role="button"], [contenteditable="true"]')) return;
  // 登录弹窗开着时不要动背后的卡片
  if (!$('authModal').classList.contains('hidden')) return;
  // 详情面板开着时，方向键不该继续 mark / restore 底层卡片
  if (!$('detailMask').classList.contains('hidden')) return;
  if ($('viewStudy').classList.contains('hidden')) return;
  if (event.code === 'Space') {
    if (active && active.tagName === 'BUTTON') return;   // 让按钮自己响应空格
    event.preventDefault();
    toggleMeaning();
    return;
  }
  if (event.key === 'ArrowUp') { event.preventDefault(); navigate(-1); return; }
  if (event.key === 'ArrowDown') { event.preventDefault(); navigate(1); return; }
  if (event.key === 'ArrowLeft') { event.preventDefault(); applyWordAction(queue[idx], 'left'); return; }
  if (event.key === 'ArrowRight') { event.preventDefault(); applyWordAction(queue[idx], 'right'); return; }
});
updateDeckMeta();
loadChapter(resumePosition());
renderChapters();
// 统计和图标设置在各自页面/面板打开时才看得见，启动时算它们是纯浪费 CPU
syncFavicon(currentIcon());
$('chapterSelect').onchange = event => gotoChapter(Number(event.target.value));
$('meaningToggle').onclick = () => {
  conf.showByDefault = !conf.showByDefault;
  save(LS_CONF, conf);
  revealed = null;
  renderStudy();
};
function toggleSpeakLang() {
  conf.speakLang = conf.speakLang === 'zh' ? 'en' : 'zh';
  refreshVoice();
  save(LS_CONF, conf);
  lastSpoken = '';          // 清掉去重标记，让 renderStudy 立刻用新语言念一次
  const warn = $('speakWarn');
  if (warn) warn.classList.add('hidden');   // 上一门语言的报错不该留到这一门
  renderStudy();
  // 中文释义走百度音频，只有单文件版没有代理时才依赖系统中文语音包
  if (conf.speakLang === 'zh' && !AUDIO_PROXY_READY && !zhVoice) {
    if (warn) {
      warn.textContent = '这个版本没有联网代理，中文释义要靠系统语音，请在系统设置里安装中文语音包。';
      warn.classList.remove('hidden');
    }
  }
}
// 朗读键：轻点开关，长按切换中英文。统一走 Pointer Events，移动超阈值就取消，
// 免得滑动页面时误切语言。
let speakPressAt = null;
let speakPressTimer = null;
let speakLongFired = false;
const speakBtn = $('speakToggle');
const cancelSpeakPress = () => {
  if (speakPressTimer) { clearTimeout(speakPressTimer); speakPressTimer = null; }
  speakPressAt = null;
};
speakBtn.addEventListener('contextmenu', event => event.preventDefault());
speakBtn.addEventListener('pointerdown', event => {
  if (typeof event.button === 'number' && event.button !== 0) return;
  speakLongFired = false;
  speakPressAt = { x: event.clientX, y: event.clientY };
  clearTimeout(speakPressTimer);
  speakPressTimer = setTimeout(() => {
    speakPressTimer = null;
    speakPressAt = null;
    speakLongFired = true;
    toggleSpeakLang();
    if (navigator.vibrate) navigator.vibrate(18);
  }, 550);
});
speakBtn.addEventListener('pointermove', event => {
  if (!speakPressAt) return;
  if (Math.abs(event.clientX - speakPressAt.x) > 8 || Math.abs(event.clientY - speakPressAt.y) > 8) cancelSpeakPress();
});
// 触摸长按后浏览器不一定补发 click，隔一拍再清标志，免得误吞下一次轻点
const releaseSpeakPress = () => {
  cancelSpeakPress();
  if (speakLongFired) setTimeout(() => { speakLongFired = false; }, 350);
};
speakBtn.addEventListener('pointerup', releaseSpeakPress);
speakBtn.addEventListener('pointercancel', releaseSpeakPress);
speakBtn.addEventListener('pointerleave', cancelSpeakPress);
speakBtn.addEventListener('click', event => {
  if (speakLongFired) { speakLongFired = false; event.preventDefault(); return; }
  cancelSpeakPress();
  conf.speak = !conf.speak;
  save(LS_CONF, conf);
  if (conf.speak) { const w = queue[idx]; if (w) speak(w); }
  renderStudy();
});
// 点红点：权重 -1，用于误判右滑后回退
$('weightBadge').onclick = event => {
  event.stopPropagation();
  lowerWeight(queue[idx]);
};
// 点单词朗读；阻止冒泡避免触发卡片的翻面
$('word').addEventListener('click', event => {
  event.stopPropagation();
  if (studyLoading) return;
  if (Date.now() - wordTouchedAt < 500) return;   // touchend 已读过，避免读两遍
  const w = queue[idx];
  if (w) speak(w);
});
let wordTouchedAt = 0;
$('deckSelect').onchange = event => switchDeck(event.target.value);

