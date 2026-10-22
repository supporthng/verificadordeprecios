"""Lectura de códigos con la cámara EN VIVO (sin tomar foto).

El JavaScript corre en la página principal:
- Cuando aparece el recuadro #lector-vivo (y está visible), abre la cámara
  trasera y muestra la imagen limpia (sin zoom ni sombreados), con una línea
  roja de "láser" como guía.
- Lee con el lector de códigos del propio navegador (BarcodeDetector). En
  Android lo trae Chrome; en iPhone se carga una versión compatible basada en
  ZXing-C++ (librería "barcode-detector"). Ambos leen en cualquier orientación
  (horizontal, vertical o inclinado).
- Al detectar un código: pitido + vibración, apaga la cámara y lo escribe en un
  cuadro oculto de Streamlit, igual que un lector de códigos.
- Si el recuadro desaparece (resultado o cambio de pestaña), apaga la cámara.
"""
import streamlit as st

# Versión fija del lector compatible para iPhone (y navegadores sin BarcodeDetector).
LECTOR_COMPATIBLE = "https://cdn.jsdelivr.net/npm/barcode-detector@3.1.3/dist/iife/ponyfill.js"

LECTOR_JS = r"""
(() => {
  if (window.__lectorVivoV6) return;        // instalar una sola vez por ventana
  const estado = { stream: null, video: null, elemento: null, abriendo: false,
                   ultimo: '', ultimoT: 0, abiertoEn: 0 };
  window.__lectorVivoV6 = estado;
  const FORMATOS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39'];

  // ---------- Sonido de lector ("bip") ----------
  // Archivo de audio (<audio>): en iPhone suena aunque esté en modo silencio.
  // Los navegadores exigen un primer toque en la pantalla para permitir sonido.
  function crearBip() {
    const sr = 22050, n = Math.floor(sr * 0.12), buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
    const txt = (o, t) => { for (let k = 0; k < t.length; k++) v.setUint8(o + k, t.charCodeAt(k)); };
    txt(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); txt(8, 'WAVE'); txt(12, 'fmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    txt(36, 'data'); v.setUint32(40, n * 2, true);
    for (let k = 0; k < n; k++) {
      const env = Math.min(1, k / 150, (n - k) / 300);
      const onda = Math.sin(2 * Math.PI * 2700 * k / sr) >= 0 ? 1 : -1;
      v.setInt16(44 + k * 2, Math.round(onda * env * 0.55 * 32767), true);
    }
    return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
  }
  const bip = new Audio(crearBip()); bip.preload = 'auto';
  estado.sonidoListo = false;
  function activarSonido() {
    if (estado.sonidoListo) return;
    bip.muted = true;
    bip.play().then(() => {
      bip.pause(); bip.currentTime = 0; bip.muted = false;
      estado.sonidoListo = true; mostrarSonido();
    }).catch(() => { bip.muted = false; });
  }
  ['pointerdown', 'touchend', 'click', 'keydown'].forEach((ev) =>
    document.addEventListener(ev, activarSonido, { capture: true, passive: true }));
  function pitido() {
    try { bip.currentTime = 0; } catch (_) {}
    bip.play().catch(() => {});
  }
  function mostrarSonido() {
    const s = document.querySelector('#lector-vivo-sonido');
    if (s) s.textContent = estado.sonidoListo ? '' : '🔈 Toca la imagen para activar el sonido';
  }
  function avisar(texto) {
    const a = document.querySelector('#lector-vivo-aviso');
    if (a) a.textContent = texto || '';
  }

  // ---------- Guía de distancia ----------
  const GUIA = [
    '🎯 Pon el código sobre la línea roja',
    '🔍 Acerca un poco el teléfono',
    '↔️ Aleja un poco el teléfono',
    '✋ Mantén el teléfono quieto un momento',
  ];
  setInterval(() => {
    if (!estado.stream || !estado.abiertoEn) return;
    const seg = (Date.now() - estado.abiertoEn) / 1000;
    const reciente = estado.guiaT && Date.now() - estado.guiaT < 700;
    if (reciente && estado.guia === 'enfocando') avisar('🔎 Enfocando… mantén el teléfono quieto');
    else if (reciente && estado.guia === 'acercar') avisar('🔍 Acerca el código: se ve muy pequeño');
    else if (reciente && estado.guia === 'centrar') avisar('🎯 Pon el código sobre la línea roja');
    else avisar(seg < 2.5 ? '📏 Distancia ideal: 15–20 cm del código'
                          : GUIA[Math.floor((seg - 2.5) / 2.2) % GUIA.length]);
    mostrarSonido();
  }, 500);

  // ---------- Lector de códigos ----------
  function cargarScript(src) {
    return new Promise((ok, mal) => {
      const s = document.createElement('script');
      s.src = src; s.async = true; s.onload = ok;
      s.onerror = () => mal(new Error('No se pudo cargar el lector'));
      document.head.appendChild(s);
    });
  }
  async function obtenerDetector() {
    if (estado.detector) return estado.detector;
    // 1) Lector nativo del navegador (Chrome en Android).
    if ('BarcodeDetector' in window) {
      try {
        const soportados = await window.BarcodeDetector.getSupportedFormats();
        const f = FORMATOS.filter((x) => soportados.includes(x));
        if (f.length) return (estado.detector = new window.BarcodeDetector({ formats: f }));
      } catch (_) {}
    }
    // 2) Versión compatible (iPhone y otros): ZXing-C++ en el propio teléfono.
    if (!(window.BarcodeDetectionAPI && window.BarcodeDetectionAPI.BarcodeDetector))
      await cargarScript('__LECTOR_COMPATIBLE__');
    return (estado.detector = new window.BarcodeDetectionAPI.BarcodeDetector({ formats: FORMATOS }));
  }

  // Escribe el código en el cuadro oculto de Streamlit y lo confirma (Enter + salir).
  function enviar(codigo) {
    const input = document.querySelector('.st-key-camara_codigo input');
    if (!input) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    input.focus();
    setter.call(input, codigo);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    for (const tipo of ['keydown', 'keypress', 'keyup'])
      input.dispatchEvent(new KeyboardEvent(tipo, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
    input.blur();
    return true;
  }

  function detener() {
    if (estado.stream) estado.stream.getTracks().forEach((t) => t.stop());
    if (estado.video) { try { estado.video.srcObject = null; estado.video.remove(); } catch (_) {} }
    estado.stream = null; estado.video = null; estado.elemento = null; estado.abiertoEn = 0;
    estado.candidato = null; estado.guiaT = 0;
  }

  function leido(texto) {
    const ahora = Date.now();
    if (texto === estado.ultimo && ahora - estado.ultimoT < 3000) return;  // evitar duplicados
    estado.ultimo = texto; estado.ultimoT = ahora;
    pitido();
    if (navigator.vibrate) navigator.vibrate(80);
    estado.pausaHasta = ahora + 2500;      // no reabrir mientras se muestra el resultado
    detener();
    avisar('✅ Código leído: ' + texto + (estado.formatoLeido ? ' (' + estado.formatoLeido + ')' : '') + ' · consultando…');
    enviar(texto);
  }

  // ---------- Validaciones: solo lecturas seguras ----------
  const CONFIRMACIONES = 3;        // mismo código en 3 imágenes seguidas
  const ESPERA_INICIAL = 1000;     // ms: dejar que la cámara enfoque al abrir
  // Dígito verificador de EAN-13, EAN-8 y UPC-A (detecta lecturas erróneas).
  function digitoValido(valor, formato) {
    if (!['ean_13', 'ean_8', 'upc_a'].includes(formato)) return true;
    if (!/^\d+$/.test(valor) || ![8, 12, 13].includes(valor.length)) return false;
    const d = valor.split('').map(Number), control = d.pop();
    let suma = 0;
    d.reverse().forEach((x, k) => { suma += x * (k % 2 === 0 ? 3 : 1); });
    return (10 - (suma % 10)) % 10 === control;
  }
  // ¿El código está sobre la línea roja (centro de la imagen) y se ve suficientemente grande?
  function revisarPosicion(c, w, h) {
    const b = c.boundingBox;
    if (!b || !b.width) return 'ok';
    const cy = h / 2, cx = b.x + b.width / 2;
    if (Math.max(b.width, b.height) < 0.12 * Math.min(w, h)) return 'acercar';
    const cruzaLaser = b.y <= cy + 0.12 * h && b.y + b.height >= cy - 0.12 * h;
    if (!cruzaLaser || cx < 0.15 * w || cx > 0.85 * w) return 'centrar';
    return 'ok';
  }
  function guiar(tipo) { estado.guia = tipo; estado.guiaT = Date.now(); }

  // Los códigos UPC-E (envases pequeños, 8 dígitos: "0 878053 8") a veces
  // llegan "expandidos" a 12 o 13 dígitos (0087800000058). Se devuelven tal
  // como están IMPRESOS en el producto: 08780538.
  function upceImpreso(valor, formato) {
    if (formato !== 'upc_e' || !/^\d+$/.test(valor)) return valor;
    if (valor.length === 8) return valor;
    let a = valor;
    if (a.length === 13 && a[0] === '0') a = a.slice(1);
    if (a.length !== 12 || !'01'.includes(a[0])) return valor;
    const ns = a[0], f = a.slice(1, 6), p = a.slice(6, 11), c = a[11];
    let d = null;
    if ('012'.includes(f[2]) && f.slice(3) === '00' && p.slice(0, 2) === '00') d = f.slice(0, 2) + p.slice(2, 5) + f[2];
    else if (f.slice(3) === '00' && p.slice(0, 3) === '000') d = f.slice(0, 3) + p.slice(3, 5) + '3';
    else if (f[4] === '0' && p.slice(0, 4) === '0000') d = f.slice(0, 4) + p[4] + '4';
    else if (p.slice(0, 4) === '0000' && '56789'.includes(p[4])) d = f + p[4];
    return d ? ns + d + c : valor;
  }
  const NOMBRE_FORMATO = { ean_13: 'EAN-13', ean_8: 'EAN-8', upc_a: 'UPC-A', upc_e: 'UPC-E',
                           code_128: 'Code 128', code_39: 'Code 39' };

  // Analiza la imagen unas 8 veces por segundo (sin saturar el teléfono).
  const lienzo = document.createElement('canvas');
  async function ciclo(stream) {
    if (estado.stream !== stream) return;            // la cámara se cerró
    const v = estado.video;
    try {
      if (v && v.readyState >= 2 && v.videoWidth) {
        const escala = Math.min(1, 1280 / Math.max(v.videoWidth, v.videoHeight));
        const w = lienzo.width = Math.round(v.videoWidth * escala);
        const h = lienzo.height = Math.round(v.videoHeight * escala);
        lienzo.getContext('2d', { willReadFrequently: true }).drawImage(v, 0, 0, w, h);
        const r = (await estado.detector.detect(lienzo)) || [];
        if (estado.stream !== stream) return;
        const ahora = Date.now();
        // Elegir el código válido que esté sobre la línea roja.
        let elegido = null, motivo = null;
        for (const c of r) {
          const valor = upceImpreso(String(c.rawValue || '').trim(), c.format);
          if (!valor || !digitoValido(valor, c.format)) continue;
          const pos = revisarPosicion(c, w, h);
          if (pos === 'ok') { elegido = valor; estado.formatoLeido = NOMBRE_FORMATO[c.format] || c.format || ''; break; }
          motivo = motivo || pos;
        }
        if (elegido && ahora - estado.abiertoEn >= ESPERA_INICIAL) {
          const cand = estado.candidato;
          if (cand && cand.valor === elegido && ahora - cand.t < 800) { cand.veces++; cand.t = ahora; }
          else estado.candidato = { valor: elegido, veces: 1, t: ahora };
          if (estado.candidato.veces >= CONFIRMACIONES) { leido(elegido); return; }
          guiar('enfocando');
        } else if (motivo) {
          guiar(motivo);
        }
        if (estado.candidato && ahora - estado.candidato.t > 800) estado.candidato = null;
      }
    } catch (_) {}
    setTimeout(() => ciclo(stream), 110);
  }

  async function abrir(el) {
    estado.abriendo = true;
    try {
      avisar('Abriendo la cámara…');
      const detectorListo = obtenerDetector();            // se carga en paralelo
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
      });
      const video = document.createElement('video');
      video.setAttribute('playsinline', ''); video.setAttribute('muted', '');
      video.muted = true; video.autoplay = true; video.srcObject = stream;
      el.querySelectorAll('video').forEach((x) => x.remove());
      el.prepend(video);
      estado.stream = stream; estado.video = video; estado.elemento = el;
      await video.play().catch(() => {});
      // Enfoque continuo si la cámara lo permite (sin zoom: imagen nítida y clara).
      const pista = stream.getVideoTracks()[0];
      estado.pista = pista;
      try {
        const cap = (pista.getCapabilities && pista.getCapabilities()) || {};
        estado.modosEnfoque = cap.focusMode || [];
        if (estado.modosEnfoque.includes('continuous'))
          await pista.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
      } catch (_) {}
      await detectorListo;
      estado.abiertoEn = Date.now();
      ciclo(stream);
    } catch (e) {
      detener();
      avisar(String(e && e.message).includes('lector')
        ? 'No se pudo cargar el lector de códigos. Revisa la conexión o usa la opción de foto de abajo.'
        : 'No se pudo abrir la cámara. Revisa el permiso o usa la opción de foto de abajo.');
      estado.error = Date.now();
    } finally {
      estado.abriendo = false;
    }
  }

  // Tocar la imagen: enfocar (y de paso activa el sonido).
  document.addEventListener('click', async (e) => {
    if (!estado.pista || !e.target.closest || !e.target.closest('#lector-vivo')) return;
    const modos = estado.modosEnfoque || [];
    try {
      if (modos.includes('single-shot')) {
        await estado.pista.applyConstraints({ advanced: [{ focusMode: 'single-shot' }] });
        setTimeout(() => modos.includes('continuous') && estado.pista &&
          estado.pista.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }).catch(() => {}), 1500);
      }
    } catch (_) {}
  }, true);

  // Vigilar el recuadro: abrir la cámara si está visible, apagarla si no.
  setInterval(() => {
    const el = document.getElementById('lector-vivo');
    const visible = !!(el && el.isConnected && el.offsetParent !== null);
    if (estado.stream && (!visible || estado.elemento !== el)) { detener(); return; }
    if (visible && !estado.stream && !estado.abriendo && !(estado.pausaHasta > Date.now()) &&
        !(estado.error && Date.now() - estado.error < 8000)) abrir(el);
  }, 700);
})();
""".replace("__LECTOR_COMPATIBLE__", LECTOR_COMPATIBLE)

