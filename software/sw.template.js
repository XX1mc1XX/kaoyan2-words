const BUILD_VERSION = '__BUILD_VERSION__';
const SHELL_CACHE = 'ky-shell-' + BUILD_VERSION;
const AUDIO_CACHE = 'ky-audio-v2';
// 四本词库合计三千多词，中英文各一条音频，「下载全部」要能一次装下。
// 真正卡体积的是下面的配额检查。
const AUDIO_CACHE_MAX = 8000;
// 导航请求的 network-first 超时：超过就先用缓存顶，避免弱网白屏
const NAV_TIMEOUT_MS = 3000;
// 配额吃到 80% 或剩余不到 8MB 就不再缓存新音频
const AUDIO_BUDGET_RATIO = 0.8;
const AUDIO_BUDGET_MIN_FREE = 8 * 1024 * 1024;
// 只缓存根路径一份页面：'./' 在部署环境里就是 index.html，重复缓存会白占一倍空间
const DATA_ASSETS = __DATA_ASSETS__;
// 首装只等页面壳这几个小文件。四本词库和主程序五百多 KB 放到激活后再补，
// 否则第一次打开会一直卡在 SW 安装，浏览器标签上的进度条也停不下来。
const SHELL_CORE = ['./', './manifest.webmanifest', './icon-192.png', './icon-512.png'];

// 写缓存一律允许失败：配额满时 cache.put 会 reject，
// 让它冒泡会把一个明明已经拿到的响应变成 503。
async function safePut(cache, request, response) {
  try {
    await cache.put(request, response);
  } catch {}
}

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    // 用 all 而不是 allSettled：任一资源 404 都该让安装失败并等浏览器重试，
    // 否则会激活一个半成品的壳，离线时直接白屏而且不会自己恢复。
    await Promise.all(SHELL_CORE.map(url => cache.add(new Request(url, { cache: 'reload' }))));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    const hadOldShell = names.some(name => name.startsWith('ky-shell-') && name !== SHELL_CACHE);
    await Promise.all(names.filter(name =>
      (name.startsWith('ky-shell-') && name !== SHELL_CACHE)
      || (name.startsWith('ky-audio-') && name !== AUDIO_CACHE),
    ).map(name => caches.delete(name)));
    await self.clients.claim();
    // 激活后再补词库分片和主程序：这时页面已经能用了，慢一点不影响首屏
    const shellCache = await caches.open(SHELL_CACHE);
    await Promise.allSettled(DATA_ASSETS.map(url => shellCache.add(new Request(url, { cache: 'reload' }))));
    if (!hadOldShell) return;
    // 新版本接管后主动刷新已打开的页面，避免用户长期看到旧缓存。
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    await Promise.allSettled(windows.map(client => {
      try {
        const url = new URL(client.url);
        if (url.origin !== self.location.origin) return Promise.resolve(null);
        return client.navigate(client.url);
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
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  // 走到这里的只有自家的 /api/audio：同源响应，ok 能如实反映成败。
  // 失败的响应一旦进缓存，那个词就永久没声音，所以只存 200。
  if (response.ok && await audioBudgetOk()) {
    await safePut(cache, request, response.clone());
    const keys = await cache.keys();
    if (keys.length > AUDIO_CACHE_MAX) {
      for (const key of keys.slice(0, keys.length - AUDIO_CACHE_MAX)) {
        try { await cache.delete(key); } catch {}
      }
    }
  }
  return response;
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
  const network = fetch(request).then(response => {
    if (response.ok) event.waitUntil(safePut(cache, request, response.clone()));
    return response;
  }).catch(() => null);
  if (fallback) {
    const raced = await Promise.race([
      network,
      new Promise(resolve => setTimeout(() => resolve(null), NAV_TIMEOUT_MS)),
    ]);
    // 只认成功的网络响应：运营商劫持页、部署中的 5xx 都不该盖掉本来能用的缓存
    if (raced && raced.ok) return raced;
    event.waitUntil(network);
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
