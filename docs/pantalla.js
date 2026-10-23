/* Dibujo de la pantalla lectora: estilo, colores, textos, logo, nombre y QR.
   Lo usan app.js (los equipos) y la vista previa de la página Apariencia, así que lo que
   se ve en la vista previa es exactamente lo que verán los equipos. No guarda ni descarga nada. */
(function () {
  "use strict";
  const PREDETERMINADA = {
    nombre_negocio: "", mostrar_nombre: true, estilo: "claro", color_marca: "#0757d4",
    posicion_logo: "esquina", titulo_espera: "Escanea tu producto",
    mensaje_espera: "Pasa el código de barras por el lector",
    texto_qr: "Consulta también desde tu celular", moneda: "RD$",
    mostrar_logo: true, mostrar_qr: true, mostrar_cuadro: false,
  };
  const ESTILOS = ["claro", "noche", "marca", "etiqueta", "panel"];
  const FONDO = { claro: "#ffffff", noche: "#10213d", etiqueta: "#ffffff" };
  const TINTA = "#0f2440", BLANCO = "#ffffff";
  const $ = function (id) { return document.getElementById(id); };
  let actual = Object.assign({}, PREDETERMINADA);

  /* ---------------- colores: siempre legibles, elija el negocio el color que elija */
  function rgb(hex) {
    const n = parseInt(String(hex).slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function hex(c) { return "#" + c.map(function (v) { return Math.round(v).toString(16).padStart(2, "0"); }).join(""); }
  function luminancia(color) {
    const c = rgb(color).map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  function contraste(a, b) {
    const x = luminancia(a), y = luminancia(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  }
  function mezclar(a, b, t) {
    const x = rgb(a), y = rgb(b);
    return hex(x.map(function (v, i) { return v + (y[i] - v) * t; }));
  }
  /* Acerca el color hacia oscuro (fondo claro) o claro (fondo oscuro) hasta que se lea. */
  function legible(color, fondo, minimo) {
    // Solo se ajusta un poco: si hace falta más, el color quedaría turbio y se usa el texto normal.
    const hacia = luminancia(fondo) > 0.4 ? TINTA : BLANCO;
    for (let t = 0; t <= 0.1501; t += 0.05) {
      const c = mezclar(color, hacia, t);
      if (contraste(c, fondo) >= minimo) return c;
    }
    return hacia;
  }
  function sobre(fondo) { return contraste(BLANCO, fondo) >= contraste(TINTA, fondo) ? BLANCO : TINTA; }

  function normalizar(a) {
    const r = Object.assign({}, PREDETERMINADA);
    if (a && typeof a === "object") {
      Object.keys(PREDETERMINADA).forEach(function (k) {
        if (a[k] === undefined || a[k] === null) return;
        if (typeof PREDETERMINADA[k] === "boolean") r[k] = !!a[k];
        else if (k !== "nombre_negocio" && String(a[k]).trim() === "") return;
        else r[k] = String(a[k]);
      });
    }
    if (ESTILOS.indexOf(r.estilo) < 0) r.estilo = "claro";
    if (r.posicion_logo !== "centro") r.posicion_logo = "esquina";
    if (!/^#[0-9a-f]{6}$/i.test(r.color_marca)) r.color_marca = PREDETERMINADA.color_marca;
    return r;
  }

  function poner(id, mostrar, texto) {
    const el = $(id);
    if (!el) return;
    el.hidden = !mostrar;
    if (texto !== undefined) el.textContent = texto;
  }
  function imagen(id, mostrar, src) {
    const el = $(id);
    if (!el) return;
    if (src && el.getAttribute("src") !== src) el.src = src;
    el.hidden = !(mostrar && src);
  }

  /* a: apariencia (estado.json); img: { logo, qr } con direcciones de imagen o null. */
  function aplicar(a, img) {
    actual = normalizar(a);
    img = img || {};
    const e = actual.estilo, marca = actual.color_marca, raiz = document.documentElement.style;
    const cuerpo = document.body;
    ESTILOS.forEach(function (x) { cuerpo.classList.toggle("estilo-" + x, x === e); });
    cuerpo.classList.toggle("logo-centro", actual.posicion_logo === "centro" && e !== "panel");
    cuerpo.classList.toggle("logo-esquina", !(actual.posicion_logo === "centro" && e !== "panel"));

    const fondo = e === "marca" ? marca : (FONDO[e] || BLANCO);
    const tinta = e === "marca" ? sobre(marca) : (e === "noche" ? "#f3f6fb" : TINTA);
    raiz.setProperty("--marca", marca);
    raiz.setProperty("--sobre-marca", sobre(marca));
    raiz.setProperty("--papel", fondo);
    raiz.setProperty("--tinta", tinta);
    raiz.setProperty("--gris", e === "marca" ? mezclar(tinta, fondo, 0.3) : (e === "noche" ? "#9fb0c8" : "#6b7a90"));
    raiz.setProperty("--linea", e === "marca" ? mezclar(tinta, fondo, 0.78) : (e === "noche" ? "#24395c" : "#e6ebf2"));
    // Precio y detalles: el color del negocio, ajustado si sobre el fondo no se leería bien.
    raiz.setProperty("--precio", e === "marca" ? tinta : (e === "etiqueta" ? TINTA : legible(marca, fondo, e === "noche" ? 4.5 : 3)));
    raiz.setProperty("--acento", e === "marca" ? tinta : legible(marca, fondo, 2.2));
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", e === "panel" ? marca : fondo);

    const nombre = actual.mostrar_nombre ? actual.nombre_negocio.trim() : "";
    const logo = actual.mostrar_logo ? img.logo : null;
    const qr = actual.mostrar_qr ? img.qr : null;
    const panel = e === "panel";

    // Logo y nombre: en la cabecera (o en el panel lateral).
    imagen("logo", !panel, logo);
    poner("nombre-negocio", !panel && !!nombre, nombre);
    $("cabecera").hidden = panel || !(logo || nombre);
    cuerpo.classList.toggle("sin-logo", !logo);
    imagen("panel-logo", panel, logo);
    poner("panel-nombre", panel && !!nombre, nombre);
    // En el precio, una referencia pequeña de dónde está el cliente.
    imagen("resultado-logo", !panel, logo);
    poner("resultado-negocio", !panel && !!nombre, nombre);
    $("resultado-cabecera").hidden = panel || !(logo || nombre);

    // QR de Consulta Móvil.
    imagen("qr-img", true, qr);
    poner("qr-texto", true, actual.texto_qr);
    $("qr").hidden = panel || !qr;
    imagen("panel-qr-img", true, qr);
    poner("panel-qr-texto", true, actual.texto_qr);
    $("panel-qr").hidden = !(panel && qr);

    poner("moneda", true, actual.moneda);
    const lector = $("lector");
    if (lector) lector.classList.toggle("oculto", !actual.mostrar_cuadro);
    if (!$("espera").hidden) textosEspera(cuerpo.classList.contains("no-encontrado-activo"), $("pista").dataset.codigo || "");
    visibilidadPanel();
  }

  function visibilidadPanel() {
    const visible = !$("espera").hidden || !$("resultado").hidden;
    $("panel").hidden = !(actual.estilo === "panel" && visible);
  }

  function textosEspera(noEncontrado, codigo) {
    $("tarjeta-codigo").classList.toggle("barcode-not-found", !!noEncontrado);
    $("titulo").textContent = noEncontrado ? "No encontramos este producto" : actual.titulo_espera;
    $("titulo").classList.toggle("no-encontrado", !!noEncontrado);
    document.body.classList.toggle("no-encontrado-activo", !!noEncontrado);
    const pista = $("pista");
    pista.classList.toggle("no-encontrado", !!noEncontrado);
    pista.dataset.codigo = noEncontrado ? codigo : "";
    pista.textContent = "";
    if (noEncontrado) {
      pista.append("Código ");
      const b = document.createElement("strong");
      b.textContent = codigo;
      pista.append(b, ". Consulta el precio en caja.");
    } else {
      pista.textContent = actual.mensaje_espera;
    }
  }

  function espera(noEncontrado, codigo) {
    $("resultado").hidden = true;
    $("espera").hidden = false;
    textosEspera(noEncontrado, codigo);
    visibilidadPanel();
  }

  const formatoPrecio = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  function producto(p, codigo, segundos) {
    $("nombre").textContent = p[1];
    $("codigo").textContent = codigo;
    // Como en la etiqueta de la góndola: entero grande y centavos pequeños arriba.
    const partes = formatoPrecio.format(Number(p[2]) || 0).split(".");
    $("precio").textContent = partes[0];
    $("centavos").textContent = partes[1] || "00";
    $("resultado").setAttribute("aria-label", p[1] + ", " + actual.moneda + " " + partes.join("."));
    $("espera").hidden = true;
    $("resultado").hidden = false;
    visibilidadPanel();
    ajustarPrecio();
    // Barra que se vacía hasta volver a la pantalla de espera.
    const barra = $("cuenta-barra");
    barra.classList.remove("corriendo");
    void barra.offsetWidth;   // reiniciar la animación si llega otro producto
    barra.style.setProperty("--duracion", (segundos || 10) + "s");
    barra.classList.add("corriendo");
  }

  /* El precio siempre cabe a lo ancho, sea cual sea la pantalla o la cantidad de cifras. */
  function ajustarPrecio() {
    const r = $("resultado"), et = document.querySelector(".etiqueta");
    if (r.hidden || !et) return;
    et.style.setProperty("--escala", "1");
    const estilo = getComputedStyle(r);
    const disponible = r.clientWidth - parseFloat(estilo.paddingLeft) - parseFloat(estilo.paddingRight);
    const ancho = et.getBoundingClientRect().width;
    if (ancho > disponible && disponible > 0) {
      et.style.setProperty("--escala", String(Math.max(0.35, (disponible / ancho) * 0.97)));
    }
  }
  window.addEventListener("resize", ajustarPrecio);

  function ocultar() {
    $("espera").hidden = true;
    $("resultado").hidden = true;
    visibilidadPanel();
  }

  window.Pantalla = { PREDETERMINADA: PREDETERMINADA, ESTILOS: ESTILOS, normalizar: normalizar,
                      aplicar: aplicar, espera: espera, producto: producto, ocultar: ocultar,
                      contraste: contraste, legible: legible };
})();
