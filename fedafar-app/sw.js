// ── Service Worker FEDAFAR PWA ──────────────────────────────────────────────
// Estrategia:
//   - /api/*            → SOLO red (precios, stock y cuentas siempre frescos)
//   - navegación (HTML) → red primero, cae a caché si no hay conexión
//   - assets estáticos  → caché con revalidación en segundo plano
//
// Subí el número de versión cada vez que quieras forzar la actualización del caché.
const CACHE_VERSION = 'fedafar-v2';
const APP_SHELL = [
  '/tienda/',
  '/tienda/index.html',
  '/tienda/app.js',
  '/tienda/style.css',
  '/tienda/manifest.json',
  '/tienda/icon-192.png',
  '/tienda/icon-512.png',
];

// Instalación: precachear la cáscara de la app
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

// Activación: limpiar cachés viejos
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // Solo manejamos GET; el resto (POST/PUT...) va directo a la red
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // 1) Datos del backend → SIEMPRE red, nunca caché
  if (url.pathname.startsWith('/api/')) {
    return; // deja que el navegador lo maneje normalmente (network)
  }

  // 2) Navegación (cargar la página) → red primero, caché de respaldo offline
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then((c) => c.put('/tienda/index.html', copy));
          return res;
        })
        .catch(() => caches.match('/tienda/index.html'))
    );
    return;
  }

  // 3) Assets estáticos (JS, CSS, imágenes, fuentes, CDN) → stale-while-revalidate
  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req)
        .then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone();
            caches.open(CACHE_VERSION).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
