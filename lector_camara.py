"""Lectura de códigos con la cámara EN VIVO (sin tomar foto).

El JavaScript corre en la página principal:
- Cuando aparece el recuadro #lector-vivo (y está visible), abre la cámara
  trasera y busca códigos de barras con html5-qrcode (usa el lector nativo del
  navegador si existe; si no, ZXing en el propio teléfono).
- Al detectar un código, apaga la cámara y lo escribe en un cuadro oculto de
  Streamlit, igual que un lector de códigos: Streamlit consulta como siempre.
- Si el recuadro desaparece (se muestra el resultado o se cambia de pestaña),
  apaga la cámara. Al volver a escanear, la abre de nuevo.
"""
import streamlit as st

LIBRERIA = "https://cdnjs.cloudflare.com/ajax/libs/html5-qrcode/2.3.8/html5-qrcode.min.js"

LECTOR_JS = r"""
(() => {
  if (window.__lectorVivoV3) return;        // instalar una sola vez por ventana
  const estado = { lector: null, elemento: null, abriendo: false, ultimo: '', ultimoT: 0 };
  window.__lectorVivoV3 = estado;

  // ---------- Sonido de lector ("bip") ----------
  // Se reproduce como ARCHIVO de audio (<audio>): en iPhone suena aunque el
  // teléfono esté en modo silencio (Web Audio queda mudo con el interruptor).
  // Los navegadores exigen un primer toque en la pantalla para permitir sonido.
  function crearBip() {
    const sr = 22050, n = Math.floor(sr * 0.12), buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
    const txt = (o, t) => { for (let k = 0; k < t.length; k++) v.setUint8(o + k, t.charCodeAt(k)); };
    txt(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); txt(8, 'WAVE'); txt(12, 'fmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    txt(36, 'data'); v.setUint32(40, n * 2, true);
    for (let k = 0; k < n; k++) {
      const env = Math.min(1, k / 150, (n - k) / 300);                 // sin chasquidos
      const onda = Math.sin(2 * Math.PI * 2700 * k / sr) >= 0 ? 1 : -1;  // tono de lector
      v.setInt16(44 + k * 2, Math.round(onda * env * 0.55 * 32767), true);
    }
    return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
  }
  const bip = new Audio(crearBip()); bip.preload = 'auto';
  estado.sonidoListo = false;
  function activarSonido() {
    if (estado.sonidoListo) return;
    bip.muted = true;                       // reproducción muda dentro del toque = permiso
    bip.play().then(() => {
      bip.pause(); bip.currentTime = 0; bip.muted = false;
      estado.sonidoListo = true; mostrarSonido();
    }).catch(() => { bip.muted = false; });
  }
  ['pointerdown', 'touchend', 'click', 'keydown'].forEach((ev) =>
    document.addEventListener(ev, activarSonido, { capture: true, passive: true }));
  function pitido() {
    try { bip.currentTime = 0; } catch (_) {}
    bip.play().catch(() => {
      // Respaldo: Web Audio (si el navegador no dejó usar el archivo).
      try {
        const A = window.AudioContext || window.webkitAudioContext; if (!A) return;
        const ctx = estado.ctx || (estado.ctx = new A()); const t = ctx.currentTime;
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'square'; o.frequency.setValueAtTime(2700, t);
        g.gain.setValueAtTime(0.22, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.13);
        o.connect(g); g.connect(ctx.destination); o.start(t); o.stop(t + 0.14);
      } catch (_) {}
    });
  }
  function mostrarSonido() {
    const s = document.querySelector('#lector-vivo-sonido');
    if (s) s.textContent = estado.sonidoListo ? '' : '🔈 Toca la imagen para activar el sonido';
  }

  // ---------- Guía de distancia ----------
  // Mientras no lee, alterna indicaciones para acercar o alejar el teléfono.
  const GUIA = [
    '🎯 Centra el código dentro de la franja',
    '🔍 Acerca un poco el teléfono',
    '↔️ Aleja un poco el teléfono',
    '✋ Mantén el teléfono quieto un momento',
  ];
  setInterval(() => {
    if (!estado.lector || !estado.abiertoEn) return;
    const seg = (Date.now() - estado.abiertoEn) / 1000;
    if (seg < 2.5) { avisar('📏 Distancia ideal: 15–20 cm del código'); }
    else avisar(GUIA[Math.floor((seg - 2.5) / 2.2) % GUIA.length]);
    mostrarSonido();
  }, 500);

  function cargarLibreria() {
    if (window.Html5Qrcode || (window.__Html5QrcodeLibrary__ && window.__Html5QrcodeLibrary__.Html5Qrcode))
      return Promise.resolve();
    if (estado.cargando) return estado.cargando;
    estado.cargando = new Promise((ok, mal) => {
      const s = document.createElement('script');
      s.src = '__LIBRERIA__'; s.async = true;
      s.onload = ok; s.onerror = () => { estado.cargando = null; mal(new Error('No se pudo cargar el lector')); };
      document.head.appendChild(s);
    });
    return estado.cargando;
  }
  const lib = () => window.__Html5QrcodeLibrary__ || window;

  function avisar(texto) {
    const a = document.querySelector('#lector-vivo-aviso');
    if (a) a.textContent = texto || '';
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

  async function detener() {
    const l = estado.lector; estado.lector = null; estado.elemento = null; estado.abiertoEn = 0;
    if (l) { try { await l.stop(); } catch (_) {} try { l.clear(); } catch (_) {} }
  }

  // ---------- Enfoque ----------
  // 1) Enfoque continuo. 2) Un poco de zoom (1.6x) si la cámara lo permite: así
  // el teléfono se aleja del código y entra en su distancia de enfoque (los
  // iPhone recientes no enfocan bien muy de cerca). 3) Tocar la imagen = enfocar.
  async function mejorarEnfoque(lector) {
    try {
      const cap = (lector.getRunningTrackCapabilities && lector.getRunningTrackCapabilities()) || {};
      const ajustes = [];
      if ((cap.focusMode || []).includes('continuous')) ajustes.push({ focusMode: 'continuous' });
      if (cap.zoom && cap.zoom.max > 1) ajustes.push({ zoom: Math.min(cap.zoom.max, Math.max(cap.zoom.min || 1, 1.6)) });
      if (ajustes.length) await lector.applyVideoConstraints({ advanced: ajustes });
      estado.capacidades = cap;
    } catch (_) {}
  }
  document.addEventListener('click', async (e) => {
    if (!estado.lector || !e.target.closest || !e.target.closest('#lector-vivo')) return;
    const modos = (estado.capacidades && estado.capacidades.focusMode) || [];
    try {
      if (modos.includes('single-shot')) {
        await estado.lector.applyVideoConstraints({ advanced: [{ focusMode: 'single-shot' }] });
        setTimeout(() => estado.lector && modos.includes('continuous') &&
          estado.lector.applyVideoConstraints({ advanced: [{ focusMode: 'continuous' }] }).catch(() => {}), 1500);
      }
    } catch (_) {}
  }, true);

  async function abrir(el) {
    estado.abriendo = true;
    try {
      await cargarLibreria();
      const L = lib(); const F = L.Html5QrcodeSupportedFormats;
      // Solo los formatos de productos: menos formatos = lectura más rápida.
      const formatos = F ? [F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_128, F.CODE_39]
                            .filter((x) => x !== undefined) : undefined;
      const lector = new L.Html5Qrcode('lector-vivo', {
        verbose: false, formatsToSupport: formatos,
        experimentalFeatures: { useBarCodeDetectorIfSupported: true },
      });
      estado.lector = lector; estado.elemento = el; estado.abiertoEn = 0;
      avisar('Abriendo la cámara…');
      await lector.start(
        { facingMode: 'environment' },
        {
          fps: 15,
          // Franja horizontal (forma de código de barras): menos imagen que analizar.
          qrbox: (w, h) => ({ width: Math.floor(w * 0.82), height: Math.floor(Math.min(h * 0.4, w * 0.34)) }),
          // Resolución HD (el enfoque y el zoom se aplican al abrir: mejorarEnfoque).
          videoConstraints: {
            facingMode: { ideal: 'environment' },
            width: { ideal: 1280 }, height: { ideal: 720 },
          },
        },
        (texto) => {
          const ahora = Date.now();
          if (texto === estado.ultimo && ahora - estado.ultimoT < 3000) return;  // evitar duplicados
          estado.ultimo = texto; estado.ultimoT = ahora;
          pitido();
          if (navigator.vibrate) navigator.vibrate(80);
          avisar('Código leído: ' + texto + ' · consultando…');
          estado.pausaHasta = ahora + 2500;   // no reabrir mientras se muestra el resultado
          detener().then(() => enviar(texto));
        },
        () => {}
      );
      estado.abiertoEn = Date.now();
      await mejorarEnfoque(lector);
    } catch (e) {
      await detener();
      avisar('No se pudo abrir la cámara. Revisa el permiso o usa la opción de foto de abajo.');
      estado.error = Date.now();
    } finally {
      estado.abriendo = false;
    }
  }

  // Vigilar el recuadro: abrir la cámara si está visible, apagarla si no.
  setInterval(() => {
    const el = document.getElementById('lector-vivo');
    const visible = !!(el && el.isConnected && el.offsetParent !== null);
    if (estado.lector && (!visible || estado.elemento !== el)) { detener(); return; }
    if (visible && !estado.lector && !estado.abriendo && !(estado.pausaHasta > Date.now()) &&
        !(estado.error && Date.now() - estado.error < 8000)) abrir(el);
  }, 700);
})();
""".replace("__LIBRERIA__", LIBRERIA)

CSS = """
<style>
.lector-vivo { width: 100%; max-width: 520px; margin: 0 auto; border-radius: 14px;
  overflow: hidden; background: #0b1b33; min-height: 220px; }
.lector-vivo video { width: 100% !important; height: auto !important; display: block; }
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
    st.markdown('<div id="lector-vivo" class="lector-vivo"></div>'
                '<div id="lector-vivo-aviso" class="lector-vivo-aviso">Abriendo la cámara…</div>'
                '<div id="lector-vivo-sonido" class="lector-vivo-sonido"></div>',
                unsafe_allow_html=True)
    with st.container(key="camara_codigo"):
        st.text_input("Código leído por la cámara", key=clave_cuadro,
                      on_change=al_leer, label_visibility="collapsed")
    ejecutar_js_en_pagina(LECTOR_JS, "lector_vivo_js")
