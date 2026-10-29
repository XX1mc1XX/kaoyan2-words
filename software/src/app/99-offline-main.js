// ---- PWA / 离线可用 ----
let offlinePrefetchState = 'unknown';
let offlinePrefetchFailed = 0;
function updateOfflineStatus() {
  const el = $('offlineDiag');
  if (!el) return;
  if (location.protocol === 'file:') {
    el.textContent = '当前是本地单文件模式，词库和学习记录本来就能离线使用；真人发音预加载后秒播，未就绪时立即用系统语音。';
    el.className = 'offline-note ok';
    return;
  }
  if (!window.isSecureContext) {
    el.textContent = '当前是局域网 HTTP 模式，浏览器不会启用离线缓存；部署到 HTTPS 后即可离线使用。';
    el.className = 'offline-note';
    return;
  }
  const swReady = 'serviceWorker' in navigator && !!navigator.serviceWorker.controller;
  const cachedCount = audioCachedWords.size;
  const assetsIncomplete = offlinePrefetchState === 'partial' || offlinePrefetchFailed > 0;
  if (assetsIncomplete && navigator.onLine !== false) {
    el.textContent = '离线词库缓存不完整（失败 ' + offlinePrefetchFailed + ' 项），正在等待联网补缓存。';
    el.className = 'offline-note warn';
    return;
  }
  if (navigator.onLine === false) {
    el.textContent = swReady
      ? '离线模式：词库和学习功能可用；已缓存 ' + cachedCount + ' 个发音。'
      : '当前离线，且页面尚未完成离线缓存。联网打开一次后即可离线使用。';
  } else {
    el.textContent = swReady
      ? '离线缓存已就绪，已缓存 ' + cachedCount + ' 个发音。'
      : '正在准备离线缓存；联网打开一次后即可离线使用。';
  }
  el.className = 'offline-note' + (swReady && !assetsIncomplete ? ' ok' : '');
}

// ---------- 全量离线缓存 ----------
// 缓存写入交给 Service Worker：页面只发请求，持久化和淘汰策略都在 sw.js 里。
// 页面壳和四本词库在 SW 安装时就已存好，这里补的是全部真人发音 + 词典详情分片。
// 音频都很小（10KB 上下），并发开满，只在单条卡住时超时跳过，不做任何限速。
const OFFLINE_CONCURRENCY = 16;
const OFFLINE_FETCH_TIMEOUT = 20000;
const OFFLINE_PERMANENT_KEY = 'ky_audio_permanent_fail_' + AUDIO_CACHE_VERSION;
let offlinePermanent = (() => { try { return new Set(JSON.parse(localStorage.getItem(OFFLINE_PERMANENT_KEY)) || []); } catch { return new Set(); } })();
let offlineJob = null;

async function offlineWordList() {
  await Promise.all(DECK_KEYS.map(loadWebDeck));
  const seen = new Set();
  const out = [];
  for (const key of DECK_KEYS) {
    for (const item of DECKS[key].words || []) {
      const name = item && item.word;
      if (!name || seen.has(name)) continue;
      seen.add(name);
      out.push(name);
    }
  }
  return out;
}

// 中文释义也要能离线：百度 TTS 每个文本一个音频，按文本去重后数量比词数少
async function offlineZhTexts() {
  await Promise.all(DECK_KEYS.map(loadWebDeck));
  const seen = new Set();
  const out = [];
  for (const key of DECK_KEYS) {
    for (const item of DECKS[key].words || []) {
      const text = meaningForSpeech(item);
      if (!text || seen.has(text)) continue;
      seen.add(text);
      out.push(text);
    }
  }
  return out;
}

