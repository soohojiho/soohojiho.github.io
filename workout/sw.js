/* 오운완 운동일지 — /workout/ 범위 전용 오프라인 캐시
   가족대시보드 루트(/sw.js)와는 범위(scope)가 분리되어 있어 서로 간섭하지 않습니다. */
const CACHE = 'owunwan-workout-v1';
const SCOPE_PATH = '/workout/';
const CORE = [
  './',
  './index.html',
  './manifest.json',
  './icon.svg',
  './icon-192.png',
  './icon-512.png',
  './icon-maskable-512.png',
  './apple-touch-icon.png'
];
const CDN = [
  'https://cdn.tailwindcss.com'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(CORE).catch(() => {}))
      .then((cache) => Promise.all(
        CDN.map((url) => fetch(url, { mode: 'cors' })
          .then((res) => res.ok ? cache.put(url, res) : null)
          .catch(() => null))
      ).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE && k.indexOf('owunwan') === 0).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Tailwind CDN: 캐시 우선(오프라인에서도 스타일 유지)
  if (url.hostname === 'cdn.tailwindcss.com') {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((cache) => cache.put(req, copy)).catch(() => {});
        return res;
      }).catch(() => Response.error()))
    );
    return;
  }

  if (url.origin !== self.location.origin) return;
  if (url.pathname.indexOf(SCOPE_PATH) !== 0) return;

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match('./index.html')))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((hit) => {
      if (hit) {
        fetch(req).then((res) => {
          if (res && res.ok) caches.open(CACHE).then((cache) => cache.put(req, res.clone())).catch(() => {});
        }).catch(() => {});
        return hit;
      }
      return fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((cache) => cache.put(req, copy)).catch(() => {});
        return res;
      });
    })
  );
});
