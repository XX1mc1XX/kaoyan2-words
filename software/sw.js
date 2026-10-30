const BUILD_VERSION = 'edbd90984455';
const SHELL_CACHE = 'ky-shell-' + BUILD_VERSION;
const AUDIO_CACHE = 'ky-audio-v2';
const AUDIO_PROTOCOL_VERSION = 1;
// 页面只有在收到这个响应头后才允许写本地「已缓存」标记。
const CACHE_STATUS_HEADER = 'x-ky-cache';
// 修订号 + SW 实例 epoch 用来丢弃跨标签页乱序到达的旧消息。
const CACHE_REVISION_HEADER = 'x-ky-cache-revision';
const CACHE_EPOCH_HEADER = 'x-ky-cache-epoch';
// 四本词库合计三千多词，中英文各一条音频，「下载全部」要能一次装下。
// 真正卡体积的是下面的配额检查。
const AUDIO_CACHE_MAX = 8000;
let audioWriteCount = 0;
let audioCacheRevision = 0;
const audioCacheEpoch = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
let audioMutationQueue = Promise.resolve();
const pendingAudioFetches = new Map();
// 导航请求的 network-first 超时：超过就先用缓存顶，避免弱网白屏
const NAV_TIMEOUT_MS = 3000;
// 配额吃到 80% 或剩余不到 8MB 就不再缓存新音频
const AUDIO_BUDGET_RATIO = 0.8;
const AUDIO_BUDGET_MIN_FREE = 8 * 1024 * 1024;
// 只缓存根路径一份页面：'./' 在部署环境里就是 index.html，重复缓存会白占一倍空间
const APP_ASSET = './app.4defd52cb022.js';
const DATA_ASSETS = ["./data/words.b5ef547ac5fc.json", "./data/derivatives.47bc601b592b.json", "./data/basic.c44eb02808ef.json", "./data/insurance.ed6ab2b6e23c.json"];
const PREFETCH_DIAGNOSTIC_CACHE = 'ky-prefetch-diagnostics-v1';
const PREFETCH_DIAGNOSTIC_URL = self.location.origin + '/__ky-internal/prefetch-diagnostics';
let prefetchRunSequence = 0;
const prefetchInFlight = new Map();
let prefetchDiagnosticQueue = Promise.resolve();
// 首装只等页面壳这几个小文件。四本词库和主程序五百多 KB 放到激活后再补，
// 否则第一次打开会一直卡在 SW 安装，浏览器标签上的进度条也停不下来。
const SHELL_CORE = ['./', APP_ASSET, './manifest.webmanifest', './icon-192.png', './icon-512.png'];

// 写缓存一律允许失败：配额满时 cache.put 会 reject，
// 让它冒泡会把一个明明已经拿到的响应变成 503。
async function safePut(cache, request, response) {
  try {
    await cache.put(request, response);
    return true;
  } catch (err) {
    console.warn('[SW] cache put failed', request.url, err);
    return false;
  }
}

function normalizeAudioVersion(value) {
  if (value == null) return '';
  const version = String(value).trim();
  if (!/^\d+$/.test(version)) return version;
  return version.replace(/^0+(?=\d)/, '');
}

function audioCacheKey(request) {
  const url = new URL(request.url);
  const word = url.searchParams.get('word') || '';
  const lang = String(url.searchParams.get('lang') || '').trim().toLowerCase() === 'zh' ? 'zh' : 'en';
  const version = normalizeAudioVersion(url.searchParams.get('v'));
  const canonical = new URL(url.origin + url.pathname);
  // 固定参数顺序，并只保留会影响音频内容的参数。offline 只是本次请求的控制位，
  // 不能进入缓存身份；lang 的默认值 en 和空 v 也不单独制造一份缓存。
  if (lang === 'zh') canonical.searchParams.set('lang', 'zh');
  if (version) canonical.searchParams.set('v', version);
  canonical.searchParams.set('word', word);
  canonical.hash = '';
  return new Request(canonical.toString(), { method: 'GET' });
}