function renderOfflineJob() {
  const job = offlineJob;
  if (!job) return;
  const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
  $('offlineFill').style.width = pct + '%';
  const problems = [];
  if (job.failed) problems.push('失败 ' + job.failed);
  if (job.skipped) problems.push('跳过 ' + job.skipped);
  if (job.detailsFailed) problems.push('详情失败 ' + job.detailsFailed);
  const tail = problems.length ? '，' + problems.join('，') : '';
  // 用最近几秒的滑动速度；跳过已缓存那段不会把全程平均速度算得虚高。
  const now = Date.now();
  if (job.sampleT && now - job.sampleT >= 3000) {
    job.rate = (job.done - job.sampleDone) / ((now - job.sampleT) / 1000);
    job.sampleT = now;
    job.sampleDone = job.done;
  } else if (!job.sampleT) {
    job.sampleT = now;
    job.sampleDone = job.done;
  }
  const rate = job.rate > 0 ? ' · ' + job.rate.toFixed(0) + '/秒' : '';
  if (job.cancelled) $('offlineStat').textContent = '已停止：缓存了 ' + job.done + ' / ' + job.total + ' 个' + tail;
  else if (job.done >= job.total) {
    $('offlineStat').textContent = (problems.length ? '完成但有缺失：' : '完成：')
      + job.total + ' 条发音和词典已处理' + tail;
  } else $('offlineStat').textContent = job.phase + ' ' + job.done + ' / ' + job.total + '（' + pct + '%）' + rate + tail;
}

// 中文现在走百度 TTS，是可缓存的音频；单文件版没有 worker，才退回系统语音
function zhVoiceStatus() {
  refreshVoice();
  if (AUDIO_PROXY_READY) return '中文朗读：百度语音，点「下载全部」可一并离线';
  if (!zhVoice) return '中文朗读：单文件版没有联网代理，系统也没装中文语音';
  return '中文朗读：系统语音（' + zhVoice.name + '）';
}
function warmChineseVoice() {
  const synth = window.speechSynthesis;
  if (!synth || !zhVoice) return false;
  try {
    const u = new SpeechSynthesisUtterance('一');
    u.voice = zhVoice;
    u.lang = zhVoice.lang || 'zh-CN';
    u.rate = 1.2;
    u.volume = 0;
    synth.speak(u);
    return true;
  } catch { return false; }
}
async function refreshOfflineStat() {
  const box = $('offlineBox');
  if (!box) return;
  const supported = 'serviceWorker' in navigator && window.isSecureContext && location.protocol !== 'file:';
  box.classList.toggle('hidden', !supported);
  const zhEl = $('zhVoiceStat');
  if (zhEl) zhEl.textContent = zhVoiceStatus();
  if (!supported || offlineJob) return;
  $('offlineStat').textContent = '正在统计…';
  const words = await offlineWordList();
  if (offlineJob) return;
  $('offlineStat').textContent = '共 ' + words.length + ' 个词，已缓存发音 ' + audioCachedWords.size + ' 个。';
}

