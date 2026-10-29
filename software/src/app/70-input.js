let touchStart = null;
let slideLock = false;     // 130ms 滑出动画期间不接受新的滑动判定，避免同一次滑动重复计分
let swipeFrame = 0;
let pendingSwipe = null;
const card = $('card');
const swipeStage = $('swipeStage');
const swipeTrack = $('swipeTrack');
const swipeLeftCard = $('swipeLeftCard');
const swipeRightCard = $('swipeRightCard');
const hideSwipeActions = () => {
  swipeStage.classList.remove('swiping-left', 'swiping-right');
};
// 边框提示用 class，不直接写 style.borderColor：后者每次都要重算样式
const clearSwipeHint = () => card.classList.remove('swipe-ok', 'swipe-bad');
// 最后一次 touchmove 排的 rAF 可能晚于 touchend 执行，会把已经复位的
// transform / opacity / 边框 class 又写回去，卡片就歪着停在半透明上。
// 抬手前先掐掉挂起的那一帧。
const settleSwipe = () => {
  if (swipeFrame) { cancelAnimationFrame(swipeFrame); swipeFrame = 0; }
  pendingSwipe = null;
};
card.addEventListener('touchstart', event => {
  if (event.target.closest && event.target.closest('.badges')) { touchStart = null; return; }
  if (event.touches.length !== 1) return;
  const t = event.touches[0];
  hideSwipeActions();
  touchStart = { x: t.clientX, y: t.clientY, time: Date.now(), moved: false };
}, { passive: true });
card.addEventListener('touchmove', event => {
  if (!touchStart || event.touches.length !== 1) return;
  const t = event.touches[0];
  const dx = t.clientX - touchStart.x, dy = t.clientY - touchStart.y;
  if (Math.abs(dx) > 12 || Math.abs(dy) > 12) touchStart.moved = true;
  const absX = Math.abs(dx), absY = Math.abs(dy);
  if (absX > absY) {
    // 横向：跟手位移 + 颜色提示，同时阻止浏览器横向手势
    event.preventDefault();
    pendingSwipe = { dx, absX };
    // 写样式合并进 rAF：每帧直接改 transform/borderColor 会反复触发样式重算
    if (!swipeFrame) {
      swipeFrame = requestAnimationFrame(() => {
        swipeFrame = 0;
        const p = pendingSwipe;
        if (!p) return;
        const shift = Math.max(-96, Math.min(96, p.dx));
        swipeTrack.style.transition = 'none';
        swipeTrack.style.transform = 'translateX(' + shift + 'px)';
        card.style.opacity = String(1 - Math.min(p.absX / 420, 0.28));
        card.classList.toggle('swipe-ok', p.absX > 30 && p.dx < 0);
        card.classList.toggle('swipe-bad', p.absX > 30 && p.dx > 0);
        swipeStage.classList.toggle('swiping-left', p.absX > 14 && p.dx < 0);
        swipeStage.classList.toggle('swiping-right', p.absX > 14 && p.dx > 0);
      });
    }
  } else if (absY > 10) {
    event.preventDefault();
    hideSwipeActions();
  }
}, { passive: false });
card.addEventListener('touchend', event => {
  // 长按已经打开了详情面板，这次抬手不要再当成点击翻面
  if (pressFired) { pressFired = false; touchStart = null; settleSwipe(); return; }
  if (event.target.closest && event.target.closest('.badges')) { touchStart = null; settleSwipe(); return; }
  if (!touchStart || event.changedTouches.length !== 1) { touchStart = null; return; }
  const t = event.changedTouches[0];
  const dx = t.clientX - touchStart.x, dy = t.clientY - touchStart.y;
  const elapsed = Date.now() - touchStart.time;
  const moved = touchStart.moved;
  const startX = touchStart.x;
  touchStart = null;
  settleSwipe();
  hideSwipeActions();
  if (slideLock) return;
  if (!moved && elapsed < 600) {
    swipeTrack.style.transition = 'none'; swipeTrack.style.transform = '';
    card.style.opacity = ''; clearSwipeHint(); card.style.transition = '';
    // 点词朗读，点别处翻面；起点落在单词上也只是「点」，不影响手势
    if (event.target.closest && event.target.closest('#word')) {
      const w = queue[idx];
      if (w && !studyLoading) { wordTouchedAt = Date.now(); speak(w); }
      return;
    }
    toggleMeaning();
    return;
  }
  const absX = Math.abs(dx), absY = Math.abs(dy);
  const word = queue[idx];
  if (word && absX >= 34 && absX >= absY && startX > 26) {
    const inMastered = activeDeck === 'mastered';
    const slideOut = (action, direction) => {
      slideLock = true;
      swipeTrack.style.transition = 'transform .13s ease-out';
      swipeTrack.style.transform = 'translateX(' + (direction < 0 ? '-110%' : '110%') + ')';
      card.style.transition = 'opacity .13s ease-out';
      card.style.opacity = '0';
      setTimeout(() => {
        swipeTrack.style.transition = 'none';
        swipeTrack.style.transform = '';
        card.style.transition = 'none';
        card.style.opacity = '';
        clearSwipeHint();
        // action 里一旦抛错，锁不复位就会把之后所有滑动都吞掉
        try { action(); } finally {
          slideLock = false;
          requestAnimationFrame(() => {
            swipeTrack.style.transition = '';
            card.style.transition = '';
          });
        }
      }, 130);
    };
    const bounce = () => {
      swipeTrack.style.transition = 'transform .16s ease';
      swipeTrack.style.transform = '';
      card.style.transition = 'opacity .16s ease, border-color .16s ease';
      card.style.opacity = '';
      card.classList.toggle('swipe-ok', dx < 0);
      card.classList.toggle('swipe-bad', dx > 0);
      setTimeout(() => {
        clearSwipeHint();
        card.style.transition = '';
        swipeTrack.style.transition = '';
      }, 260);
    };
    if (dx < 0) {
      // 左滑：普通库=认识；已认识库=降权重（停在当前词）
      if (inMastered) { bounce(); lowerWeight(word); }
      else slideOut(() => mark(word, true), dx);
    } else {
      // 右滑：普通库=不认识（权重+1）；已认识库=恢复原词库
      if (inMastered) slideOut(() => restoreMastered(word), dx);
      else { bounce(); mark(word, false); }
    }
    return;
  }
  // 纵向翻词：先弹回再翻
  swipeTrack.style.transition = 'transform .16s ease';
  swipeTrack.style.transform = '';
  card.style.transition = 'opacity .16s ease, border-color .16s ease';
  card.style.opacity = ''; clearSwipeHint();
  setTimeout(() => { swipeTrack.style.transition = ''; card.style.transition = ''; }, 200);
  if (absY >= 34 && absY > absX) navigate(dy < 0 ? 1 : -1);
}, { passive: true });
card.addEventListener('touchcancel', () => {
  touchStart = null;
  settleSwipe();
  hideSwipeActions();
  swipeTrack.style.transition = 'transform .16s ease';
  swipeTrack.style.transform = '';
  card.style.transition = 'opacity .16s ease, border-color .16s ease';
  card.style.opacity = '';
  clearSwipeHint();
  setTimeout(() => { swipeTrack.style.transition = ''; card.style.transition = ''; }, 220);
}, { passive: true });

