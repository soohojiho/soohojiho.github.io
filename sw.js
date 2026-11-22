/* 수호&지호 가족대시보드 — 오프라인 캐시 (앱처럼 쓰기) */
const CACHE = 'suho-jiho-dashboard-v16';
const ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png',
  './icon-maskable-512.png',
  './apple-touch-icon.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(ASSETS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // /workout/ (오운완 운동일지), /foodmap/ (내 맛집·휴게소 지도)은 각자의 서비스 워커가 맡는다.
  // 여기서 가로채면 오프라인 시 가족대시보드 index.html이 대신 나가므로 손대지 않고 통과시킨다.
  if (url.pathname === '/workout' || url.pathname.startsWith('/workout/')) return;
  if (url.pathname === '/foodmap' || url.pathname.startsWith('/foodmap/')) return;

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
    caches.match(req).then((hit) => hit || fetch(req).catch(() => hit))
  );
});
