/* 내 전국 맛집·휴게소 지도 — /foodmap/ 범위 전용 오프라인 캐시
   루트(가족대시보드) 서비스 워커와는 scope가 분리되어 서로 간섭하지 않습니다. */
const CACHE = 'my-foodmap-v2';
const SCOPE_PATH = '/foodmap/';
const CORE = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  './icon-maskable-512.png',
  './apple-touch-icon.png'
];
const CDN = [
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(CORE).catch(() => {}))
      .then((cache) => Promise.all(
        CDN.map((url) => fetch(url, { mode: 'cors' })
          .then((res) => (res && res.ok) ? cache.put(url, res) : null)
          .catch(() => null))
      ).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE && k.indexOf('my-foodmap') === 0).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // 지도 타일은 네트워크에서 바로 (캐시로 용량을 채우지 않도록 통과)
  if (url.hostname.endsWith('tile.openstreetmap.org')) return;

  // Leaflet CDN: 캐시 우선 (오프라인에서도 지도 스타일 유지)
  if (url.hostname === 'unpkg.com' || url.hostname === 'cdn.jsdelivr.net') {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
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
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
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
          if (res && res.ok) caches.open(CACHE).then((c) => c.put(req, res.clone())).catch(() => {});
        }).catch(() => {});
        return hit;
      }
      return fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      });
    })
  );
});
