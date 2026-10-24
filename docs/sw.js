/* Guarda la app en el equipo para que abra SIN internet.
   Al cambiar cualquier archivo de la app, sube VERSION: los equipos la renuevan solos. */
const VERSION = "verificador-2.0.6";
const ARCHIVOS = ["./", "index.html", "estilos.css", "app.js", "config.js", "codigos.js", "datos.js", "pantalla.js",
                  "manifest.webmanifest", "fuentes/Sora.ttf", "icono.svg", "icono-192.png", "icono-512.png"];

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
  const destino = new URL(pedido.url);
  if (pedido.method !== "GET" || destino.origin !== self.location.origin) return;  // Supabase: directo
  if (destino.pathname.endsWith("/version.txt") || destino.pathname.endsWith("/apps.json")) return;   // siempre de internet
  if (pedido.mode === "navigate" && !/\/(privacidad|condiciones)\.html$/.test(destino.pathname)) {
    // La página siempre desde el equipo (con o sin ?estado=...).
    e.respondWith(caches.match("index.html").then(function (r) { return r || fetch(pedido); }));
    return;
  }
  e.respondWith(caches.match(pedido, { ignoreSearch: true }).then(function (r) { return r || fetch(pedido); }));
});
