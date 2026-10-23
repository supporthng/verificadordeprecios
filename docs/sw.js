/* Guarda la app en el equipo para que abra SIN internet.
   Al cambiar cualquier archivo de la app, sube VERSION: los equipos la renuevan solos. */
const VERSION = "verificador-1.0.0";
const ARCHIVOS = ["./", "index.html", "estilos.css", "app.js", "codigos.js", "datos.js",
                  "manifest.webmanifest", "icono.svg", "icono-192.png", "icono-512.png"];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(VERSION)
    .then(function (c) { return c.addAll(ARCHIVOS.map(function (a) { return new Request(a, { cache: "reload" }); })); })
    .then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys()
    .then(function (claves) { return Promise.all(claves.filter(function (k) { return k !== VERSION; })
      .map(function (k) { return caches.delete(k); })); })
    .then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (e) {
  const pedido = e.request;
  if (pedido.method !== "GET" || new URL(pedido.url).origin !== self.location.origin) return;  // Supabase: directo
  if (pedido.mode === "navigate") {
    // La página siempre desde el equipo (con o sin ?estado=...).
    e.respondWith(caches.match("index.html").then(function (r) { return r || fetch(pedido); }));
    return;
  }
  e.respondWith(caches.match(pedido, { ignoreSearch: true }).then(function (r) { return r || fetch(pedido); }));
});