// 一次全量下载等于几千个音频请求，撞到限流就退避重试，别让整批失败
function responseIsPermanentAudioFailure(err) {
  const m = String((err && err.message) || '');
  const status = Number((m.match(/audio (\d{3})/) || [])[1]);
  return status >= 400 && status < 500 && status !== 408 && status !== 425 && status !== 429;
}
function cancelledError() {
  return Object.assign(new Error('cancelled'), { name: 'AbortError' });
}
async function waitWithAbort(ms, signal) {
  if (signal && signal.aborted) throw cancelledError();
  await new Promise((resolve, reject) => {
    const timer = setTimeout(done, ms);
    function done() {
      if (signal) signal.removeEventListener('abort', onAbort);
      resolve();
    }
    function onAbort() {
      clearTimeout(timer);
      if (signal) signal.removeEventListener('abort', onAbort);
      reject(cancelledError());
    }
    if (signal) signal.addEventListener('abort', onAbort, { once: true });
  });
}
async function fetchOfflineAudio(text, lang, externalSignal) {
  const waits = [2000, 6000, 15000];
  for (let attempt = 0; attempt <= waits.length; attempt += 1) {
    if (externalSignal && externalSignal.aborted) throw cancelledError();
    const timeoutController = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const abort = () => { try { timeoutController.abort(); } catch {} };
    if (externalSignal) externalSignal.addEventListener('abort', abort, { once: true });
    const timer = timeoutController ? setTimeout(abort, OFFLINE_FETCH_TIMEOUT) : null;
    let response;
    try {
      response = await fetch(offlineAudioUrl(text, lang) + '&offline=1', timeoutController ? { signal: timeoutController.signal } : {});
    } catch (err) {
      if (externalSignal && externalSignal.aborted) throw cancelledError();
      if (attempt === waits.length) throw err;
      await waitWithAbort(waits[attempt], externalSignal);
      continue;
    } finally {
      if (timer) clearTimeout(timer);
      if (externalSignal) externalSignal.removeEventListener('abort', abort);
    }
    // 408/425/429/5xx 都可重试；其余 4xx 是确定性失败。
    const retryable = response.status === 408 || response.status === 425 || response.status === 429 || response.status >= 500;
    if (retryable && attempt < waits.length) {
      try { await response.body?.cancel(); } catch {}
      const retryAfter = Number(response.headers.get('retry-after') || 0) * 1000;
      const fallbackWait = response.status === 429 ? waits[attempt] : [500, 2000, 6000][attempt];
      const wait = Math.min(30000, Math.max(retryAfter || 0, fallbackWait));
      await waitWithAbort(wait, externalSignal);
      continue;
    }
    if (!response.ok) throw new Error('audio ' + response.status);
    return response;
  }
}
async function waitForServiceWorkerReady(signal, timeoutMs) {
  if (!('serviceWorker' in navigator)) throw new Error('浏览器不支持离线缓存');
  if (navigator.serviceWorker.controller) return navigator.serviceWorker.ready;
  if (signal && signal.aborted) throw cancelledError();
  const registration = await navigator.serviceWorker.ready;
  if (signal && signal.aborted) throw cancelledError();
  if (navigator.serviceWorker.controller) return registration;
  // ready 只说明有活动 worker，不保证当前页面已经被它接管；离线写入必须在 controller 下进行。
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      navigator.serviceWorker.removeEventListener('controllerchange', onChange);
      if (signal) signal.removeEventListener('abort', onAbort);
      fn(value);
    };
    const onChange = () => {
      if (navigator.serviceWorker.controller) finish(resolve, registration);
    };
    const onAbort = () => finish(reject, cancelledError());
    const timer = setTimeout(() => finish(reject, new Error('Service Worker 接管超时')), timeoutMs || 15000);
    navigator.serviceWorker.addEventListener('controllerchange', onChange);
    if (signal) signal.addEventListener('abort', onAbort, { once: true });
    onChange();
  });
}