function audioEntryFromKey(key) {
  const url = new URL(key.url);
  const word = url.searchParams.get('word') || '';
  const lang = url.searchParams.get('lang') === 'zh' ? 'zh' : 'en';
  const version = url.searchParams.get('v') || '';
  return {
    cacheKey: key.url,
    url: key.url,
    word,
    lang,
    v: version || null,
    marker: lang + ':' + word,
  };
}

function isAudioCacheKey(key) {
  try {
    const url = new URL(key.url);
    return url.pathname.includes('/api/audio') && !!url.searchParams.get('word');
  } catch {
    return false;
  }
}

function withCacheStatus(response, status, revision) {
  const headers = new Headers(response.headers);
  headers.set(CACHE_STATUS_HEADER, status);
  headers.set(CACHE_REVISION_HEADER, String(Number.isFinite(revision) ? revision : audioCacheRevision));
  headers.set(CACHE_EPOCH_HEADER, audioCacheEpoch);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function audioFailureResponse() {
  return withCacheStatus(new Response('', {
    status: 503,
    headers: { 'content-type': 'text/plain; charset=utf-8' },
  }), 'store-failed', audioCacheRevision);
}

function bumpAudioRevision() {
  audioCacheRevision += 1;
  return audioCacheRevision;
}

function runAudioMutation(task) {
  const run = audioMutationQueue.then(task, task);
  audioMutationQueue = run.then(() => undefined, () => undefined);
  return run;
}

async function sameOriginWindowClients() {
  if (!self.clients || !self.clients.matchAll) return [];
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  return windows.filter(client => {
    try { return new URL(client.url).origin === self.location.origin; } catch { return false; }
  });
}

async function broadcastToWindows(message) {
  const windows = await sameOriginWindowClients();
  for (const client of windows) {
    try { client.postMessage(message); } catch {}
  }
}

function postToMessageSource(source, message) {
  if (source && typeof source.postMessage === 'function') {
    try {
      source.postMessage(message);
      return true;
    } catch {}
  }
  return false;
}

function normalizeDataAssetUrl(raw) {
  try {
    const url = new URL(String(raw), self.registration.scope);
    const dataRoot = new URL('./data/', self.registration.scope).pathname;
    if (url.origin !== self.location.origin || !url.pathname.startsWith(dataRoot)) return '';
    url.hash = '';
    return url.toString();
  } catch {
    return '';
  }
}

function normalizeDataAssetUrls(values) {
  const input = Array.isArray(values) ? values : [];
  return [...new Set(input.map(normalizeDataAssetUrl).filter(Boolean))];
}

function prefetchFailure(url, err, priority) {
  return {
    url,
    priority: !!priority,
    name: String((err && err.name) || 'Error'),
    status: Number(err && err.status) || 0,
    message: String((err && err.message) || err || 'prefetch failed'),
    at: Date.now(),
  };
}

async function prefetchOne(cache, url, priority) {
  if (prefetchInFlight.has(url)) return prefetchInFlight.get(url);
  const task = (async () => {
    const request = new Request(url, { cache: 'reload' });
    const existing = await cache.match(request);
    if (existing) return { url, priority: !!priority, result: 'hit' };
    const response = await fetch(request);
    if (!response.ok) {
      const err = new Error('prefetch HTTP ' + response.status);
      err.status = response.status;
      throw err;
    }
    if (!await safePut(cache, request, response.clone())) {
      throw new Error('prefetch cache put failed');
    }
    return { url, priority: !!priority, result: 'stored' };
  })();
  prefetchInFlight.set(url, task);
  try {
    return await task;
  } finally {
    if (prefetchInFlight.get(url) === task) prefetchInFlight.delete(url);
  }
}

async function persistPrefetchRun(run) {
  const write = async () => {
    try {
      const cache = await caches.open(PREFETCH_DIAGNOSTIC_CACHE);
      const key = new Request(PREFETCH_DIAGNOSTIC_URL);
      const oldResponse = await cache.match(key);
      const old = oldResponse ? await oldResponse.json().catch(() => ({})) : {};
      const runs = [run, ...(Array.isArray(old.runs) ? old.runs : [])]
        .filter((item, index, list) => item && list.findIndex(x => x && x.id === item.id) === index)
        .slice(0, 8);
      const payload = {
        protocol: AUDIO_PROTOCOL_VERSION,
        build: BUILD_VERSION,
        epoch: audioCacheEpoch,
        updatedAt: Date.now(),
        runs,
      };
      await safePut(cache, key, new Response(JSON.stringify(payload), {
        headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
      }));
    } catch (err) {
      console.warn('[SW] prefetch diagnostics persist failed', err);
    }
  };
  const current = prefetchDiagnosticQueue.then(write, write);
  prefetchDiagnosticQueue = current.then(() => undefined, () => undefined);
  return current;
}

async function readPrefetchDiagnostics() {
  try {
    const cache = await caches.open(PREFETCH_DIAGNOSTIC_CACHE);
    const response = await cache.match(new Request(PREFETCH_DIAGNOSTIC_URL));
    if (response) return await response.json();
  } catch {}
  return { protocol: AUDIO_PROTOCOL_VERSION, build: BUILD_VERSION, epoch: audioCacheEpoch, runs: [] };
}

function prefetchStatusMessage(run) {
  return {
    type: 'ky:prefetch-status',
    protocol: AUDIO_PROTOCOL_VERSION,
    runId: run.id,
    build: BUILD_VERSION,
    epoch: audioCacheEpoch,
    reason: run.reason,
    state: run.state,
    total: run.total,
    stored: run.stored,
    hit: run.hit,
    failed: run.failed,
    priority: run.priority,
    startedAt: run.startedAt,
    finishedAt: run.finishedAt,
  };
}

async function publishPrefetchRun(run) {
  await persistPrefetchRun(run);
  await broadcastToWindows(prefetchStatusMessage(run));
  if (run.failed) {
    await broadcastToWindows({
      type: 'ky:prefetch-failed',
      protocol: AUDIO_PROTOCOL_VERSION,
      runId: run.id,
      build: BUILD_VERSION,
      epoch: audioCacheEpoch,
      count: run.failed,
      failures: run.failures,
      // 页面应把 diagnostic 持久化；SW 也把它写入 ky-prefetch-diagnostics-v1。
      diagnostic: run,
    });
  }
}

async function prefetchDataAssets(requestedPriority, reason) {
  const priority = normalizeDataAssetUrls(requestedPriority);
  const allAssets = normalizeDataAssetUrls(DATA_ASSETS);
  const prioritySet = new Set(priority);
  const ordered = priority.concat(allAssets.filter(url => !prioritySet.has(url)));
  if (!ordered.length) return null;
  prefetchRunSequence += 1;
  const run = {
    id: BUILD_VERSION + ':' + Date.now().toString(36) + ':' + prefetchRunSequence,
    protocol: AUDIO_PROTOCOL_VERSION,
    build: BUILD_VERSION,
    epoch: audioCacheEpoch,
    reason: reason || 'activate',
    state: 'running',
    startedAt: Date.now(),
    finishedAt: null,
    priority,
    total: ordered.length,
    stored: 0,
    hit: 0,
    failed: 0,
    failures: [],
  };
  let cache;
  try {
    cache = await caches.open(SHELL_CACHE);
  } catch (err) {
    for (const url of ordered) run.failures.push(prefetchFailure(url, err, prioritySet.has(url)));
    run.failed = ordered.length;
    run.state = 'failed';
    run.finishedAt = Date.now();
    await publishPrefetchRun(run);
    return run;
  }
  const settle = async (url, isPriority) => {
    try {
      const result = await prefetchOne(cache, url, isPriority);
      run[result.result] += 1;
    } catch (err) {
      run.failed += 1;
      run.failures.push(prefetchFailure(url, err, isPriority));
    }
  };
  // 当前页需要的资源先串行完成；其余词库只开两路，避免抢占页面正在用的带宽。
  for (const url of priority) await settle(url, true);
  const rest = ordered.filter(url => !prioritySet.has(url));
  let cursor = 0;
  const worker = async () => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      if (index >= rest.length) return;
      await settle(rest[index], false);
    }
  };
  await Promise.all([worker(), worker()]);
  run.state = run.failed ? (run.failed === run.total ? 'failed' : 'partial') : 'complete';
  run.finishedAt = Date.now();
  await publishPrefetchRun(run);
  return run;
}

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    try {
      // 根 HTML 与主脚本必须原子成功；任何 404/断网都让 install 失败。
      await Promise.all(SHELL_CORE.map(url => cache.add(new Request(url, { cache: url === APP_ASSET ? 'default' : 'reload' }))));
    } catch (err) {
      await caches.delete(SHELL_CACHE).catch(() => {});
      throw err;
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    const oldShells = names.filter(name => name.startsWith('ky-shell-') && name !== SHELL_CACHE);
    // 至少保留上一版 shell：正在运行的旧页面仍可能要旧 app.<hash>.js。
    const shellsToDelete = oldShells.slice(0, Math.max(0, oldShells.length - 1));
    await Promise.all([
      ...shellsToDelete.map(name => caches.delete(name)),
      ...names.filter(name => name.startsWith('ky-audio-') && name !== AUDIO_CACHE)
        .map(name => caches.delete(name)),
    ]);
    await self.clients.claim();
    // 新页面收到后立刻上报当前词书/章节资源；通用词库预取会与它并行，但当前页
    // 资源通过独立消息优先落盘，不再和四本词库抢同一个起跑线。
    await broadcastToWindows({
      type: 'ky:prefetch-priority-request',
      protocol: AUDIO_PROTOCOL_VERSION,
      build: BUILD_VERSION,
      epoch: audioCacheEpoch,
    });
    if (oldShells.length) {
      // 不强制导航用户正在操作的页面；页面收到消息后自行提示刷新。
      await broadcastToWindows({ type: 'ky:sw-updated', build: BUILD_VERSION });
    }
    // 激活后再补词库：主脚本已在 install 阶段保证存在。离线首屏不依赖这一步。
    await prefetchDataAssets([], 'activate');
  })());
});

