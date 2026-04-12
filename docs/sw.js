const CACHE = 'vocab-v59';
const SHELL = [
  './',
  './index.html',
  './vocab.css',
  './vocab.js',
  './manifest.json',
  './icons.svg',
  './icons/icon-192.svg',
  './icons/icon-512.svg',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // vocab.json / vocab_public.json: network first, fall back to cache
  if (url.pathname.endsWith('vocab.json') || url.pathname.endsWith('vocab_public.json')) {
    e.respondWith(
      fetch(e.request)
        .then(res => {
          if (res.ok) caches.open(CACHE).then(c => c.put(e.request, res.clone()));
          return res;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Navigation requests: serve cached index.html so app always loads
  if (e.request.mode === 'navigate') {
    e.respondWith(
      caches.match('./index.html').then(cached => cached || fetch(e.request))
    );
    return;
  }

  // App shell: cache first, fall back to network
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