// 桌面（鼠标）点卡片空白处翻面。触摸结束后浏览器还会补发一次 click，
// 用时间窗挡掉，手机上的手感完全不变。
let lastCardTouchAt = 0;
card.addEventListener('touchend', () => { lastCardTouchAt = Date.now(); }, { passive: true });
card.addEventListener('keydown', event => {
  if (event.key !== 'Enter' && event.key !== 'Space') return;
  if (!queue[idx] || studyLoading) return;
  event.preventDefault();
  speak(queue[idx], { notify: true });
});
card.addEventListener('click', event => {
  if (Date.now() - lastCardTouchAt < 800) return;
  if (pressFired) { pressFired = false; return; }   // 长按刚打开详情，别顺手翻面
  if (studyLoading || !queue[idx]) return;
  if (event.target.closest && event.target.closest('.badges')) return;   // 角标自带行为
  if (event.target.closest && event.target.closest('#word')) return;     // 点单词只朗读
  toggleMeaning();
});

// ---------- 长按看详情 ----------
// 内容顺序按考研优先级排：先给「值不值得花时间」（等级 + 真题次数），
// 再给释义和词形，最后是词典全义项（默认展开，省一次点击）。
// 详情按首字母分片：一次长按只拉那个首字母的那一片（十几 KB），不下载整表
const detailShards = {};
const detailPending = {};
function detailShardKey(word) {
  const first = String(word || '').charAt(0).toLowerCase();
  return /^[a-z]$/.test(first) ? first : '_';
}
function loadDetail(word) {
  const key = detailShardKey(word);
  if (detailShards[key]) return Promise.resolve(detailShards[key]);
  if (detailPending[key]) return detailPending[key];
  const assets = WEB_MODE && DATA_META && DATA_META.assets && DATA_META.assets.details;
  if (!assets) {
    // 单文件版：整表内联；detail 是「词 → 详情」的对象，不能走 deckJson（那边只收数组）
    if (!detailShards.all) {
      const el = document.getElementById('ky-deck-detail');
      try { detailShards.all = el ? JSON.parse(el.textContent) : {}; }
      catch { detailShards.all = {}; }
    }
    return Promise.resolve(detailShards.all);
  }
  const url = assets[key];
  if (!url) {
    detailShards[key] = {};
    return Promise.resolve(detailShards[key]);
  }
  detailPending[key] = fetch(url, { cache: 'force-cache' })
    .then(r => { if (!r.ok) throw new Error('detail ' + r.status); return r.json(); })
    .then(d => { detailShards[key] = d || {}; return detailShards[key]; })
    .catch(() => { delete detailShards[key]; throw new Error('detail load failed'); })
    .finally(() => { delete detailPending[key]; });
  return detailPending[key];
}