async function runOfflineDownload(opts) {
  const auto = !!(opts && opts.auto);
  if (offlineJob) return;
  const startBtn = $('offlineStart');
  const stopBtn = $('offlineStop');
  // 准备阶段也占住任务槽，避免双击或自动/手动任务同时进入。
  offlineJob = { total: 0, done: 0, failed: 0, cancelled: false, phase: '正在准备词库…', preparing: true };
  startBtn.disabled = true;
  // file:// 单文件版没有 worker，中文只能靠系统语音，借这次点击把引擎唤醒
  warmChineseVoice();
  const zhEl = $('zhVoiceStat');
  if (zhEl) zhEl.textContent = zhVoiceStatus();
  $('offlineStat').textContent = '正在准备词库…';
  let words = [];
  try {
    words = await offlineWordList();
  } catch {
    offlineJob = null;
    startBtn.disabled = false;
    $('offlineStat').textContent = '词库加载失败，请检查网络后重试。';
    return;
  }
  // 准备阶段不持有 controller；用户若已点停止，或词库为空，必须清掉占位任务，
  // 否则 offlineJob 永远非空，之后手动下载和自动下载都进不来。
  if (!offlineJob || offlineJob.cancelled) {
    offlineJob = null;
    startBtn.disabled = false;
    return;
  }
  if (!words.length) {
    offlineJob = null;
    $('offlineStat').textContent = '词库还没加载完，稍后再试。';
    startBtn.disabled = false;
    return;
  }
  // 英文单词音 + 中文释义音一起下，中文按文本去重
  let targets = words.map(word => ({ key: word, lang: 'en' }));
  if (AUDIO_PROXY_READY) {
    for (const text of await offlineZhTexts()) targets.push({ key: text, lang: 'zh' });
  }
  // 当前章节先下：用户正在背的这几百个（英文+中文）马上可用，其余的慢慢补
  const urgent = new Set();
  for (const item of queue) {
    urgent.add(item.word);
    const zh = meaningForSpeech(item);
    if (zh) urgent.add(zh);
  }
  if (urgent.size) {
    targets = targets.filter(t => urgent.has(t.key)).concat(targets.filter(t => !urgent.has(t.key)));
  }
  // 已经在本机的不用再下一遍
  const pending = targets.filter(t => !audioCachedWords.has(audioMarkerKey(t.key, t.lang)) && !offlinePermanent.has(audioMarkerKey(t.key, t.lang)));
  // 自动模式分批：一次最多 800 条，跑完就收工，下次打开接着来。
  // 否则每次打开都在后台拖几分钟，页面和朗读都被它拖慢。
  const allTargets = targets;
  targets = auto ? pending.slice(0, 800) : pending;
  if (!targets.length) {
    offlineJob = null;
    if (auto) markAutoOfflineDone(targets.length - offlinePermanent.size);
    $('offlineStat').textContent = '全部发音都已经存在本机了。';
    startBtn.disabled = false;
    return;
  }
  offlineJob = {
    total: targets.length, done: 0, failed: 0, skipped: 0, detailsFailed: 0, cancelled: false,
    startedAt: Date.now(),
    phase: auto ? '后台自动缓存（每次最多 800 条）' : '正在下载发音',
    stopReason: '',
    controller: typeof AbortController !== 'undefined' ? new AbortController() : null,
  };
  stopBtn.classList.remove('hidden');
  renderOfflineJob();
  try {
    await waitForServiceWorkerReady(offlineJob.controller && offlineJob.controller.signal);
    // 词典详情的分片按首字母拆过，26 个小文件，先拿完离线也能长按看详情
    const details = (DATA_META && DATA_META.assets && DATA_META.assets.details) || {};
    // 词典详情分片是附加内容，拉不到不该算进发音失败：它会让 finished.failed 永远
    // 为真，后台自动缓存就再也标不成「已完成」，每次打开都要重来一遍。
    for (const url of Object.values(details)) {
      try {
        const response = await fetch(url, { cache: 'force-cache' });
        if (!response.ok) throw new Error('detail ' + response.status);
        if (!audioCacheConfirmed(response)) throw new Error('detail cache not confirmed');
        await response.text();
      } catch {
        const job = offlineJob;
        if (job && !job.cancelled) job.detailsFailed += 1;
      }
    }
    let cursor = 0;
    let consecutiveFailures = 0;
    const worker = async () => {
      for (;;) {
        const job = offlineJob;
        if (!job || job.cancelled) return;
        const index = cursor;
        cursor += 1;
        if (index >= targets.length) return;
        const target = targets[index];
        const marker = audioMarkerKey(target.key, target.lang);
        try {
          const response = await fetchOfflineAudio(target.key, target.lang, job.controller && job.controller.signal);
          if (!audioCacheConfirmed(response)) throw new Error('audio cache store failed');
          await response.arrayBuffer();
          rememberAudio(marker);
          consecutiveFailures = 0;
        } catch (err) {
          if (err && err.name === 'AbortError') return;
          if (responseIsPermanentAudioFailure(err)) {
            offlinePermanent.add(marker);
            job.skipped += 1;
          } else {
            job.failed += 1;
            consecutiveFailures += 1;
            if (consecutiveFailures >= 40) {
              job.cancelled = true;
              job.stopReason = 'threshold';
              if (job.controller) job.controller.abort();
              $('offlineStat').textContent = '网络不稳定，已暂停；下次打开会接着补。';
            }
          }
        }
        job.done += 1;
        if (job.done % 5 === 0 || job.done === job.total) renderOfflineJob();
      }
    };
    await Promise.all(Array.from({ length: OFFLINE_CONCURRENCY }, worker));
  } catch (err) {
    if (err && err.name !== 'AbortError') $('offlineStat').textContent = '离线缓存失败：' + (err.message || '请稍后重试');
  } finally {
    const finished = offlineJob;
    renderOfflineJob();
    offlineJob = null;
    flushAudioMarkers();
    try { localStorage.setItem(OFFLINE_PERMANENT_KEY, JSON.stringify([...offlinePermanent])); } catch {}
    startBtn.disabled = false;
    stopBtn.classList.add('hidden');
    updateOfflineStatus();
    // 只有这一批就把剩下的全下完了，才算彻底完成；分批模式下留着下次继续
    if (auto && finished && !finished.cancelled && !finished.failed && !finished.skipped && !finished.detailsFailed) {
      // 必须检查全量目标而不是当前这 800 条；否则首批完成就会把 done 写死。
      const stillPending = allTargets.some(t => !audioCachedWords.has(audioMarkerKey(t.key, t.lang)) && !offlinePermanent.has(audioMarkerKey(t.key, t.lang)));
      if (!stillPending) markAutoOfflineDone(allTargets.length - offlinePermanent.size);
    }
  }
}

