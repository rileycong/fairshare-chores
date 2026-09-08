const CACHE_NAME = "fairshare-v1";
const APP_SHELL = ["/", "/static/css/base.css", "/offline/"];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
    );
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((keys) =>
                Promise.all(
                    keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
                )
            )
    );
    self.clients.claim();
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    if (request.method !== "GET") return;

    const acceptsHtml = (request.headers.get("accept") || "").includes("text/html");
    if (acceptsHtml) {
        event.respondWith(
            fetch(request).catch(() => caches.match("/offline/"))
        );
        return;
    }

    if (new URL(request.url).origin === self.location.origin) {
        event.respondWith(
            caches.match(request).then((cached) => cached || fetch(request))
        );
    }
});
