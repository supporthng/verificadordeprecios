/* Verificador de precios sin internet.
   - Guarda una copia del catálogo en el equipo y consulta SIEMPRE esa copia (instantáneo).
   - Cuando hay internet revisa estado.json cada minuto y descarga el catálogo SOLO si cambió.
   - Anota cada consulta y la sube al Registro de consultas cuando vuelve la conexión.
   - Salir o configurar pide la clave de salida (se comprueba en el equipo, sin internet). */
(function () {
  "use strict";
  const APP_VERSION = "1.8.0";
  const FORMATO = 1;                       // formato de archivos que entiende esta app
  const REVISAR_CADA = 60 * 1000;          // con internet: revisar cada minuto (archivo de 1 KB)
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
  let fotosMapa = {}, fotosRef = null, sincronizandoFotos = false;   // fotos de productos
  let fotoActual = null, consultaN = 0;

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
    // Siempre en hora de República Dominicana, aunque el equipo tenga otra zona horaria
    // (los 2connect vienen de fábrica con la de China: 12 horas de diferencia).
    try {
      return d.toLocaleString("es-DO", { timeZone: "America/Santo_Domingo", day: "2-digit", month: "2-digit",
                                         year: "numeric", hour: "numeric", minute: "2-digit" });
    } catch (e) {
      return d.toLocaleString("es-DO", { day: "2-digit", month: "2-digit", year: "numeric",
                                         hour: "numeric", minute: "2-digit" });
    }
  }
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
    Pantalla.ocultar();
    $("boton-salida").hidden = conFormulario;
  }

  /* El dibujo (estilo, textos, logo, nombre, QR) lo hace pantalla.js. */
  function mostrarEspera(noEncontrado, codigo) {
    $("aviso").hidden = true;
    $("boton-salida").hidden = false;
    Pantalla.espera(noEncontrado, codigo);
    if (!noEncontrado && recargarAlVolver) location.reload();   // app nueva instalada
  }

  function mostrarProducto(p, codigo) {
    $("aviso").hidden = true;
    Pantalla.producto(p, codigo, SEG_ENCONTRADO, null);
    // La foto llega un instante después (se lee del equipo; con internet, si aún no se descargó, de la red).
    const n = ++consultaN;
    fotoPara(p, codigo).then(function (direccion) {
      if (n === consultaN && !$("resultado").hidden) Pantalla.foto(direccion);
    }).catch(function () {});
  }

  /* ------------------------------------------------------------ fotos de productos */
  function archivoFoto(p, codigo) {
    if (fotosMapa[String(p[0])]) return fotosMapa[String(p[0])];
    const formas = Codigos.variantes(codigo);
    for (let i = 0; i < formas.length; i++) if (fotosMapa[formas[i]]) return fotosMapa[formas[i]];
    return null;
  }
  async function fotoPara(p, codigo) {
    const archivo = archivoFoto(p, codigo);
    if (!archivo) return null;
    const blob = await BD.fotoLeer(archivo).catch(function () { return null; });
    if (fotoActual) { URL.revokeObjectURL(fotoActual); fotoActual = null; }
    if (blob) { fotoActual = URL.createObjectURL(blob); return fotoActual; }
    return navigator.onLine && origen ? base() + archivo : null;
  }
  /* Descarga en segundo plano las fotos nuevas y borra las que ya no se usan. */
  async function sincronizarFotos() {
    if (sincronizandoFotos || !estado || !estado.fotos || !origen) return;
    sincronizandoFotos = true;
    try {
      if (estado.fotos !== fotosRef) {
        const r = await conTiempo(base() + estado.fotos, { cache: "no-store" }, 30000);
        if (!r.ok) throw new Error("fotos HTTP " + r.status);
        const mapa = await r.json();
        if (!mapa || typeof mapa !== "object") throw new Error("fotos inválidas");
        await BD.guardar({ fotos_mapa: mapa, fotos_ref: estado.fotos });
        fotosMapa = mapa; fotosRef = estado.fotos;
      }
      const quiero = new Set(Object.values(fotosMapa));
      const tengo = new Set(await BD.fotoClaves());
      for (const archivo of quiero) {
        if (tengo.has(archivo)) continue;
        const r = await conTiempo(base() + archivo, {}, 30000);
        if (!r.ok) continue;
        await BD.fotoGuardar(archivo, await r.blob());
      }
      const sobran = Array.from(tengo).filter(function (a) { return !quiero.has(a); });
      if (sobran.length) await BD.fotoBorrar(sobran);
    } catch (e) {
      /* sin internet o sin espacio: se reintenta en la próxima revisión */
    } finally {
      sincronizandoFotos = false;
    }
  }

  function aplicarApariencia() {
    Pantalla.aplicar(estado && estado.apariencia, imagenes);
  }

  function ponerImagen(clave, blob) {
    if (imagenes[clave]) URL.revokeObjectURL(imagenes[clave]);
    imagenes[clave] = blob ? URL.createObjectURL(blob) : null;
  }

  function indicador() {
    const el = $("estado-red");
    if (!estado) { el.textContent = ""; el.hidden = true; return; }
    el.hidden = false;
    const reciente = Date.now() - ultimaRevisionOk < 5 * 60 * 1000;
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
    if (!document.hidden) { enfocar(); mantenerEncendida(); despertado = true; revisar(false); }
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
      // Reportar YA si llegaron precios nuevos o si acaba de volver la conexión;
      // si no, basta un reporte cada 5 minutos.
      const reconectado = !!ultimoError || !reportadoAlguna;   // volvió internet, o recién abrió
      reportar(!!nuevoCatalogo || reconectado);
      reportadoAlguna = true;
      ultimoError = "";
      aplicarApariencia();
      if (!$("aviso").hidden) mostrarEspera(false);
      subirRegistro();
      sincronizarFotos();
      revisarApp(false, reconectado || despertado);
      revisarMarco();
      despertado = false;
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

  /* ------------------------------------------------------------ estado del equipo */
  let equipo = { id: "", nombre: "" };
  function nuevoId() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return Array.from(crypto.getRandomValues(new Uint8Array(16)))
      .map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
  }
  async function cargarEquipo(guardado) {
    equipo.id = guardado.equipo_id || local("equipo_id") || nuevoId();
    equipo.nombre = guardado.equipo_nombre || local("equipo_nombre") || "";
    local("equipo_id", equipo.id);
    if (!guardado.equipo_id) await BD.guardar({ equipo_id: equipo.id }).catch(function () {});
  }
  function nombreEquipo() { return equipo.nombre || "Verificador " + equipo.id.slice(0, 4).toUpperCase(); }

  /* Avisa a la app en línea que este equipo está encendido y qué precios tiene. */
  let ultimoReporte = 0, reportadoAlguna = false;
  let resultadoReporte = "todavía no se ha intentado";
  async function reportar(ahora) {
    const destino = estado && estado.registro;
    if (!destino || !destino.url || !destino.clave) {
      resultadoReporte = "❌ falta la clave pública de Supabase (SUPABASE_PUBLISHABLE_KEY) en Secrets; luego pulsa Publicar";
      return;
    }
    if (!equipo.id) return;
    if (!ahora && Date.now() - ultimoReporte < 5 * 60 * 1000) return;   // basta cada 5 minutos
    ultimoReporte = Date.now();
    try {
      const cabeceras = { "apikey": destino.clave, "Content-Type": "application/json" };
      if (String(destino.clave).indexOf("eyJ") === 0) cabeceras["Authorization"] = "Bearer " + destino.clave;
      const pendientesN = await BD.contar().catch(function () { return 0; });
      const r = await conTiempo(destino.url + "/rest/v1/rpc/equipo_reporta", { method: "POST", headers: cabeceras,
        body: JSON.stringify({ p_id: equipo.id, p_nombre: nombreEquipo(), p_tipo: "verificador",
          p_app: APP_VERSION, p_precios: estado.version, p_productos: productos.size,
          p_pendientes: pendientesN,
          p_navegador: ((nativo() && nativo().tipo === "windows" ? "ConsultaPreciosApp (Windows) " : "")
                        + navigator.userAgent).slice(0, 160) }) }, 15000);
      if (r.ok) {
        resultadoReporte = "✅ " + fecha(Date.now());
      } else {
        const texto = (await r.text().catch(function () { return ""; })).slice(0, 160);
        resultadoReporte = "❌ error " + r.status + (r.status === 404 ? " (falta ejecutar MIGRACION_005)" :
          (r.status === 401 || r.status === 403) ? " (clave o permiso)" : "") + (texto ? ": " + texto : "");
      }
    } catch (e) {
      resultadoReporte = "⏳ sin conexión, se reintenta";   // no afecta al verificador
    }
  }

  $("form-nombre").addEventListener("submit", async function (e) {
    e.preventDefault();
    equipo.nombre = $("nombre-equipo").value.trim().slice(0, 40);
    local("equipo_nombre", equipo.nombre);
    await BD.guardar({ equipo_nombre: equipo.nombre || null }).catch(function () {});
    $("menu-mensaje").textContent = "✅ Nombre guardado: " + nombreEquipo();
    reportar(true);
  });

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
    $("nombre-equipo").value = equipo.nombre;
    $("dlg-menu").showModal();
    reportar(true).then(rellenarMenu);
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
      ["Equipo", nombreEquipo()],
      ["Reporte al panel", resultadoReporte],
      ["App", "versión " + APP_VERSION + (versionNueva ? " (instalando la " + versionNueva + "…)" : "")
              + (nativo() ? " · app " + (nativo().tipo === "android" ? "Android" : "Windows")
                 + (nativo().version() ? " " + nativo().version() : "")
                 + (nativo().bloqueoTotal() ? " (bloqueo total)" : "")
                 + (marcoNuevo ? " · hay una versión nueva: " + marcoNuevo.version : "") : "")],
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
    const app = nativo();
    const enLinea = estado && estado.app_en_linea;
    // Dentro de las apps, abrir la web en línea sacaría al equipo del verificador.
    $("m-en-linea").hidden = !enLinea || !!app;
    if (enLinea) $("m-en-linea").href = enLinea;
    $("m-completa").hidden = !!app;               // las apps ya están a pantalla completa
    $("m-fijar").hidden = !(app && app.tipo === "android" && !app.bloqueoTotal());
    $("m-inicio").hidden = !(app && app.tipo === "android");
    $("m-marco").hidden = !(app && marcoNuevo);
    if (marcoNuevo) $("m-marco").textContent = "⬇️ Actualizar la app a la versión " + marcoNuevo.version;
    $("m-cerrar").textContent = app && app.tipo === "android" ? "⏻ Salir del verificador (abre Ajustes)"
                                                              : "⏻ Cerrar aplicación";
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
    if (!ok) {
      // ¿Cambiaron la clave en la app en línea? Con internet, traer la vigente y comprobar otra vez.
      const antes = JSON.stringify(estado.salida);
      await revisar(false);
      if (estado.salida && JSON.stringify(estado.salida) !== antes) {
        try { ok = await claveCorrecta($("clave").value, estado.salida); } catch (err) { ok = false; }
      }
    }
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

  /* ------------------------------------------------------------ actualizar la app
     version.txt (en GitHub Pages) dice cuál es la versión vigente. Si el equipo tiene otra,
     se pide la nueva; si a los 2 minutos sigue sin instalarse, se reinstala desde cero
     (los precios guardados NO se borran: están en IndexedDB, no en la caché de la app). */
  let versionNueva = "", nuevaDesde = 0, despertado = false;
  async function reinstalarApp() {
    try {
      const regs = navigator.serviceWorker ? await navigator.serviceWorker.getRegistrations() : [];
      for (const r of regs) await r.unregister();
      if (self.caches) for (const k of await caches.keys()) await caches.delete(k);
    } catch (e) { /* se recarga igual */ }
    location.reload();
  }
  async function revisarApp(ahora, rapido) {
    try {
      const r = await conTiempo("version.txt?t=" + Date.now(), { cache: "no-store" }, 8000);
      if (!r.ok) return false;
      const v = (await r.text()).trim();
      if (!/^\d+\.\d+\.\d+$/.test(v) || v === APP_VERSION) { versionNueva = ""; nuevaDesde = 0; return false; }
      versionNueva = v;
      if (!nuevaDesde) nuevaDesde = Date.now();
      const reg = navigator.serviceWorker && await navigator.serviceWorker.getRegistration();
      if (reg) await reg.update().catch(function () {});
      const libre = $("resultado").hidden && !dialogoAbierto();
      if (ahora) { await reinstalarApp(); return true; }
      // Al volver internet / despertar: dar 15 s a la actualización normal y, si no se aplicó,
      // reinstalar (sin interrumpir a un cliente que mira un precio). En los demás casos, 2 min.
      const espera = rapido ? 15000 : 2 * 60 * 1000;
      if (rapido) {
        setTimeout(function () { revisarApp(false, false).then(function () {
          if (versionNueva && $("resultado").hidden && !dialogoAbierto()) reinstalarApp();
        }); }, espera);
      } else if (libre && Date.now() - nuevaDesde > espera) {
        await reinstalarApp();
      }
      return true;
    } catch (e) { return false; }
  }

  /* ------------------------------------------------------------ apps Android / Windows
     Dentro de la app "Consulta de Precios" para Android (window.AndroidKiosco) o Windows
     (window.pywebview.api) se usa su puente para salir del quiosco. */
  function nativo() {
    if (window.AndroidKiosco && typeof window.AndroidKiosco.salir === "function") {
      const a = window.AndroidKiosco;
      return { tipo: "android", salir: function () { a.salir(); },
               bloqueoTotal: function () { try { return !!a.bloqueoTotal(); } catch (e) { return false; } },
               version: function () { try { return a.version(); } catch (e) { return ""; } },
               fijar: function () { a.fijar(); }, cambiarInicio: function () { a.cambiarInicio(); },
               actualizar: typeof a.actualizar === "function" ? function (url) { a.actualizar(url); } : null };
    }
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.salir === "function") {
      const w = window.pywebview.api;
      return { tipo: "windows", salir: function () { w.salir(); }, bloqueoTotal: function () { return false; },
               version: function () { return versionMarcoWindows; },
               actualizar: function (url) { w.actualizar(url); } };
    }
    return null;
  }
  // En Windows las llamadas al puente son asíncronas: la versión se pide una vez al abrir.
  let versionMarcoWindows = "";
  window.addEventListener("pywebviewready", function () {
    try { window.pywebview.api.version().then(function (v) { versionMarcoWindows = String(v || ""); revisarMarco(); }); }
    catch (e) { /* sin puente */ }
  });

  /* ------------------------------------------------------------ actualizar el "marco" de la app
     docs/apps.json dice la versión vigente del APK y del instalador de Windows. */
  let marcoNuevo = null;   // {version, url} si hay una versión nueva del marco
  function versionMayor(a, b) {
    const x = String(a || "0").split(".").map(Number), y = String(b || "0").split(".").map(Number);
    for (let i = 0; i < 3; i++) { if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); }
    return false;
  }
  async function revisarMarco() {
    const app = nativo();
    if (!app || !app.actualizar || !app.version()) { marcoNuevo = null; return; }
    try {
      const r = await conTiempo("apps.json?t=" + Date.now(), { cache: "no-store" }, 8000);
      if (!r.ok) return;
      const info = (await r.json())[app.tipo];
      marcoNuevo = info && info.url && versionMayor(info.version, app.version()) ? info : null;
    } catch (e) { /* sin internet: se revisa después */ }
  }
  window.__actualizacionApp = function (estado) {
    const textos = { descargando: "⬇️ Descargando la versión nueva de la app…",
                     instalando: "⚙️ Instalando… (en Android, toca «Instalar» si lo pide)",
                     error: "No se pudo actualizar la app. Revisa la conexión e inténtalo de nuevo." };
    $("menu-mensaje").textContent = textos[estado] || "";
  };

  /* ------------------------------------------------------------ cerrar la app */
  $("m-cerrar").addEventListener("click", function () {
    cerrarMenu();
    const app = nativo();
    if (app) { app.salir(); return; }   // Android: abre Ajustes · Windows: cierra la app
    try {
      // Fully Kiosk (con "Enable JavaScript Interface" activado) expone fully.exit().
      if (window.fully && typeof window.fully.exit === "function") { window.fully.exit(); return; }
    } catch (e) { /* sigue con el cierre normal */ }
    window.close();   // funciona en la app instalada (pantalla de inicio)
    setTimeout(function () {
      if (document.visibilityState === "visible") {
        abrirMenu();
        $("menu-mensaje").textContent = "Este navegador no deja cerrar la página. Usa el botón de inicio " +
          "o el gesto de salida de Fully. (En Fully: activa Advanced Web Settings > Enable JavaScript Interface.)";
      }
    }, 600);
  });

  $("m-marco").addEventListener("click", function () {
    const a = nativo();
    if (!a || !a.actualizar || !marcoNuevo) return;
    a.actualizar(marcoNuevo.url);
    window.__actualizacionApp("descargando");
  });
  $("m-fijar").addEventListener("click", function () { cerrarMenu(); const a = nativo(); if (a && a.fijar) a.fijar(); });
  $("m-inicio").addEventListener("click", function () { cerrarMenu(); const a = nativo(); if (a && a.cambiarInicio) a.cambiarInicio(); });
  $("m-volver").addEventListener("click", cerrarMenu);
  $("m-actualizar").addEventListener("click", async function () {
    $("menu-mensaje").textContent = "Buscando…";
    if (await revisarApp(true)) return;    // había app nueva: se reinstala y recarga
    const antes = estado && estado.version;
    await revisar(false);
    $("menu-mensaje").textContent = ultimoError ? "No se pudo: " + ultimoError
      : (estado.version !== antes ? "✅ Precios nuevos descargados." : "✅ Ya tienes los precios más recientes.");
    rellenarMenu();
  });
  $("m-completa").addEventListener("click", function () {
    // Cerrar el menú ANTES: si queda abierto, la pantalla completa lo tapa y bloquea todo.
    cerrarMenu();
    const el = document.documentElement;
    const pedir = el.requestFullscreen || el.webkitRequestFullscreen;
    if (pedir) Promise.resolve(pedir.call(el)).catch(function () {}).then(enfocar);
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
    // Sirve el enlace largo, o la dirección corta de la app (usa la dirección incluida en config.js).
    const o = validarOrigen($("enlace").value) || validarOrigen((self.CONFIG_EQUIPOS || {}).estado);
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
      // Recargar ya, salvo que un cliente esté viendo un precio o haya un diálogo abierto.
      if ($("resultado").hidden && !dialogoAbierto()) location.reload();
    });
  }
  // Al volver internet: revisar enseguida y de nuevo a los 5 y 20 s (el Wi-Fi tarda en estar listo).
  window.addEventListener("online", function () {
    [0, 5000, 20000].forEach(function (ms) { setTimeout(function () { revisar(false); }, ms); });
  });

  /* ------------------------------------------------------------ inicio */
  async function iniciar() {
    if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(function () {});
    mantenerEncendida();
    const params = new URLSearchParams(location.search);
    const desdeEnlace = validarOrigen(params.get("estado") ? location.href : "");
    let guardado = {};
    try { guardado = await BD.leer(["origen", "estado", "catalogo", "img_logo", "img_qr", "revisado",
                                    "equipo_id", "equipo_nombre", "fotos_mapa", "fotos_ref"]); }
    catch (e) { guardado = {}; }
    await cargarEquipo(guardado);
    origen = desdeEnlace || guardado.origen || validarOrigen(local("origen")) ||
             validarOrigen((self.CONFIG_EQUIPOS || {}).estado);
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
      fotosMapa = guardado.fotos_mapa || {}; fotosRef = guardado.fotos_ref || null;
      aplicarApariencia();
      mostrarEspera(false);
      indicador();
      revisar(false);
    } else {
      mostrarAviso("⏳", "Conectando…", "Buscando los precios publicados.", false);
      await revisar(true);
    }
    setInterval(function () { revisar(false); }, REVISAR_CADA + Math.floor(Math.random() * 10000));
    setInterval(indicador, 60000);
    enfocar();
  }

  /* Para pruebas automáticas. */
  window.__verificador = { buscar: buscar, revisar: revisar, estado: function () { return estado; },
                           cantidad: function () { return productos.size; }, equipo: function () { return equipo; }, subirRegistro: subirRegistro, revisarApp: revisarApp };
  iniciar();
})();
