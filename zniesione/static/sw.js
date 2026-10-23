// Service worker aplikacji zniesione.pl: instalacja na telefonie i szybkie uruchamianie.
// Pliki statyczne (z wersją w adresie) z pamięci podręcznej; strona i API zawsze z sieci, żeby dane były aktualne.
const CACHE = 'zniesione-v1';
const SHELL = ['/', '/static/icons/icon-192.png', '/static/manifest.webmanifest'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  if (url.pathname.startsWith('/static/')) {  // adresy z ?v=wersja: bezpiecznie z pamięci podręcznej
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(res => {
      if (res.ok) caches.open(CACHE).then(c => c.put(e.request, res.clone()));
      return res;
    })));
  } else if (e.request.mode === 'navigate') {  // strona: z sieci, bez sieci ostatnia zapisana wersja
    e.respondWith(fetch(e.request).then(res => {
      caches.open(CACHE).then(c => c.put('/', res.clone()));
      return res;
    }).catch(() => caches.match('/')));
  }
});
