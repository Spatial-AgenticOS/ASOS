/**
 * FERAL service worker — minimal PWA install + offline shell.
 *
 * Caching strategy (intentionally narrow):
 *   - ``cache-first`` for /assets/* (Vite emits content-hashed names, so
 *     they're immutable; serving the cached copy is always safe).
 *   - ``no-store`` (bypass cache entirely) for auth- and pair-sensitive
 *     paths: /api/setup/*, /api/devices/pair/*, /api/auth/*. Stale
 *     responses for these paths would lock the user into broken state
 *     (e.g. "setup_complete: false" cached forever) — explicitly opt out.
 *   - ``no-fetch-handler`` for /v1/*. WebSocket upgrade requests must
 *     never go through the SW; the spec allows it but Chrome's
 *     fetch-respondWith path interferes with the upgrade handshake
 *     intermittently. Pass-through.
 *   - ``network-first, fallback-to-cache`` for everything else.
 *   - On any /api/* response with status 401: clear runtime cache so
 *     a stale token doesn't trap the user.
 */

// v2026.5.29 — bumped from v1 → v2 so the old cache (which precached a
// manifest.webmanifest path that may have 404'd on installed wheels) is
// pruned on next activation. Without the bump, operators upgrading would
// keep seeing the synthetic ``503 Offline`` for cached-miss fetches that
// initiated from the old service worker.
const VERSION = 'feral-sw-v3';
const STATIC_CACHE = `feral-static-${VERSION}`;
const RUNTIME_CACHE = `feral-runtime-${VERSION}`;

const STATIC_ASSETS = [
  '/',
  '/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(STATIC_ASSETS)).then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  // Intentionally NO ``self.clients.claim()`` here. Calling claim()
  // makes the SW take over all open pages immediately on first
  // activation, which iOS Safari has historically translated into a
  // forced reload of the page. On the /pair landing, that reload
  // arrived between the WS open and the node_register completing —
  // silently killing the pairing flow with a "connecting…" hang.
  // The SW becomes active on the next navigation; that's good enough
  // for a PWA install and avoids the reload race entirely.
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== STATIC_CACHE && k !== RUNTIME_CACHE)
          .map((k) => caches.delete(k)),
      ),
    ),
  );
});

function isAuthSensitive(pathname) {
  return (
    pathname.startsWith('/api/setup/') ||
    pathname.startsWith('/api/devices/pair/') ||
    pathname.startsWith('/api/auth/')
  );
}

function isWsOrApi(pathname) {
  return pathname.startsWith('/v1/');
}

function isHashedAsset(pathname) {
  return pathname.startsWith('/assets/');
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // WebSocket upgrade or v1 stream — pass through unmodified.
  if (isWsOrApi(url.pathname)) return;

  // Auth-sensitive: bypass cache entirely.
  if (isAuthSensitive(url.pathname)) {
    event.respondWith(
      fetch(req, { cache: 'no-store' }).then(async (resp) => {
        if (resp && resp.status === 401) {
          const runtime = await caches.open(RUNTIME_CACHE);
          const reqs = await runtime.keys();
          await Promise.all(reqs.map((r) => runtime.delete(r)));
        }
        return resp;
      }),
    );
    return;
  }

  // Hashed assets — cache-first, immutable.
  if (isHashedAsset(url.pathname)) {
    event.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then(async (resp) => {
        if (resp && resp.ok) {
          const runtime = await caches.open(RUNTIME_CACHE);
          await runtime.put(req, resp.clone());
        }
        return resp;
      })),
    );
    return;
  }

  // Everything else (API GETs not in the bypass list, navigation
  // requests for the SPA shell): network-first, fallback to cache,
  // final fallback to / shell so SPA still boots offline.
  event.respondWith(
    fetch(req).then(async (resp) => {
      if (resp && resp.ok && req.url.startsWith(self.location.origin)) {
        const runtime = await caches.open(RUNTIME_CACHE);
        await runtime.put(req, resp.clone());
      }
      return resp;
    }).catch(async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      if (req.mode === 'navigate') {
        return caches.match('/') || new Response('Offline', { status: 503 });
      }
      return new Response('Offline', { status: 503 });
    }),
  );
});
