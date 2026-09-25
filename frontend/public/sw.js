/**
 * Drishti Service Worker
 * Strategy:
 *   - App shell (navigation): network-first → cache fallback
 *   - Next.js static chunks (_next/*): stale-while-revalidate
 *   - API calls (/v1/*, cross-origin): pass-through (no caching)
 *   - Background Sync: notify active clients to trigger page-level queue processor
 *
 * NOTE: This SW is intentionally minimal for MVP. The Android native app will
 * replace the capture/sync path entirely; this SW only powers the PWA shell.
 */

const CACHE = "aci-shell-v3";
const OFFLINE_SHELL = "/sessions";

/* ── Install ──────────────────────────────────────────────────────────────── */

self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then((c) =>
      c.addAll([OFFLINE_SHELL]).catch(() => {
        // Non-fatal — cache warm-up is best-effort
      })
    )
  );
});

/* ── Activate ─────────────────────────────────────────────────────────────── */

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

/* ── Fetch ────────────────────────────────────────────────────────────────── */

self.addEventListener("fetch", (e) => {
  const { request } = e;
  const url = new URL(request.url);

  // Only handle GET requests from our own origin
  if (request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;

  // Skip API calls — let them fail naturally so the page handles offline state
  if (url.pathname.startsWith("/v1/")) return;
  if (url.port === "8000") return;

  // Next.js chunks: network-first so code changes appear immediately in dev.
  // Only fall back to cache when offline.
  if (url.pathname.startsWith("/_next/static/")) {
    e.respondWith(
      fetch(request)
        .then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(CACHE).then((c) => c.put(request, clone));
          }
          return res;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Navigation requests: network-first, cache fallback
  if (request.mode === "navigate") {
    e.respondWith(
      fetch(request)
        .then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(CACHE).then((c) => c.put(request, clone));
          }
          return res;
        })
        .catch(() =>
          caches
            .match(request)
            .then((cached) => cached || caches.match(OFFLINE_SHELL))
            .then(
              (res) =>
                res ||
                new Response(
                  "<!DOCTYPE html><html><body><p>Drishti is offline. Reconnect to continue.</p></body></html>",
                  {
                    status: 503,
                    headers: { "Content-Type": "text/html" },
                  }
                )
            )
        )
    );
    return;
  }
});

/* ── Background Sync ──────────────────────────────────────────────────────── */

self.addEventListener("sync", (e) => {
  if (e.tag === "aci-frame-sync") {
    // Notify all open clients to run their page-level sync queue.
    // If no clients are open, uploads will start on next page load.
    e.waitUntil(
      self.clients
        .matchAll({ includeUncontrolled: true, type: "window" })
        .then((clients) =>
          clients.forEach((c) => c.postMessage({ type: "BACKGROUND_SYNC" }))
        )
    );
  }
});

/* ── Push (placeholder for future use) ───────────────────────────────────── */

self.addEventListener("push", (e) => {
  if (!e.data) return;
  const data = e.data.json();
  e.waitUntil(
    self.registration.showNotification(data.title ?? "Drishti", {
      body: data.body ?? "",
      icon: "/icon.svg",
      badge: "/icon.svg",
    })
  );
});