// 后台自动缓存：首屏稳定后自己跑全量，用户不用点任何按钮
const AUTO_OFFLINE_KEY = 'ky_auto_offline_' + AUDIO_CACHE_VERSION;
const AUTO_OFFLINE_DONE_PREFIX = 'done:';
let autoOfflineStarted = false;
function readAutoOfflineDone() {
  try {
    const raw = String(localStorage.getItem(AUTO_OFFLINE_KEY) || '');
    const match = raw.match(/^done:(\d+)$/);
    if (!match) return null;
    return { expected: Math.max(0, Number(match[1]) || 0) };
  } catch { return null; }
}
function markAutoOfflineDone(expected) {
  try { localStorage.setItem(AUTO_OFFLINE_KEY, AUTO_OFFLINE_DONE_PREFIX + Math.max(0, Number(expected) || 0)); } catch {}
}
function clearAutoOfflineDone() {
  try {
    const raw = String(localStorage.getItem(AUTO_OFFLINE_KEY) || '');
    if (raw.startsWith(AUTO_OFFLINE_DONE_PREFIX) || raw === 'done') localStorage.removeItem(AUTO_OFFLINE_KEY);
  } catch {}
}
function autoOfflineAllowed() {
  const done = readAutoOfflineDone();
  if (done && audioCachedWords.size >= done.expected) return false;
  if (done) clearAutoOfflineDone();
  const conn = navigator.connection;
  if (conn && (conn.saveData || /(^|-)2g$/.test(conn.effectiveType || ''))) return false;
  return true;
}
function scheduleAutoOffline() {
  if (autoOfflineStarted || !autoOfflineAllowed()) return;
  if (!('serviceWorker' in navigator) || !window.isSecureContext || location.protocol === 'file:') return;
  autoOfflineStarted = true;
  // 等首屏、缓存对账和首词朗读都稳定之后，再占用后台带宽。
  const start = () => runOfflineDownload({ auto: true });
  const idle = () => {
    if ('requestIdleCallback' in window) requestIdleCallback(start, { timeout: 20000 });
    else setTimeout(start, 20000);
  };
  if (document.readyState === 'complete') idle();
  else window.addEventListener('load', idle, { once: true });
}
$('offlineStart').onclick = () => {
  if (offlineJob) { $('offlineStat').textContent = '正在后台缓存中，进度见上方。'; return; }
  runOfflineDownload();
};
$('offlineStop').onclick = () => { if (offlineJob) { offlineJob.cancelled = true; offlineJob.stopReason = 'user'; if (offlineJob.controller) offlineJob.controller.abort(); } };