function escapeHtml(text) {
  return String(text == null ? '' : text).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function detailRow(key, value) {
  return value ? '<div class="detail-row"><span class="k">' + key + '</span><span class="v">' + value + '</span></div>' : '';
}
// 词形注释：纯码（p|d）是形态变化，其余是派生词自己的释义
const FORM_LABELS = {
  p: '过去式', d: '过去分词', i: '现在分词',
  s: '复数', 3: '第三人称单数', r: '比较级', t: '最高级',
};
function formNote(value) {
  if (!value) return '';
  const codes = value.split('|');
  if (codes.every(code => FORM_LABELS[code])) return codes.map(code => FORM_LABELS[code]).join('·');
  return value;   // 派生词，值本身就是中文释义
}
function renderDetail(word, info) {
  info = info || {};
  $('detailWord').textContent = word.word;
  $('detailWord').lang = 'en';
  $('detailPhonetic').textContent = info.p ? '/' + info.p + '/' : '';

  const chips = [];
  if (word.priority) chips.push('<span class="detail-chip">' + escapeHtml(word.priority) + '</span>');
  if ((info.g || []).indexOf('ky') >= 0) chips.push('<span class="detail-chip">考研大纲</span>');
  $('detailStatus').innerHTML = chips.length
    ? '<div class="detail-row"><span class="k">定位</span><span class="v">' + chips.join('') + '</span></div>'
    : '';

  const exam = [];
  // 词库字段是从 JSON 来的外部数据，拼进 innerHTML 前强制转成数字
  const freq = Number(word.freq) || 0;
  const en1Freq = Number(word.en1_freq) || 0;
  if (freq > 0) exam.push('英语二 ' + freq + ' 次');
  if (en1Freq > 0) exam.push('英语一 ' + en1Freq + ' 次');
  $('detailExam').innerHTML = detailRow('真题', exam.length ? exam.join(' · ') : '未在已收录真题中出现');

  const forms = (word.forms || []).filter(Boolean);
  // 词形后面带释义：形态变化标「过去式 / 现在分词」，真派生词给它自己的意思
  const formNotes = info.f || {};
  const formsHtml = forms.map(f => {
    const note = formNote(formNotes[f.toLowerCase()]);
    return note
      ? escapeHtml(f) + '<span class="form-note">（' + escapeHtml(note) + '）</span>'
      : escapeHtml(f);
  }).join(' / ');
  $('detailForms').innerHTML =
    detailRow('释义', escapeHtml(word.meaning)) +
    (word.family ? detailRow('词族', escapeHtml(word.family)) : '') +
    (forms.length ? detailRow('词形', formsHtml) : '');

  $('detailDict').textContent = info.t || '（这个词没有额外的词典义项）';
  $('detailDictBox').open = true;
  const mask = $('detailMask');
  // 打开时把焦点移进面板并记住来源：弹窗有 role=dialog 就必须真的管焦点，
  // 否则读屏和键盘用户还在背后的卡片上操作。
  if (mask.classList.contains('hidden')) {
    detailFocusBack = document.activeElement;
    mask.classList.remove('hidden');
    setPageInert(true, mask);
    const close = $('detailClose');
    if (close) { try { close.focus({ preventScroll: true }); } catch {} }
  }
}

async function openDetail(word) {
  if (!word) return;
  renderDetail(word, null);
  let shard;
  try { shard = await loadDetail(word.word); }
  catch {
    if (!$('detailMask').classList.contains('hidden')) $('detailDict').textContent = '详情加载失败，请检查网络后再试。';
    return;
  }
  if ($('detailMask').classList.contains('hidden')) return;
  if (queue[idx] && queue[idx].word === word.word) renderDetail(word, shard[word.word]);
}
let detailFocusBack = null;
function closeDetail() {
  const mask = $('detailMask');
  if (mask.classList.contains('hidden')) return;
  mask.classList.add('hidden');
  setPageInert(false);
  const back = detailFocusBack;
  detailFocusBack = null;
  if (back && typeof back.focus === 'function') { try { back.focus({ preventScroll: true }); } catch {} }
}
$('detailClose').onclick = closeDetail;
$('detailMask').onclick = event => { if (event.target === $('detailMask')) closeDetail(); };
$('detailAgain').onclick = () => { const w = queue[idx]; if (w) speak(w); };
// 焦点锁在面板内：Tab 到最后一个就回到第一个
$('detailSheet').addEventListener('keydown', event => {
  if (event.key !== 'Tab') return;
  const sheet = $('detailSheet');
  const items = [...sheet.querySelectorAll('button, summary, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter(el => !el.disabled);
  if (!items.length) return;
  const first = items[0], last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
window.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !$('detailMask').classList.contains('hidden')) closeDetail();
});

// 长按 0.5 秒打开；手指一动或提前抬起就取消，避免和滑动冲突
let pressTimer = null;
let pressFired = false;
const startPress = () => {
  clearTimeout(pressTimer);
  pressFired = false;
  const w = queue[idx];
  if (!w || studyLoading || !$('detailMask').classList.contains('hidden')) return;
  pressTimer = setTimeout(() => {
    pressFired = true;
    if (navigator.vibrate) navigator.vibrate(12);
    openDetail(w);
  }, 500);
};
const stopPress = () => { clearTimeout(pressTimer); pressTimer = null; };
card.addEventListener('touchstart', startPress, { passive: true });
card.addEventListener('touchmove', stopPress, { passive: true });
card.addEventListener('touchcancel', stopPress, { passive: true });
card.addEventListener('touchend', stopPress, { passive: true });
card.addEventListener('mousedown', event => {
  // 只有左键才算长按：右键同样会触发 mousedown，会莫名弹出详情
  if (event.button !== 0) return;
  startPress();
});
card.addEventListener('mouseup', stopPress);
card.addEventListener('mouseleave', stopPress);

// 鼠标滚轮翻词：挂到 document，卡片外的页眉缝隙和留白也能翻；
// 累加归一化后的 delta 再判定，普通鼠标一格≈100px 直接翻一个词，
// 高精度滚轮/触控板的小 delta 也能攒出来（旧的 "<3 直接丢弃" 会毫无反应）。
let wheelAcc = 0;
let wheelDir = 0;
let wheelLockedUntil = 0;
const WHEEL_STEP = 40;      // 翻一个词所需的滚动量
const WHEEL_COOLDOWN = 30;  // 只防同一帧里的连发，限速交给上面的累积阈值
document.addEventListener('wheel', event => {
  if (event.ctrlKey || event.metaKey) return;              // Ctrl/⌘ + 滚轮 = 缩放
  if ($('viewStudy').classList.contains('hidden')) return; // 词表/统计页有自己的滚动条
  if (!$('detailMask').classList.contains('hidden')) return;
  if (!$('authModal').classList.contains('hidden')) return;
  if (event.target.closest && event.target.closest('input, textarea, select')) return;
  if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
  const dy = event.deltaY * (event.deltaMode === 1 ? 40 : event.deltaMode === 2 ? 800 : 1);
  const dir = dy > 0 ? 1 : -1;
  if (dir !== wheelDir) { wheelAcc = 0; wheelDir = dir; }  // 反向立刻响应，不等冷却
  wheelAcc += dy;
  if (Math.abs(wheelAcc) < WHEEL_STEP) return;
  const now = Date.now();
  if (now < wheelLockedUntil) return;  // 冷却期内的滚动先攒着，到期后接着用，不丢
  event.preventDefault();
  wheelLockedUntil = now + WHEEL_COOLDOWN;
  wheelAcc = 0;
  navigate(dir);
}, { passive: false });
let dragWarmTimer = null;
$('progressBar').oninput = event => {
  if (!queue.length) return;
  const want = Math.max(Number(event.target.value), 0);
  // 分母是整章词数、队列却只有内嵌的几十个：拖到队列之外先记下目标，补全后再落位
  pendingSeek = want > queue.length - 1 && deckIncomplete()
    ? { deck: activeDeck, ch: curChapter, idx: want }
    : null;
  idx = Math.min(want, queue.length - 1);
  revealed = null;
  dragging = true;
  renderStudy();
  // 拖动停顿 120ms 就把目标词的音频准备好，松手那一刻直接出声
  clearTimeout(dragWarmTimer);
  dragWarmTimer = setTimeout(() => {
    const w = queue[idx];
    const key = w && audioKeyOf(w);
    if (key) preloadAudioWord(key, conf.speakLang === 'zh' ? 'zh' : 'en');
  }, 120);
};
$('progressBar').onchange = finishProgressDrag;
// 拖回原位置不会触发 change，必须另有出口，否则 dragging 永远为 true（进度条冻结、自动朗读失效）
// 松手必须补一次发音：拖动过程中 renderStudy() 会跳过朗读，不发就只剩手势没声音，
// 用户得自己再点喇叭。
function finishProgressDrag() {
  if (!dragging) return;
  dragging = false;
  clearTimeout(dragWarmTimer);
  savePos();
  prefetchAudioNearby();
  if (pendingSeek !== null) return;   // 目标位次还没到货，等补齐后落位时再朗读
  const w = queue[idx];
  if (w && conf.speak && speak(w)) lastSpoken = w.word;
}
$('progressBar').onpointerup = finishProgressDrag;
$('progressBar').ontouchend = finishProgressDrag;
$('progressBar').onblur = finishProgressDrag;
$('shuffleChapter').onclick = () => {
  const slice = chapterSlice(curChapter);
  if (slice.every(w => isMastered(w))) {
    if (!window.confirm('本章已全部掌握。打乱会清空掌握记录、重新背一遍，继续？')) return;
    for (const w of slice) if (state[w.word]) { const e = liveEntry(w.word); e.mastered = false; e.t = Date.now(); }
    save(LS_STATE, state);
  } else if (!window.confirm('打乱当前章节顺序？学习进度不会丢失。')) {
    return;
  }
  loadChapter(curChapter, 'shuffle');
  updateStats();
};
$('restoreOrder').onclick = () => {
  if (!window.confirm('恢复当前章节原序？打乱的顺序会被重置，学习进度不会丢失。')) return;
  loadChapter(curChapter, 'natural');
  updateStats();
};
$('prevWord').onclick = () => navigate(-1);
$('nextWord').onclick = () => navigate(1);
$('doneAction').onclick = () => {
  const mode = $('doneAction').dataset.mode;
  if (mode === 'list') { switchView('List'); return; }
  if (mode === 'reshuffle') {
    if (!window.confirm('打乱重背会清空本章掌握标记并重新开始，继续？')) return;
    // 整章已掌握：清掉掌握标记，按权重重新洗牌重背
    for (const w of chapterSlice(curChapter)) {
      if (state[w.word]) { const e = liveEntry(w.word); e.mastered = false; e.t = Date.now(); }
    }
    save(LS_STATE, state);
  }
  loadChapter(curChapter, mode === 'reshuffle' ? 'shuffle' : 'natural');
  updateStats();
};
$('tabStudy').onclick = () => switchView('Study');
$('tabList').onclick = () => switchView('List');
$('tabStat').onclick = () => switchView('Stat');
// ARIA tabs 的方向键导航：只移动焦点，不改变当前面板。
document.querySelector('.tabs').addEventListener('keydown', event => {
  const tabs = [...document.querySelectorAll('.tab')];
  const i = tabs.indexOf(document.activeElement);
  if (i < 0) return;
  let next = i;
  if (event.key === 'ArrowRight') next = (i + 1) % tabs.length;
  else if (event.key === 'ArrowLeft') next = (i - 1 + tabs.length) % tabs.length;
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = tabs.length - 1;
  else return;
  event.preventDefault();
  tabs[next].focus();
});
let searchTimer = null;
$('searchInput').oninput = event => {
  searchText = event.target.value;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => renderList(true), 120);
};
document.querySelectorAll('.filter').forEach(button => {
  button.onclick = () => {
    priorityFilter = button.dataset.priority;
    document.querySelectorAll('.filter').forEach(b => {
      b.classList.toggle('active', b === button);
      b.setAttribute('aria-pressed', String(b === button));
    });
    renderList(true);
  };
});
$('testSpeak').onclick = () => {
  const diag = $('speakDiag');
  diag.textContent = '正在播放 hello…';
  const ok = speak({ word: 'hello', meaning: '你好' }, { notify: true, onStatus: source => {
    if (source === 'online') diag.textContent = '真人发音已立即播放；这个词也会缓存，之后离线可重播。';
    else if (source === 'system') diag.textContent = '已立即用系统语音播放；真人发音会在后台缓存，之后秒播。';
    else diag.textContent = '在线发音和系统语音都不可用，请检查网络、媒体音量或换用系统浏览器。';
  }});
  if (!ok) diag.textContent = '请先点一下页面任意位置，再点测试发音。';
};
$('iconUpload').onclick = () => $('iconFile').click();
$('iconReset').onclick = () => {
  conf.icon = null;
  conf.iconAt = Date.now();
  save(LS_CONF, conf);
  renderAuth();
  renderIconSettings();
  syncFavicon(currentIcon());
  $('iconStatus').textContent = '已恢复默认图标。';
  $('iconFile').value = '';
};
$('iconFile').onchange = event => {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  if (!file.type.startsWith('image/')) {
    $('iconStatus').textContent = '请选择图片文件。';
    event.target.value = '';
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    $('iconStatus').textContent = '图片不能超过 10MB。';
    event.target.value = '';
    return;
  }
  $('iconStatus').textContent = '正在处理图片…';
  const url = URL.createObjectURL(file);
  const image = new Image();
  image.onload = () => {
    try {
      const size = 256;
      const side = Math.min(image.naturalWidth, image.naturalHeight);
      const sx = (image.naturalWidth - side) / 2;
      const sy = (image.naturalHeight - side) / 2;
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = size;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, size, size);
      ctx.drawImage(image, sx, sy, side, side, 0, 0, size, size);
      const data = canvas.toDataURL('image/jpeg', 0.86);
      conf.icon = { kind: 'image', data, name: file.name.slice(0, 60) };
      conf.iconAt = Date.now();
      save(LS_CONF, conf);
      renderAuth();
      renderIconSettings();
      syncFavicon(currentIcon());
      $('iconStatus').textContent = '已使用自定义图标：' + file.name;
    } catch (e) {
      $('iconStatus').textContent = '图片处理失败，请换一张试试。';
    } finally {
      URL.revokeObjectURL(url);
      event.target.value = '';
    }
  };
  image.onerror = () => {
    URL.revokeObjectURL(url);
    event.target.value = '';
    $('iconStatus').textContent = '无法读取这张图片，请换一张试试。';
  };
  image.src = url;
};
$('exportProgress').onclick = () => {
  const dump = {
    v: 1,
    exported: new Date().toISOString(),
    state,
    chapterData,
    daily,
    conf: { deck: conf.deck, chapter: conf.chapter || 0, deckChapter: conf.deckChapter || {}, progressAt: Number(conf.progressAt) || 0, showByDefault: !!conf.showByDefault, speak: conf.speak !== false, speakLang: conf.speakLang === 'zh' ? 'zh' : 'en', icon: conf.icon || null, iconAt: Number(conf.iconAt) || 0, resetAt: Number(conf.resetAt) || 0 }
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