// 音频缓存上限除了条数，还要看真实配额：1500 条音频可以有几十 MB。
// 所有缓冲/淘汰都走同一个串行队列，避免两个标签页同时淘汰时互相删掉刚写入的项。
async function evictAudioEntries(cache, keys, count, reason, protectedUrls) {
  const protect = protectedUrls instanceof Set ? protectedUrls : new Set(protectedUrls || []);
  const removed = [];
  const candidates = keys.filter(key => !protect.has(key.url));
  for (const oldKey of candidates.slice(0, Math.max(0, count))) {
    try {
      if (await cache.delete(oldKey)) removed.push(oldKey);
    } catch {}
  }
  if (!removed.length) return removed;
  const revision = bumpAudioRevision();
  const entries = removed.map(audioEntryFromKey);
  await broadcastToWindows({
    type: 'ky:audio-evicted',
    protocol: AUDIO_PROTOCOL_VERSION,
    build: BUILD_VERSION,
    epoch: audioCacheEpoch,
    revision,
    reason: reason || 'eviction',
    cacheName: AUDIO_CACHE,
    urls: removed.map(key => key.url),
    entries,
  });
  return removed;
}

async function audioBudgetOk() {
  try {
    if (!navigator.storage || !navigator.storage.estimate) return true;
    const { usage, quota } = await navigator.storage.estimate();
    if (!quota) return true;
    if (usage / quota > AUDIO_BUDGET_RATIO) return false;
    return quota - usage > AUDIO_BUDGET_MIN_FREE;
  } catch {
    return true;
  }
}