// ---- 安装到桌面 + 手动检查更新 ----
let installPrompt = null;
const isStandalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault();
  installPrompt = event;
  const stat = $('appStat');
  if (stat && !isStandalone()) stat.textContent = '可以安装到桌面了，点左边按钮。';
});
const installHint = () => {
  const ua = navigator.userAgent;
  if (/MicroMessenger/i.test(ua)) return '微信里没有安装入口：点右上角「…」→「在浏览器打开」，再照下面的步骤装。';
  if (/iPhone|iPad|iPod/i.test(ua)) return 'iPhone/iPad：点 Safari 底部「分享」→「添加到主屏幕」。';
  return '安卓：点浏览器右上角「⋮」菜单 →「添加到主屏幕」或「安装应用」。';
};
$('installApp').onclick = async () => {
  const stat = $('appStat');
  if (isStandalone()) { stat.textContent = '已经在桌面图标里运行了。'; return; }
  if (!installPrompt) {
    stat.textContent = installHint();
    return;
  }
  installPrompt.prompt();
  const choice = await installPrompt.userChoice;
  stat.textContent = choice && choice.outcome === 'accepted' ? '已安装，去桌面找图标。' : '已取消。' + installHint();
  installPrompt = null;
};
let updateCheckBusy = false;
$('checkUpdate').onclick = async () => {
  const stat = $('appStat');
  if (updateCheckBusy) return;
  updateCheckBusy = true;
  stat.textContent = '正在检查…';
  try {
    const reg = await navigator.serviceWorker.getRegistration();
    if (!reg) { stat.textContent = '当前不是离线版本，直接刷新页面即可。'; return; }
    const before = navigator.serviceWorker.controller;
    await reg.update();
    await new Promise(resolve => setTimeout(resolve, 300));
    const installing = reg.installing;
    const changed = navigator.serviceWorker.controller !== before || !!installing || !!reg.waiting;
    if (!changed) {
      stat.textContent = '已是最新版本。';
      return;
    }
    stat.textContent = '发现新版本，正在应用…';
    if (reg.waiting) reg.waiting.postMessage({ type: 'ky:skip-waiting' });
    if (navigator.serviceWorker.controller === before && installing) {
      await new Promise(resolve => {
        const timer = setTimeout(resolve, 10000);
        const done = () => {
          if (installing.state === 'installed' || installing.state === 'activated' || installing.state === 'redundant') {
            clearTimeout(timer);
            installing.removeEventListener('statechange', done);
            resolve();
          }
        };
        installing.addEventListener('statechange', done);
        done();
      });
      if (reg.waiting) reg.waiting.postMessage({ type: 'ky:skip-waiting' });
    }
    if (navigator.serviceWorker.controller !== before) {
      stat.textContent = '新版本已就绪，正在刷新…';
      setTimeout(() => location.reload(), 700);
    } else {
      stat.textContent = '新版本已下载，关闭并重新打开应用后生效。';
    }
  } catch {
    stat.textContent = '检查失败，请确认网络后重试。';
  } finally {
    updateCheckBusy = false;
  }
};

