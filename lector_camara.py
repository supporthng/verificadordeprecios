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
  if (window.__lectorVivo) return;          // instalar una sola vez por ventana
  const estado = { lector: null, elemento: null, abriendo: false, ultimo: '', ultimoT: 0 };
  window.__lectorVivo = estado;

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
    const l = estado.lector; estado.lector = null; estado.elemento = null;
    if (l) { try { await l.stop(); } catch (_) {} try { l.clear(); } catch (_) {} }
  }

  async function abrir(el) {
    estado.abriendo = true;
    try {
      await cargarLibreria();
      const L = lib(); const F = L.Html5QrcodeSupportedFormats;
      const formatos = F ? [F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_128, F.CODE_39,
                            F.CODE_93, F.ITF, F.CODABAR, F.QR_CODE].filter((x) => x !== undefined) : undefined;
      const lector = new L.Html5Qrcode('lector-vivo', {
        verbose: false, formatsToSupport: formatos,
        experimentalFeatures: { useBarCodeDetectorIfSupported: true },
      });
      estado.lector = lector; estado.elemento = el;
      avisar('Apunta la cámara al código de barras…');
      await lector.start(
        { facingMode: 'environment' },
        { fps: 12, qrbox: (w, h) => ({ width: Math.floor(w * 0.85), height: Math.floor(Math.min(h * 0.5, w * 0.45)) }) },
        (texto) => {
          const ahora = Date.now();
          if (texto === estado.ultimo && ahora - estado.ultimoT < 3000) return;  // evitar duplicados
          estado.ultimo = texto; estado.ultimoT = ahora;
          if (navigator.vibrate) navigator.vibrate(80);
          avisar('Código leído: ' + texto + ' · consultando…');
          estado.pausaHasta = ahora + 2500;   // no reabrir mientras se muestra el resultado
          detener().then(() => enviar(texto));
        },
        () => {}
      );
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
.lector-vivo-aviso { text-align: center; color: #0b315f; font-weight: 700; margin-top: 6px; }
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
                '<div id="lector-vivo-aviso" class="lector-vivo-aviso">Abriendo la cámara…</div>',
                unsafe_allow_html=True)
    with st.container(key="camara_codigo"):
        st.text_input("Código leído por la cámara", key=clave_cuadro,
                      on_change=al_leer, label_visibility="collapsed")
    ejecutar_js_en_pagina(LECTOR_JS, "lector_vivo_js")