CSS = """
<style>
/* Vista de cámara limpia: imagen completa, bordes redondeados y línea láser. */
.lector-vivo { position: relative; width: 100%; max-width: 560px; margin: 0 auto;
  border-radius: 16px; overflow: hidden; background: #0b1b33;
  height: clamp(220px, 42vh, 380px); }
.lector-vivo video { width: 100%; height: 100%; object-fit: cover; display: block; }
.lector-vivo .laser { position: absolute; left: 8%; right: 8%; top: 50%; height: 3px;
  margin-top: -1px; border-radius: 3px; background: #ff2d2d;
  box-shadow: 0 0 10px 2px rgba(255, 45, 45, .75); pointer-events: none;
  animation: laser-pulso 1.2s ease-in-out infinite; }
@keyframes laser-pulso { 0%, 100% { opacity: .55; } 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .lector-vivo .laser { animation: none; } }
.lector-vivo-aviso { text-align: center; color: #0b315f; font-weight: 800; margin-top: 8px;
  font-size: clamp(16px, 4.6vw, 21px); min-height: 1.4em; }
.lector-vivo-sonido { text-align: center; color: #b45309; font-weight: 700; font-size: 15px; min-height: 1.2em; }
/* Cuadro que recibe el código: montado y funcional, pero fuera de la vista. */
.st-key-camara_codigo { position: absolute !important; left: -10000px !important;
  width: 1px !important; height: 1px !important; overflow: hidden !important; }
</style>
"""


def mostrar_lector(clave_cuadro, al_leer):
    """Dibuja el recuadro de la cámara y el cuadro oculto que recibe el código."""
    from shared import ejecutar_js_en_pagina
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown('<div id="lector-vivo" class="lector-vivo"><div class="laser"></div></div>'
                '<div id="lector-vivo-aviso" class="lector-vivo-aviso">Abriendo la cámara…</div>'
                '<div id="lector-vivo-sonido" class="lector-vivo-sonido"></div>',
                unsafe_allow_html=True)
    with st.container(key="camara_codigo"):
        st.text_input("Código leído por la cámara", key=clave_cuadro,
                      on_change=al_leer, label_visibility="collapsed")
    ejecutar_js_en_pagina(LECTOR_JS, "lector_vivo_js")