window.addEventListener('online', updateOfflineStatus);
window.addEventListener('offline', updateOfflineStatus);
updateOfflineStatus();
if ('serviceWorker' in navigator && window.isSecureContext && location.protocol !== 'file:') {
  window.addEventListener('load', () => {
    const hadControllerAtLoad = !!navigator.serviceWorker.controller;
    let reloadScheduled = false;
    const scheduleUpdateReload = () => {
      if (reloadScheduled) return;
      reloadScheduled = true;
      showSessionNotice('离线内容已更新，正在刷新页面…', 3000);
      setTimeout(() => location.reload(), 1200);
    };
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      updateOfflineStatus();
      // 首次安装的 clients.claim 不应导致一次无意义刷新；已有控制器后的更换才刷新。
      if (hadControllerAtLoad || reloadScheduled) scheduleUpdateReload();
    });
    navigator.serviceWorker.register('./sw.js', { updateViaCache: 'none' }).then(async registration => {
      // 每次打开都查更新要拉一次 sw.js，还可能触发整壳重装；一天查一次足够。
      const KEY = 'ky_update_check_v1';
      let last = 0;
      try { last = Number(localStorage.getItem(KEY)) || 0; } catch {}
      if (Date.now() - last > 86400000) {
        registration.update().then(() => {
          try { localStorage.setItem(KEY, String(Date.now())); } catch {}
        }).catch(() => {});
      }
      await navigator.serviceWorker.ready;
      const idle = window.requestIdleCallback || (fn => setTimeout(fn, 1200));
      idle(async () => {
        await reconcileAudioCache();
        if (navigator.serviceWorker.controller) {
          navigator.serviceWorker.controller.postMessage({
            type: 'ky:prefetch-diagnostics-query', protocol: 1, requestId: 'startup',
          });
        }
        updateOfflineStatus();
        scheduleAutoOffline();
      }, { timeout: 5000 });
      updateOfflineStatus();
    }).catch(() => updateOfflineStatus());
    navigator.serviceWorker.addEventListener('message', event => {
      const msg = event.data || {};
      if (msg.type === 'ky:audio-cache-snapshot') {
        const pending = pendingAudioCacheQueries.get(msg.requestId);
        if (pending) {
          clearTimeout(pending.timer);
          pendingAudioCacheQueries.delete(msg.requestId);
          pending.resolve(msg);
        }
        applyAudioCacheSnapshot(msg);
        return;
      }
      if (msg.type === 'ky:audio-evicted' && Array.isArray(msg.urls)) {
        if (!acceptAudioCacheRevision(msg.epoch, msg.revision)) return;
        let changed = false;
        for (const raw of msg.urls) {
          try {
            const u = new URL(raw, location.href);
            const word = u.searchParams.get('word') || '';
            const lang = u.searchParams.get('lang') === 'zh' ? 'zh' : 'en';
            if (forgetAudio(audioMarkerKey(word, lang))) changed = true;
          } catch {}
        }
        if (changed) flushAudioMarkers();
      } else if (msg.type === 'ky:prefetch-priority-request') {
        const id = DECK_IDS[activeDeck];
        const asset = id && DATA_META.assets && DATA_META.assets[id];
        if (asset && navigator.serviceWorker.controller) {
          navigator.serviceWorker.controller.postMessage({
            type: 'ky:prefetch-priority',
            protocol: 1,
            assets: [asset],
            deck: activeDeck,
          });
        }
      } else if (msg.type === 'ky:prefetch-diagnostics') {
        const latest = Array.isArray(msg.runs) ? msg.runs[0] : null;
        if (latest && latest.state) {
          offlinePrefetchState = latest.state === 'complete' ? 'complete' : 'partial';
          offlinePrefetchFailed = Math.max(0, Number(latest.failed) || 0);
          updateOfflineStatus();
        }
      } else if (msg.type === 'ky:prefetch-status') {
        offlinePrefetchState = msg.state === 'complete' ? 'complete' : 'partial';
        offlinePrefetchFailed = Math.max(0, Number(msg.failed) || 0);
        if (offlinePrefetchState === 'complete') {
          try { localStorage.removeItem('ky_prefetch_diag_v1'); } catch {}
        }
        updateOfflineStatus();
      } else if (msg.type === 'ky:prefetch-failed') {
        offlinePrefetchState = 'partial';
        offlinePrefetchFailed = Math.max(0, Number(msg.count) || 0);
        try { localStorage.setItem('ky_prefetch_diag_v1', JSON.stringify(msg.diagnostic || msg)); } catch {}
        showSessionNotice('离线缓存未完整下载，联网后会自动重试。', 8000);
        updateOfflineStatus();
      } else if (msg.type === 'ky:sw-updated') {
        updateOfflineStatus();
      }
    });
  });
}