async function storeAudioResponse(cache, key, response) {
  return runAudioMutation(async () => {
    let stored = await safePut(cache, key, response.clone());
    // 配额满时 cache.put 会在进入淘汰逻辑前失败；先腾出至少 20% 再重试。
    if (!stored) {
      const fullKeys = await cache.keys();
      await evictAudioEntries(
        cache,
        fullKeys,
        Math.max(1, Math.ceil(fullKeys.length * 0.2)),
        'quota-retry',
        new Set([key.url]),
      );
      stored = await safePut(cache, key, response.clone());
    }
    if (!stored) return { status: 'store-failed', revision: audioCacheRevision };

    audioWriteCount += 1;
    if (audioWriteCount >= 32) {
      audioWriteCount = 0;
      const keys = await cache.keys();
      const keep = (await audioBudgetOk()) ? AUDIO_CACHE_MAX : Math.max(1, Math.floor(keys.length * 0.8));
      if (keys.length > keep) {
        await evictAudioEntries(
          cache,
          keys,
          keys.length - keep,
          keep === AUDIO_CACHE_MAX ? 'cache-limit' : 'quota-maintenance',
          new Set([key.url]),
        );
      }
    }
    const revision = bumpAudioRevision();
    return { status: 'stored', revision };
  });
}

async function cacheFirstAudio(request) {
  const cache = await caches.open(AUDIO_CACHE);
  const key = audioCacheKey(request);
  const cached = await cache.match(key);
  if (cached) return withCacheStatus(cached, 'hit', audioCacheRevision);

  let pending = pendingAudioFetches.get(key.url);
  if (!pending) {
    const task = (async () => {
      // 用规范化后的 key 发请求：服务端看到的 lang/v 与缓存身份完全一致，
      // offline 控制位不会透传，也不会因参数顺序不同产生两份音频。
      const network = await fetch(key);
      if (!network.ok) {
        return { response: network, status: 'store-failed', revision: audioCacheRevision };
      }
      const outcome = await storeAudioResponse(cache, key, network);
      return { response: network, status: outcome.status, revision: outcome.revision };
    })();
    pending = task.finally(() => {
      if (pendingAudioFetches.get(key.url) === pending) pendingAudioFetches.delete(key.url);
    });
    pendingAudioFetches.set(key.url, pending);
  }
  const result = await pending;
  return withCacheStatus(result.response.clone(), result.status, result.revision);
}

