const BUILD_VERSION = 'cdcc5f12e068';
const SHELL_CACHE = 'ky-shell-' + BUILD_VERSION;
const AUDIO_CACHE = 'ky-audio-v1';
const AUDIO_CACHE_MAX = 1500;
// 只缓存根路径一份页面：'./' 在部署环境里就是 index.html，重复缓存会白占一倍空间
const SHELL = ['./', './manifest.webmanifest', './icon-192.png', './icon-512.png'];

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    await Promise.allSettled(SHELL.map(url => cache.add(new Request(url, { cache: 'reload' }))));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name =>
      (name.startsWith('ky-shell-') && name !== SHELL_CACHE)
      || (name.startsWith('ky-audio-') && name !== AUDIO_CACHE),
    ).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

async function cacheFirstAudio(request) {
  const cache = await caches.open(AUDIO_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(request, response.clone());
    const keys = await cache.keys();
    if (keys.length > AUDIO_CACHE_MAX) {
      for (const key of keys.slice(0, keys.length - AUDIO_CACHE_MAX)) await cache.delete(key);
    }
  }
  return response;
}

async function navigationResponse(event) {
  const request = event.request;
  const cache = await caches.open(SHELL_CACHE);
  const cached = (await cache.match(request, { ignoreSearch: true }))
    || (await cache.match('./'))
    || (await cache.match('./index.html'));
  const network = fetch(request).then(response => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => null);
  if (cached) {
    event.waitUntil(network);
    return cached;
  }
  const response = await network;
  return response || new Response('离线缓存尚未完成，请联网打开一次。', {
    status: 503,
    headers: { 'content-type': 'text/plain; charset=utf-8' },
  });
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request).then(response => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => null);
  return cached || network || new Response('', { status: 504 });
}

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.includes('/api/audio')) {
    event.respondWith(cacheFirstAudio(request).catch(() => new Response('', { status: 503 })));
    return;
  }
  if (url.pathname.includes('/api/')) return;
  if (request.mode === 'navigate') {
    event.respondWith(navigationResponse(event));
    return;
  }
  if (['script', 'style', 'image', 'font', 'manifest'].includes(request.destination)) {
    event.respondWith(staleWhileRevalidate(request));
  }
});
