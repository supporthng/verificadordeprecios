/* Verificador de precios sin internet.
   - Guarda una copia del catálogo en el equipo y consulta SIEMPRE esa copia (instantáneo).
   - Cuando hay internet revisa estado.json cada 5 minutos y descarga el catálogo SOLO si cambió.
   - Anota cada consulta y la sube al Registro de consultas cuando vuelve la conexión.
   - Salir o configurar pide la clave de salida (se comprueba en el equipo, sin internet). */
(function () {
  "use strict";
  const APP_VERSION = "1.0.0";
  const FORMATO = 1;                       // formato de archivos que entiende esta app
  const REVISAR_CADA = 5 * 60 * 1000;      // revisar si hay precios nuevos
  const SEG_ENCONTRADO = 10, SEG_NO_ENCONTRADO = 7;
  const MAX_REGISTRO = 20000, LOTE_REGISTRO = 200, DIAS_REGISTRO = 55;
  const INTENTOS_CLAVE = 5, BLOQUEO_CLAVE = 60 * 1000;
  const RUTA_ESTADO = "/storage/v1/object/public/equipos/estado.json";

  const $ = function (id) { return document.getElementById(id); };
  const lector = $("lector");

  let origen = null;          // URL de estado.json
  let estado = null;          // estado.json guardado en el equipo
  let productos = new Map();  // código -> [código, nombre, precio]
  let revisando = false, ultimaRevisionOk = 0, ultimoError = "";
  let temporizador = null, recargarAlVolver = false;
  const imagenes = { logo: null, qr: null };   // URLs locales (blob:)

  /* ------------------------------------------------------------ utilidades */
  function conTiempo(url, opciones, ms) {
    const control = new AbortController();
    const t = setTimeout(function () { control.abort(); }, ms);
    return fetch(url, Object.assign({}, opciones, { signal: control.signal }))
      .finally(function () { clearTimeout(t); });
  }
  function base() { return origen.slice(0, origen.length - "estado.json".length); }
  function fecha(valor) {
    if (!valor) return "—";
    const d = new Date(valor);
    if (isNaN(d)) return "—";
    return d.toLocaleString("es-DO", { day: "2-digit", month: "2-digit", year: "numeric",
                                       hour: "numeric", minute: "2-digit" });
  }
  const formatoPrecio = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  function local(clave, valor) {
    try {
      if (valor === undefined) return localStorage.getItem(clave);
      if (valor === null) localStorage.removeItem(clave); else localStorage.setItem(clave, valor);
    } catch (e) { return null; }
  }
  function dialogoAbierto() { return $("dlg-clave").open || $("dlg-menu").open; }

  /* Solo se aceptan enlaces de un estado.json publicado por la app en un Supabase (https). */
  function validarOrigen(texto) {
    try {
      let u = new URL(String(texto || "").trim());
      const interno = u.searchParams.get("estado");
      if (interno) u = new URL(interno);         // pegaron el enlace de instalación completo
      if (u.protocol !== "https:" || !u.pathname.endsWith(RUTA_ESTADO)) return null;
      return u.origin + u.pathname;
    } catch (e) { return null; }
  }

  /* ------------------------------------------------------------ pantallas */
  function mostrarAviso(icono, titulo, texto, conFormulario) {
    $("aviso-icono").textContent = icono;
    $("aviso-titulo").textContent = titulo;
    $("aviso-texto").textContent = texto;
    $("form-vincular").hidden = !conFormulario;
    $("aviso").hidden = false;
    $("espera").hidden = true;
    $("resultado").hidden = true;
    $("boton-salida").hidden = conFormulario;
  }

  function mostrarEspera(noEncontrado, codigo) {
    $("aviso").hidden = true;
    $("resultado").hidden = true;
    $("espera").hidden = false;
    $("boton-salida").hidden = false;
    $("tarjeta-codigo").classList.toggle("barcode-not-found", !!noEncontrado);
    $("titulo").textContent = noEncontrado ? "PRODUCTO NO ENCONTRADO" : "ESCANEA TU CÓDIGO AQUÍ";
    $("titulo").classList.toggle("no-encontrado", !!noEncontrado);
    const pista = $("pista");
    pista.classList.toggle("no-encontrado", !!noEncontrado);
    pista.textContent = "";
    if (noEncontrado) {
      pista.append("Código consultado: ");
      const b = document.createElement("strong");
      b.textContent = codigo;
      pista.append(b);
    } else {
      pista.textContent = "El precio se mostrará automáticamente";
    }
    if (!noEncontrado && recargarAlVolver) location.reload();   // app nueva instalada
  }

  function mostrarProducto(p, codigo) {
    $("nombre").textContent = p[1];
    $("codigo").textContent = codigo;
    $("precio").textContent = "RD$ " + formatoPrecio.format(Number(p[2]) || 0);
    $("aviso").hidden = true;
    $("espera").hidden = true;
    $("resultado").hidden = false;
  }

  function aplicarApariencia() {
    const a = (estado && estado.apariencia) || { mostrar_logo: true, mostrar_qr: true, mostrar_cuadro: false };
    $("logo").hidden = !(a.mostrar_logo && imagenes.logo);
    if (imagenes.logo) $("logo").src = imagenes.logo;
    $("qr").hidden = !(a.mostrar_qr && imagenes.qr);
    if (imagenes.qr) $("qr-img").src = imagenes.qr;
    lector.classList.toggle("oculto", !a.mostrar_cuadro);
  }

  function ponerImagen(clave, blob) {
    if (imagenes[clave]) URL.revokeObjectURL(imagenes[clave]);
    imagenes[clave] = blob ? URL.createObjectURL(blob) : null;
  }

  function indicador() {
    const el = $("estado-red");
    if (!estado) { el.textContent = ""; el.hidden = true; return; }
    el.hidden = false;
    const reciente = Date.now() - ultimaRevisionOk < 2 * REVISAR_CADA + 60000;
    el.style.setProperty("--punto", reciente ? "#16a34a" : "#94a3b8");
    el.textContent = reciente ? "Precios al día" : "Sin conexión · precios del " + fecha(estado.publicado).split(",")[0];
  }

  /* ------------------------------------------------------------ consulta */
  function buscar(texto) {
    const codigo = String(texto || "").trim();
    if (!codigo || codigo.length > 64 || !productos.size) return;
    let hallado = null;
    const formas = Codigos.variantes(codigo);
    for (let i = 0; i < formas.length && !hallado; i++) hallado = productos.get(formas[i]) || null;
    clearTimeout(temporizador);
    if (hallado) {
      mostrarProducto(hallado, codigo);
      temporizador = setTimeout(function () { mostrarEspera(false); }, SEG_ENCONTRADO * 1000);
    } else {
      mostrarEspera(true, codigo);
      temporizador = setTimeout(function () { mostrarEspera(false); }, SEG_NO_ENCONTRADO * 1000);
    }
    anotar(codigo, hallado);
  }

  lector.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      const valor = lector.value;
      lector.value = "";
      buscar(valor);
    }
  });

  /* El cursor SIEMPRE en el cuadro del escáner (salvo con un diálogo abierto). */
  function enfocar() {
    if (dialogoAbierto() || !$("form-vincular").hidden) return;
    if (document.activeElement !== lector) {
      try { lector.focus({ preventScroll: true }); } catch (e) { lector.focus(); }
    }
  }
  setInterval(enfocar, 700);
  lector.addEventListener("blur", function () { setTimeout(enfocar, 30); });
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) { enfocar(); mantenerEncendida(); revisar(false); }
  });
  /* Si una tecla llega fuera del cuadro, se redirige a él sin perderla. */
  document.addEventListener("keydown", function (e) {
    if (dialogoAbierto() || e.target === lector || !$("form-vincular").hidden) return;
    if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); const v = lector.value; lector.value = ""; buscar(v); }
    else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); lector.value += e.key; }
    enfocar();
  }, true);
  document.addEventListener("pointerdown", function () { setTimeout(enfocar, 50); });

  /* ------------------------------------------------------------ registro */
  function anotar(codigo, p) {
    BD.anotar({
      created_at: new Date().toISOString(), barcode: codigo.slice(0, 64), found: !!p,
      product_name: p ? String(p[1]).slice(0, 200) : null,
      price: p ? Math.round(Number(p[2]) * 100) / 100 : null,
      source: "local", channel: "offline-verificador",
    }).then(function () { return BD.recortar(MAX_REGISTRO); })
      .catch(function () { /* el registro nunca debe afectar la consulta */ });
    clearTimeout(anotar.envio);
    anotar.envio = setTimeout(subirRegistro, 5000);
  }

  let subiendo = false;
  async function subirRegistro() {
    const destino = estado && estado.registro;
    if (subiendo || !destino || !destino.url || !destino.clave) return;
    subiendo = true;
    try {
      for (let vuelta = 0; vuelta < 50; vuelta++) {
        const lote = await BD.pendientes(LOTE_REGISTRO);
        if (!lote.length) break;
        const limite = Date.now() - DIAS_REGISTRO * 864e5;
        const viejas = lote.filter(function (x) { return Date.parse(x.fila.created_at) < limite; });
        const filas = lote.filter(function (x) { return Date.parse(x.fila.created_at) >= limite; });
        if (filas.length) {
          const cabeceras = { "apikey": destino.clave, "Content-Type": "application/json", "Prefer": "return=minimal" };
          if (String(destino.clave).indexOf("eyJ") === 0) cabeceras["Authorization"] = "Bearer " + destino.clave;
          const r = await conTiempo(destino.url + "/rest/v1/price_lookup_log",
            { method: "POST", headers: cabeceras, body: JSON.stringify(filas.map(function (x) { return x.fila; })) }, 20000);
          if (!r.ok) break;   // sin la migración 004 o sin red: se reintenta más tarde
        }
        await BD.quitar(lote.map(function (x) { return x.id; }));
      }
    } catch (e) { /* sin internet: queda pendiente */ }
    finally { subiendo = false; }
  }

  /* ------------------------------------------------------------ sincronización */
  async function descargarImagen(ruta) {
    const r = await conTiempo(base() + ruta, {}, 30000);
    if (!r.ok) throw new Error("imagen HTTP " + r.status);
    return r.blob();
  }

  async function revisar(mostrarProgreso) {
    if (revisando || !origen) return;
    revisando = true;
    try {
      const r = await conTiempo(origen + "?t=" + Date.now(), { cache: "no-store" }, 12000);
      if (!r.ok) throw new Error(r.status === 400 || r.status === 404
        ? "Todavía no se publicó nada para los equipos." : "HTTP " + r.status);
      const nuevo = await r.json();
      if (!nuevo || !nuevo.version || !nuevo.catalogo) throw new Error("Respuesta inválida.");
      if ((nuevo.formato || 1) > FORMATO) throw new Error("La app del equipo es antigua: recárgala con internet.");
      const cambios = { estado: nuevo, revisado: Date.now() };
      let nuevoCatalogo = null;
      if (!estado || estado.version !== nuevo.version || !productos.size) {
        if (mostrarProgreso) mostrarAviso("⬇️", "Descargando precios…",
          (nuevo.productos || 0).toLocaleString("es-DO") + " productos. Solo tarda la primera vez.", false);
        const rc = await conTiempo(base() + nuevo.catalogo, {}, 180000);
        if (!rc.ok) throw new Error("catálogo HTTP " + rc.status);
        const c = await rc.json();
        if (!c || c.version !== nuevo.version || !Array.isArray(c.productos)) throw new Error("Catálogo incompleto.");
        nuevoCatalogo = c.productos;
        cambios.catalogo = nuevoCatalogo;
      }
      const nuevasImagenes = {};
      for (const clave of ["logo", "qr"]) {
        if (!estado || estado[clave] !== nuevo[clave]) {
          nuevasImagenes[clave] = nuevo[clave] ? await descargarImagen(nuevo[clave]) : null;
          cambios["img_" + clave] = nuevasImagenes[clave];
        }
      }
      await BD.guardar(cambios);           // todo junto: nunca queda a medias
      estado = nuevo;
      if (nuevoCatalogo) productos = new Map(nuevoCatalogo.map(function (p) { return [String(p[0]), p]; }));
      Object.keys(nuevasImagenes).forEach(function (k) { ponerImagen(k, nuevasImagenes[k]); });
      ultimaRevisionOk = Date.now();
      ultimoError = "";
      aplicarApariencia();
      if (!$("aviso").hidden) mostrarEspera(false);
      subirRegistro();
    } catch (e) {
      ultimoError = e && e.name === "AbortError" ? "Sin respuesta (¿hay internet?)." : String(e && e.message || e);
      if (!productos.size) {
        mostrarAviso("📶", "Hace falta internet una vez",
          "Conecta el equipo a internet para descargar los precios. Después funciona sin conexión. (" + ultimoError + ")", false);
      }
    } finally {
      revisando = false;
      indicador();
    }
  }

  /* ------------------------------------------------------------ clave y menú */
  function hexABytes(h) { return new Uint8Array(h.match(/../g).map(function (x) { return parseInt(x, 16); })); }
  async function claveCorrecta(clave, v) {
    const llave = await crypto.subtle.importKey("raw", new TextEncoder().encode(clave), "PBKDF2", false, ["deriveBits"]);
    const bits = await crypto.subtle.deriveBits(
      { name: "PBKDF2", hash: "SHA-256", salt: hexABytes(v.sal), iterations: Number(v.iteraciones) }, llave, 256);
    const hex = Array.from(new Uint8Array(bits)).map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
    let distinto = hex.length ^ v.hash.length;
    for (let i = 0; i < hex.length; i++) distinto |= hex.charCodeAt(i) ^ v.hash.charCodeAt(i);
    return distinto === 0;
  }

  let cierreMenu = null;
  function abrirMenu() {
    clearTimeout(temporizador);
    rellenarMenu();
    $("menu-mensaje").textContent = "";
    $("m-desvincular").dataset.confirmar = "";
    $("m-desvincular").textContent = "🔗 Desvincular este equipo";
    $("dlg-menu").showModal();
    reiniciarCierreMenu();
  }
  function reiniciarCierreMenu() {
    clearTimeout(cierreMenu);
    cierreMenu = setTimeout(cerrarMenu, 2 * 60 * 1000);   // nunca queda abierto solo
  }
  function cerrarMenu() {
    clearTimeout(cierreMenu);
    if ($("dlg-menu").open) $("dlg-menu").close();
    if (productos.size) mostrarEspera(false);
    enfocar();
  }
  $("dlg-menu").addEventListener("pointerdown", reiniciarCierreMenu);
  $("dlg-menu").addEventListener("cancel", function (e) { e.preventDefault(); cerrarMenu(); });

  async function rellenarMenu() {
    const pendientesN = await BD.contar().catch(function () { return "—"; });
    const filas = [
      ["Inventario", estado ? estado.inventario : "—"],
      ["Productos", productos.size.toLocaleString("es-DO")],
      ["Precios publicados", estado ? fecha(estado.publicado) : "—"],
      ["Última revisión", ultimaRevisionOk ? fecha(ultimaRevisionOk) : "sin conexión desde que se abrió"],
      ["Consultas por subir", String(pendientesN)],
      ["App", "versión " + APP_VERSION],
    ];
    if (ultimoError) filas.push(["Último aviso", ultimoError]);
    const dl = $("menu-estado");
    dl.textContent = "";
    filas.forEach(function (f) {
      const dt = document.createElement("dt"), dd = document.createElement("dd");
      dt.textContent = f[0]; dd.textContent = f[1];
      dl.append(dt, dd);
    });
    const sinClave = !(estado && estado.salida);
    $("menu-aviso").hidden = !sinClave;
    $("menu-aviso").textContent = "Todavía no hay clave de salida: defínela en la app en línea, en Equipos sin internet.";
    const enLinea = estado && estado.app_en_linea;
    $("m-en-linea").hidden = !enLinea;
    if (enLinea) $("m-en-linea").href = enLinea;
  }

  $("boton-salida").addEventListener("click", function () {
    if (!(estado && estado.salida)) { abrirMenu(); return; }
    $("clave").value = "";
    $("clave-error").textContent = "";
    $("dlg-clave").showModal();
    setTimeout(function () { $("clave").focus(); }, 50);
  });
  $("clave-cancelar").addEventListener("click", function () { $("dlg-clave").close(); enfocar(); });
  $("form-clave").addEventListener("submit", async function (e) {
    e.preventDefault();
    const bloqueo = Number(local("bloqueo_clave") || 0);
    if (Date.now() < bloqueo) {
      $("clave-error").textContent = "Demasiados intentos. Espera " + Math.ceil((bloqueo - Date.now()) / 1000) + " segundos.";
      return;
    }
    $("clave-entrar").disabled = true;
    $("clave-error").textContent = "Verificando…";
    let ok = false;
    try { ok = await claveCorrecta($("clave").value, estado.salida); } catch (err) { ok = false; }
    $("clave-entrar").disabled = false;
    if (ok) {
      local("intentos_clave", null);
      $("dlg-clave").close();
      abrirMenu();
    } else {
      const n = Number(local("intentos_clave") || 0) + 1;
      if (n >= INTENTOS_CLAVE) { local("bloqueo_clave", String(Date.now() + BLOQUEO_CLAVE)); local("intentos_clave", null); }
      else local("intentos_clave", String(n));
      $("clave-error").textContent = "Clave incorrecta.";
      $("clave").value = "";
    }
  });

  $("m-volver").addEventListener("click", cerrarMenu);
  $("m-actualizar").addEventListener("click", async function () {
    $("menu-mensaje").textContent = "Buscando…";
    const antes = estado && estado.version;
    await revisar(false);
    $("menu-mensaje").textContent = ultimoError ? "No se pudo: " + ultimoError
      : (estado.version !== antes ? "✅ Precios nuevos descargados." : "✅ Ya tienes los precios más recientes.");
    rellenarMenu();
  });
  $("m-completa").addEventListener("click", function () {
    const el = document.documentElement;
    const pedir = el.requestFullscreen || el.webkitRequestFullscreen;
    if (pedir) Promise.resolve(pedir.call(el)).catch(function () {});
  });
  $("m-desvincular").addEventListener("click", async function () {
    const b = $("m-desvincular");
    if (!b.dataset.confirmar) {
      b.dataset.confirmar = "1";
      b.textContent = "⚠️ Toca otra vez para borrar los precios de este equipo";
      return;
    }
    await BD.borrarTodo().catch(function () {});
    local("origen", null);
    location.replace(location.pathname);
  });

  /* ------------------------------------------------------------ vincular */
  $("form-vincular").addEventListener("submit", function (e) {
    e.preventDefault();
    const o = validarOrigen($("enlace").value);
    if (!o) { $("enlace-error").textContent = "Ese no es el enlace de instalación. Cópialo desde Equipos sin internet."; return; }
    vincular(o);
  });
  async function vincular(o) {
    origen = o;
    local("origen", o);
    await BD.guardar({ origen: o }).catch(function () {});
    mostrarAviso("⏳", "Conectando…", "Buscando los precios publicados.", false);
    revisar(true);
  }

  /* ------------------------------------------------------------ equipo */
  let bloqueoPantalla = null;
  async function mantenerEncendida() {
    try {
      if ("wakeLock" in navigator && !bloqueoPantalla && !document.hidden) {
        bloqueoPantalla = await navigator.wakeLock.request("screen");
        bloqueoPantalla.addEventListener("release", function () { bloqueoPantalla = null; });
      }
    } catch (e) { /* no disponible: Fully Kiosk ya mantiene la pantalla */ }
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").then(function (reg) {
      setInterval(function () { reg.update().catch(function () {}); }, 60 * 60 * 1000);
    }).catch(function () {});
    let primera = !navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener("controllerchange", function () {
      if (primera) { primera = false; return; }
      recargarAlVolver = true;   // se aplica al volver a la pantalla de espera
      if (!$("espera").hidden && !dialogoAbierto()) location.reload();
    });
  }
  window.addEventListener("online", function () { revisar(false); });

  /* ------------------------------------------------------------ inicio */
  async function iniciar() {
    if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(function () {});
    mantenerEncendida();
    const params = new URLSearchParams(location.search);
    const desdeEnlace = validarOrigen(params.get("estado") ? location.href : "");
    let guardado = {};
    try { guardado = await BD.leer(["origen", "estado", "catalogo", "img_logo", "img_qr", "revisado"]); }
    catch (e) { guardado = {}; }
    origen = desdeEnlace || guardado.origen || validarOrigen(local("origen"));
    if (desdeEnlace) {
      if (desdeEnlace !== guardado.origen) await BD.guardar({ origen: desdeEnlace }).catch(function () {});
      local("origen", desdeEnlace);
      history.replaceState(null, "", location.pathname);   // dirección limpia para instalar
    }
    if (!origen) {
      mostrarAviso("🔗", "Vincula este equipo",
        "Abre en este equipo el enlace de instalación que aparece en la app en línea, en Equipos sin internet, o pégalo aquí.", true);
      return;
    }
    if (guardado.estado && Array.isArray(guardado.catalogo)) {
      estado = guardado.estado;
      ultimaRevisionOk = Number(guardado.revisado) || 0;
      productos = new Map(guardado.catalogo.map(function (p) { return [String(p[0]), p]; }));
      ponerImagen("logo", guardado.img_logo || null);
      ponerImagen("qr", guardado.img_qr || null);
      aplicarApariencia();
      mostrarEspera(false);
      indicador();
      revisar(false);
    } else {
      mostrarAviso("⏳", "Conectando…", "Buscando los precios publicados.", false);
      await revisar(true);
    }
    setInterval(function () { revisar(false); }, REVISAR_CADA + Math.floor(Math.random() * 30000));
    setInterval(indicador, 60000);
    enfocar();
  }

  /* Para pruebas automáticas. */
  window.__verificador = { buscar: buscar, revisar: revisar, estado: function () { return estado; },
                           cantidad: function () { return productos.size; }, subirRegistro: subirRegistro };
  iniciar();
})();