async function cacheFirstShellAsset(request, event) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request);
  if (cached) return withCacheStatus(cached, 'hit', audioCacheRevision);
  const response = await fetch(request);
  if (!response.ok) return withCacheStatus(response, 'store-failed', audioCacheRevision);
  // 页面把确认头当作离线资源真正的落盘凭据，所以这里必须等 cache.put 有结果，
  // 不能像普通静态资源那样把写入丢到 event.waitUntil() 里再乐观返回。
  const stored = await safePut(cache, request, response.clone());
  return withCacheStatus(response, stored ? 'stored' : 'store-failed', audioCacheRevision);
}

// 导航请求走 network-first：cache-first 会让部署后的首次访问仍然返回旧页面。
// 网络慢到 3 秒以上就先用缓存顶，避免弱网白屏。
async function navigationResponse(event) {
  const request = event.request;
  const cache = await caches.open(SHELL_CACHE);
  const fallback = (await cache.match(request, { ignoreSearch: true }))
    || (await cache.match('./'))
    || (await cache.match('./index.html'));
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), NAV_TIMEOUT_MS) : null;
  const network = fetch(request, controller ? { signal: controller.signal } : undefined).then(response => {
    if (response.ok) event.waitUntil(safePut(cache, request, response.clone()));
    return response;
  }).catch(() => null).finally(() => { if (timer) clearTimeout(timer); });
  if (fallback) {
    const raced = await Promise.race([
      network,
      new Promise(resolve => setTimeout(() => resolve(null), NAV_TIMEOUT_MS)),
    ]);
    if (raced && raced.ok) return raced;
    return fallback;
  }
  const response = await network;
  return response || new Response('离线缓存尚未完成，请联网打开一次。', {
    status: 503,
    headers: { 'content-type': 'text/plain; charset=utf-8' },
  });
}

async function staleWhileRevalidate(request, event) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request).then(response => {
    if (response.ok) event.waitUntil(safePut(cache, request, response.clone()));
    return response;
  }).catch(() => null);
  return cached || network || new Response('', { status: 504 });
}

