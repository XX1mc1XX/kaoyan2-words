const BUILD_VERSION = '4e120f40cd87';
const SHELL_CACHE = 'ky-shell-' + BUILD_VERSION;
const AUDIO_CACHE = 'ky-audio-v2';
// 页面只有在收到这个响应头后才允许写本地「已缓存」标记。
const CACHE_STATUS_HEADER = 'x-ky-cache';
// 四本词库合计三千多词，中英文各一条音频，「下载全部」要能一次装下。
// 真正卡体积的是下面的配额检查。
const AUDIO_CACHE_MAX = 8000;
// 导航请求的 network-first 超时：超过就先用缓存顶，避免弱网白屏
const NAV_TIMEOUT_MS = 3000;
// 配额吃到 80% 或剩余不到 8MB 就不再缓存新音频
const AUDIO_BUDGET_RATIO = 0.8;
const AUDIO_BUDGET_MIN_FREE = 8 * 1024 * 1024;
// 只缓存根路径一份页面：'./' 在部署环境里就是 index.html，重复缓存会白占一倍空间
const APP_ASSET = './app.9775dd28fffb.js';
const DATA_ASSETS = ["./data/words.b5ef547ac5fc.json", "./data/derivatives.47bc601b592b.json", "./data/basic.c44eb02808ef.json", "./data/insurance.ed6ab2b6e23c.json"];
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

function audioCacheKey(request) {
  const url = new URL(request.url);
  // offline=1 只表达本次请求要求「写成功才算成功」，不参与缓存身份，
  // 否则在线播放和离线下载会各存一份相同音频。
  url.searchParams.delete('offline');
  return new Request(url.toString(), { method: 'GET' });
}

function withCacheStatus(response, status) {
  const headers = new Headers(response.headers);
  headers.set(CACHE_STATUS_HEADER, status);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
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
    // 激活后再补词库：主脚本已在 install 阶段保证存在。
    const shellCache = await caches.open(SHELL_CACHE);
    const results = await Promise.allSettled(DATA_ASSETS.map(url => shellCache.add(new Request(url, { cache: 'reload' }))));
    const failed = results.filter(x => x.status === 'rejected');
    if (failed.length) console.warn('[SW] data prefetch incomplete', failed.length);
    if (failed.length) {
      const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const client of wins) { try { client.postMessage({ type: 'ky:prefetch-failed', count: failed.length }); } catch {} }
    }
    if (!oldShells.length) return;
    // 不强制导航用户正在操作的页面；页面收到消息后自行提示刷新。
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    await Promise.allSettled(windows.map(client => {
      try {
        if (new URL(client.url).origin !== self.location.origin) return Promise.resolve(null);
        client.postMessage({ type: 'ky:sw-updated', build: BUILD_VERSION });
        return Promise.resolve(null);
      } catch {
        return Promise.resolve(null);
      }
    }));
  })());
});

// 音频缓存上限除了条数，还要看真实配额：1500 条音频可以有几十 MB。
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

async function cacheFirstAudio(request) {
  const cache = await caches.open(AUDIO_CACHE);
  const key = audioCacheKey(request);
  const cached = await cache.match(key);
  if (cached) return withCacheStatus(cached, 'hit');
  const response = await fetch(request);
  // 走到这里的只有自家的 /api/audio：同源响应，ok 能如实反映成败。
  if (!response.ok) return response;
  const stored = await safePut(cache, key, response.clone());
  if (!stored) {
    // 正常播放仍可继续用刚拿到的音频；页面绝不能把它记成离线可用。
    return withCacheStatus(response, 'store-failed');
  }
  const keys = await cache.keys();
  const keep = (await audioBudgetOk()) ? AUDIO_CACHE_MAX : Math.floor(AUDIO_CACHE_MAX * 0.9);
  if (keys.length > keep) {
    const removed = [];
    for (const oldKey of keys.slice(0, keys.length - keep)) {
      try { await cache.delete(oldKey); removed.push(oldKey.url); } catch {}
    }
    if (removed.length && self.clients && self.clients.matchAll) {
      const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const client of wins) {
        try { client.postMessage({ type: 'ky:audio-evicted', urls: removed }); } catch {}
      }
    }
  }
  return withCacheStatus(response, 'stored');
}

async function cacheFirstShellAsset(request, event) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok && event) event.waitUntil(safePut(cache, request, response.clone()));
  return response;
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

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  // 有道发音是跨域响应，浏览器只会给 opaque：既读不到内容也判断不出成功与否，
  // 一旦把错误响应缓存进去，那个词就永久没声音。宁可播放时直连（0.2s），
  // 离线副本统一走自家 worker（能判断 200）。
  if (url.origin !== self.location.origin) return;
  if (url.pathname.includes('/api/audio')) {
    event.respondWith(cacheFirstAudio(request).catch(() => new Response('', { status: 503 })));
    return;
  }
  if (url.pathname.startsWith('/data/')) {
    event.respondWith(cacheFirstShellAsset(request, event).catch(() => new Response('', { status: 503 })));
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
