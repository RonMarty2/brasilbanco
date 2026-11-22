const CACHE_NAME = "remesas-pwa-v2";
const SHARE_CACHE_NAME = "remesas-share-tmp";
const ASSETS_TO_CACHE = [
  "/pwa/",
  "/pwa/index.html",
  "/pwa/app.js",
  "/pwa/manifest.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE).catch((err) => {
        console.log("Error inicializando caché offline", err);
      });
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME && key !== SHARE_CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Web Share Target (WhatsApp -> PWA)
  if (
    event.request.method === "POST" &&
    (url.pathname.endsWith("/pwa/index.html") || url.pathname.endsWith("/pwa/share-target"))
  ) {
    event.respondWith(
      (async () => {
        try {
          const formData = await event.request.formData();
          const file = formData.get("voucher") || formData.get("voucher_share");
          if (file) {
            const cache = await caches.open(SHARE_CACHE_NAME);
            await cache.put(
              "/shared-voucher",
              new Response(file, {
                headers: {
                  "Content-Type": file.type || "image/jpeg",
                  "X-Filename": encodeURIComponent(file.name || "voucher.jpg")
                }
              })
            );
          }
        } catch (err) {
          console.error("Error procesando share-target:", err);
        }
        return Response.redirect("/pwa/?shared=1", 303);
      })()
    );
    return;
  }

  // Red de primero para API, caché para assets estáticos
  if (event.request.url.includes("/api/")) {
    event.respondWith(fetch(event.request));
    return;
  }

  event.respondWith(
    fetch(event.request).catch(() => {
      return caches.match(event.request);
    })
  );
});