function extendMessageEvent(event, task) {
  const guarded = Promise.resolve(task).catch(err => {
    console.warn('[SW] message handler failed', err);
  });
  if (event && typeof event.waitUntil === 'function') event.waitUntil(guarded);
  return guarded;
}

async function audioCacheSnapshot(requestId, includeEntries) {
  return runAudioMutation(async () => {
    const cache = await caches.open(AUDIO_CACHE);
    const keys = (await cache.keys()).filter(isAudioCacheKey);
    const entries = keys.map(audioEntryFromKey)
      .sort((a, b) => a.marker.localeCompare(b.marker) || a.cacheKey.localeCompare(b.cacheKey));
    const markers = [...new Set(entries.map(entry => entry.marker))];
    const snapshot = {
      type: 'ky:audio-cache-snapshot',
      protocol: AUDIO_PROTOCOL_VERSION,
      requestId: requestId == null ? null : String(requestId),
      build: BUILD_VERSION,
      epoch: audioCacheEpoch,
      revision: audioCacheRevision,
      cacheName: AUDIO_CACHE,
      complete: true,
      count: entries.length,
      markers,
    };
    if (includeEntries) snapshot.entries = entries;
    return snapshot;
  });
}

self.addEventListener('message', event => {
  const message = event.data && typeof event.data === 'object' ? event.data : {};
  if (message.protocol != null && Number(message.protocol) !== AUDIO_PROTOCOL_VERSION) return;

  if (message.type === 'ky:prefetch-priority') {
    const assets = Array.isArray(message.assets) ? message.assets
      : (Array.isArray(message.urls) ? message.urls : []);
    extendMessageEvent(event, prefetchDataAssets(assets, message.reason || 'page-priority'));
    return;
  }

  if (message.type === 'ky:prefetch-diagnostics-query') {
    extendMessageEvent(event, (async () => {
      const payload = await readPrefetchDiagnostics();
      const response = Object.assign({}, payload, {
        type: 'ky:prefetch-diagnostics',
        protocol: AUDIO_PROTOCOL_VERSION,
        requestId: message.requestId == null ? null : String(message.requestId),
        build: BUILD_VERSION,
        epoch: audioCacheEpoch,
      });
      if (!postToMessageSource(event.source, response)) await broadcastToWindows(response);
    })());
    return;
  }

  if (message.type === 'ky:audio-cache-query') {
    extendMessageEvent(event, (async () => {
      try {
        const snapshot = await audioCacheSnapshot(message.requestId, !!message.includeEntries);
        if (!postToMessageSource(event.source, snapshot)) await broadcastToWindows(snapshot);
      } catch (err) {
        const failure = {
          type: 'ky:audio-cache-snapshot',
          protocol: AUDIO_PROTOCOL_VERSION,
          requestId: message.requestId == null ? null : String(message.requestId),
          build: BUILD_VERSION,
          epoch: audioCacheEpoch,
          revision: audioCacheRevision,
          complete: false,
          error: String((err && err.message) || err || 'snapshot failed'),
        };
        if (!postToMessageSource(event.source, failure)) await broadcastToWindows(failure);
      }
    })());
  }
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  // 有道发音是跨域响应，浏览器只会给 opaque：既读不到内容也判断不出成功与否，
  // 一旦把错误响应缓存进去，那个词就永久没声音。宁可播放时直连（0.2s），
  // 离线副本统一走自家 worker（能判断 200）。
  if (url.origin !== self.location.origin) return;
  if (url.pathname.includes('/api/audio')) {
    event.respondWith(cacheFirstAudio(request).catch(() => audioFailureResponse()));
    return;
  }
  if (url.pathname.startsWith('/data/')) {
    event.respondWith(cacheFirstShellAsset(request, event).catch(() => audioFailureResponse()));
    return;
  }
  if (url.pathname.includes('/api/')) return;
  if (request.mode === 'navigate') {
    event.respondWith(navigationResponse(event));
    return;
  }
  if (['script', 'style', 'image', 'font', 'manifest'].includes(request.destination)) {
    event.respondWith(staleWhileRevalidate(request, event));
  }
});
