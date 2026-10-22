import html
import re
import base64
from io import BytesIO
from PIL import Image, ImageOps
from datetime import datetime, timedelta, timezone
import time
import inspect

import pandas as pd
import requests
import streamlit as st

# El enfoque se aplica directamente al textbox nativo de Streamlit.
# No utiliza declare_component ni iframe: evita el RuntimeError anterior.
FOCO_JS = r"""
(() => {
  // Solo el cuadro del verificador (contenedor con clave fija), nunca otros
  // cuadros de la app. Si hay dos (el nuevo y el que está desapareciendo tras
  // una lectura), se usa el ÚLTIMO, que es el nuevo.
  const SELECTOR = '.st-key-cuadro_codigo input';
  const cuadro = () => {
    const lista = document.querySelectorAll(SELECTOR);
    return lista.length ? lista[lista.length - 1] : null;
  };
  const editable = (el) => !!(el && el !== document.body && el.matches &&
    el.matches('input,textarea,select,[contenteditable="true"]'));
  const esNuestro = (el) => !!(el && el.closest && el.closest('.st-key-cuadro_codigo'));
  function enfocar() {
    const input = cuadro();
    if (!input || input.disabled || input.readOnly) return;
    const activo = document.activeElement;
    if (activo === input) return;
    // No interrumpir si alguien escribe en OTRO control (p. ej. clave de admin).
    if (editable(activo) && !esNuestro(activo)) return;
    try { input.focus({preventScroll: true}); } catch (_) { input.focus(); }
  }
  window.__cpEnfocar = enfocar;
  // Instalar una sola vez por ventana, aunque el fragmento se actualice.
  if (!window.__cpFocoV2) {
    window.__cpFocoV2 = true;
    new MutationObserver(() => requestAnimationFrame(() => window.__cpEnfocar()))
      .observe(document.body, {childList: true, subtree: true});
    ['focus', 'pageshow', 'click', 'touchend'].forEach((ev) =>
      window.addEventListener(ev, () => setTimeout(() => window.__cpEnfocar(), 0), true));
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) setTimeout(() => window.__cpEnfocar(), 100);
    });
    // Respaldo para el escáner: si llega una tecla y el cursor NO está en un
    // cuadro de texto, se mueve al cuadro del verificador ANTES de que la tecla
    // se escriba, así no se pierde ningún dígito.
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      if (editable(document.activeElement)) return;
      window.__cpEnfocar();
    }, true);
    setInterval(() => window.__cpEnfocar(), 500);
  }
  requestAnimationFrame(() => setTimeout(enfocar, 50));
})();
"""

SUPABASE_URL = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
SUPABASE_ANON_KEY = str(st.secrets.get("SUPABASE_ANON_KEY", "")).strip()

SUPABASE_SERVICE_ROLE_KEY = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()

def admin_api(method, table, params=None, payload=None):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Falta SUPABASE_SERVICE_ROLE_KEY en Secrets.")
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": "Bearer " + SUPABASE_SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    response = requests.request(
        method, f"{SUPABASE_URL}/rest/v1/{table}",
        params=params, json=payload, headers=headers, timeout=12,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=4, show_spinner=False)
def active_source():
    settings = admin_api("GET", "price_source_settings",
                         params={"id": "eq.1", "select": "source_type"})
    if not settings:
        raise RuntimeError("Falta configurar el origen de datos.")
    mode = settings[0]["source_type"]
    if mode == "local":
        return mode, None
    if mode == "google":
        return mode, None
    if mode != "external":
        raise RuntimeError("Origen de datos desconocido.")
    sources = admin_api("GET", "external_price_sources",
                        params={"enabled": "eq.true", "select": "id,name", "limit": "2"})
    if len(sources) != 1:
        raise RuntimeError(
            "La fuente externa requiere exactamente una configuración habilitada. "
            "Configúrala en Fuentes de datos."
        )
    return mode, sources[0]["id"]


@st.cache_data(ttl=60, show_spinner=False)
def cargar_imagen(nombre):
    """Lee una imagen (logo.png o qr-movil.png) del bucket privado de Supabase."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return None
    try:
        response = requests.get(
            f"{SUPABASE_URL}/storage/v1/object/logo-negocio/{nombre}",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": "Bearer " + SUPABASE_SERVICE_ROLE_KEY,
            },
            timeout=8,
        )
        if response.status_code == 200 and response.headers.get("content-type", "").startswith("image/"):
            return response.content
    except requests.RequestException:
        pass
    return None


@st.cache_data(ttl=60, show_spinner=False)
def imagen_base64(nombre, ancho, alto):
    """Imagen ya redimensionada y codificada. Se calcula una vez por minuto,
    no en cada actualización del verificador (que ocurre cada segundo)."""
    datos = cargar_imagen(nombre)
    if not datos:
        return None
    try:
        with Image.open(BytesIO(datos)) as original:
            imagen = ImageOps.contain(original.convert("RGBA"), (ancho, alto))
            salida = BytesIO()
            imagen.save(salida, format="PNG")
        return base64.b64encode(salida.getvalue()).decode("ascii")
    except (OSError, ValueError):
        return None


CSS = """
<style>
.stApp { background: #f4f7fc; }
.block-container {
    max-width: 100%;
    padding: .5rem .8rem 1rem;
}
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.main-header {
    background: linear-gradient(135deg, #0c2e59, #0759c9);
    border-radius: 20px;
    padding: clamp(12px, 3vw, 28px);
    text-align: center;
    color: white;
    margin-bottom: 12px;
}
.main-header h1 {
    color: white !important;
    font-size: clamp(20px, 4vw, 38px);
    margin: 0;
}
.main-header p {
    color: #dceaff;
    font-size: clamp(12px, 2vw, 17px);
    margin: 6px 0 0;
}
.scan-title {
    color: #102b50;
    text-align: center;
    font-weight: 850;
    font-size: clamp(18px, 3.5vw, 32px);
    margin: 10px 0;
}
div[data-testid="stTextInput"] input {
    text-align: center !important;
    font-size: clamp(16px, 2vw, 21px) !important;
    min-height: 44px;
    height: 44px;
    padding: 4px 12px;
    border-radius: 14px;
    border: 2px solid #d5e1f1;
    background: white;
}
.product-card {
    background: white;
    border: 1px solid #dce5f2;
    border-radius: 20px;
    padding: clamp(16px, 4vw, 36px);
    text-align: center;
    margin: 10px auto;
    box-shadow: 0 7px 25px rgba(20,50,90,.07);
}
/* Resultado ampliado para pantallas de verificadores de precios. */
.product-card.result-card {
    width: 100%;
    min-height: 76dvh;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: clamp(8px, 1.5vh, 18px);
    padding: clamp(16px, 3vw, 40px);
    margin: 0 auto;
}
.result-card .product-name {
    font-size: clamp(28px, 5.5vw, 66px);
    margin: 2px 0;
}
.result-card .product-code {
    font-size: clamp(17px, 2.5vw, 26px);
    margin: 0;
}
.result-card .product-price {
    font-size: clamp(54px, 10vw, 126px);
    margin: 0;
}
.result-card .product-label, .result-card .price-label {
    font-size: clamp(15px, 2vw, 23px);
}
@media (max-width: 600px) {
    .product-card.result-card { min-height: 72dvh; }
    .result-card .product-price { font-size: clamp(42px, 11vw, 78px); }
}
@media (orientation: landscape) and (max-height: 650px) {
    .product-card.result-card { min-height: 79dvh; padding: 10px 22px; gap: 6px; }
    .result-card .product-name { font-size: clamp(28px, 5vw, 58px); }
    .result-card .product-price { font-size: clamp(55px, 9vw, 110px); }
}
.product-label, .price-label {
    color: #64748b;
    font-weight: 800;
    letter-spacing: 1px;
    font-size: clamp(12px, 2vw, 17px);
}
.product-name {
    color: #102b50;
    font-size: clamp(22px, 4.5vw, 40px);
    font-weight: 850;
    overflow-wrap: anywhere;
    line-height: 1.2;
    margin: 12px 0;
}
.product-code {
    color: #64748b;
    font-size: clamp(14px, 2vw, 21px);
    overflow-wrap: anywhere;
    margin-bottom: 22px;
}
.product-price {
    color: #0757c3;
    font-size: clamp(40px, 8vw, 76px);
    font-weight: 900;
    line-height: 1.1;
    overflow-wrap: anywhere;
    margin-top: 8px;
}
@media (max-width: 600px) {
    .block-container { padding: .6rem .6rem 1rem; }
    .main-header { padding: 13px 10px; margin-bottom: 8px; }
    .main-header h1 { font-size: clamp(19px, 5.5vw, 27px); }
    .scan-title { margin: 6px 0; font-size: clamp(17px, 5vw, 24px); }
    div[data-testid="stTextInput"] input { min-height: 48px; }
    .product-card { padding: 18px 12px; }
}
@media (orientation: landscape) and (max-height: 650px) {
    .block-container { padding-top: .25rem; padding-bottom: .4rem; }
    .main-header { padding: 8px 12px; margin-bottom: 5px; }
    .main-header h1 { font-size: clamp(18px, 3vw, 27px); }
    .main-header p { margin-top: 2px; font-size: 12px; }
    .scan-title { margin: 4px 0; font-size: clamp(17px, 3vw, 24px); }
    div[data-testid="stTextInput"] input { min-height: 44px; }
    .product-card { padding: 12px; margin: 4px auto; }
    .product-name { margin: 6px 0; }
    .product-code { margin-bottom: 8px; }
}

.search-card { min-height: 255px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; }
.search-card .search-label { color: #64748b; font-weight: 800; letter-spacing: 1px; font-size: 14px; }
.search-card .search-text { color: #102b50; font-weight: 750; font-size: clamp(18px, 3vw, 24px); }
.search-visual { width: min(300px, 90%); height: 105px; overflow: hidden; }
.search-lens { animation: scan-barcode 2.1s ease-in-out infinite; transform-origin: center; }
@keyframes scan-barcode { 0%, 100% { transform: translateX(0); } 50% { transform: translateX(180px); } }
@media (prefers-reduced-motion: reduce) { .search-lens { animation: none; } }
.not-found-name { color: #102b50; font-size: clamp(23px, 4.5vw, 40px); font-weight: 850; line-height: 1.2; margin: 16px 0; }
.business-logo-label {
    text-align: center;
    color: #64748b;
    font-weight: 750;
    letter-spacing: 1px;
    margin: 22px 0 8px;
}

/* Codigo de barras decorativo con barrido continuo, sin recursos externos. */
.animated-barcode-card {
    width: min(310px, 75vw); margin: 8px auto 20px; padding: 16px 18px 12px;
    background: #fff; border-radius: 12px; text-align: center;
    box-shadow: 0 2px 10px rgba(20,50,90,.04);
}
.animated-bars {
    position: relative; height: 105px; overflow: hidden;
    background: repeating-linear-gradient(90deg,
        #102b50 0px, #102b50 2px, #fff 2px, #fff 5px,
        #102b50 5px, #102b50 9px, #fff 9px, #fff 12px,
        #102b50 12px, #102b50 13px, #fff 13px, #fff 17px,
        #102b50 17px, #102b50 22px, #fff 22px, #fff 26px);
}
.animated-scan-line {
    position: absolute; top: 0; bottom: 0; left: 0; width: 4px;
    background: #ff9d20; box-shadow: 0 0 9px 3px rgba(255,157,32,.7);
    animation: barcode-sweep 2.4s ease-in-out infinite alternate;
}
@keyframes barcode-sweep { from { left: 0; } to { left: calc(100% - 4px); } }
.animated-barcode-caption { color: #102b50; margin-top: 10px; font-size: 16px; }
@media (prefers-reduced-motion: reduce) { .animated-scan-line { animation: none; left: 50%; } }
@media (max-width: 600px) { .animated-barcode-card { width: min(260px, 76vw); } }
</style>
"""
# Color verde del campo de la antigua Prueba del Cursor.
# Solo modifica la apariencia; no cambia el mecanismo de enfoque.
CSS += """
<style>
div[data-testid="stTextInput"] input:focus,
div[data-testid="stTextInput"] input:focus-visible {
    outline: none !important;
    border-color: #16823c !important;
    box-shadow: 0 0 0 3px #d9f5df !important;
}
</style>
"""

# Ajuste para pantallas integradas de verificadores (ej. 2connect).
# Se preserva la lógica del escáner, el enfoque y los tiempos de resultados.
CSS += """
<style>
@media (max-height: 720px) and (min-width: 600px) {
  [data-testid="stMainBlockContainer"], .block-container {
    padding-top: 0.25rem !important;
    padding-bottom: 0.2rem !important;
  }
  [data-testid="stVerticalBlock"] { gap: 0.35rem !important; }
  .main-header {
    padding: 9px 14px !important;
    margin-bottom: 2px !important;
    border-radius: 12px !important;
  }
  .main-header h1 { font-size: clamp(19px, 3.2vh, 27px) !important; }
  .main-header p { font-size: 11px !important; margin-top: 2px !important; }
  .animated-barcode-card {
    height: auto !important;
    width: min(260px, 60vw) !important;
    padding: 8px 12px 6px !important;
    margin: 1px auto 2px !important;
  }
  .animated-bars { height: clamp(45px, 11vh, 70px) !important; }
  .animated-barcode-caption { margin-top: 3px !important; font-size: 12px !important; }
  .scan-title { margin: 2px 0 !important; font-size: clamp(17px, 3vh, 23px) !important; }
  div[data-testid="stTextInput"] input {
    height: 39px !important;
    min-height: 39px !important;
  }
  [data-testid="stImage"] img {
    max-height: clamp(55px, 14vh, 88px) !important;
    width: auto !important;
    object-fit: contain !important;
    margin: 0 auto !important;
  }
  [data-testid="stImage"] { text-align: center !important; }
  .product-card.result-card {
    min-height: 68dvh !important;
    padding: 12px 20px !important;
  }
}
@media (max-height: 480px) and (min-width: 600px) {
  .main-header { padding: 6px 12px !important; }
  .animated-bars { height: 42px !important; }
  .animated-barcode-card { padding: 5px 10px 3px !important; }
  .scan-title { font-size: 17px !important; }
  [data-testid="stImage"] img { max-height: 54px !important; }
}
</style>
"""

# El textbox sigue en el DOM y recibe el foco y los codigos del escaner.
# Se oculta solo visualmente: NO usar display:none ni visibility:hidden.
# Se aplica o no según la pestaña Apariencia (ver verificador()).
CSS_CUADRO_OCULTO = """
<style>
/* El contenedor sale del flujo: no ocupa espacio ni separación en pantalla. */
.st-key-cuadro_codigo {
    position: absolute !important; width: 0 !important; height: 0 !important;
    overflow: visible !important; margin: 0 !important;
}
/* El input sigue montado y enfocable; solo se oculta visualmente.
   Nunca usar display:none, visibility:hidden ni type=hidden. */
div[data-testid="stTextInput"] {
    position: absolute !important;
    left: -10000px !important;
    top: auto !important;
    width: 300px !important;
    height: 48px !important;
    opacity: 0 !important;
    overflow: visible !important;
    pointer-events: none !important;
}
div[data-testid="stTextInput"] input {
    width: 300px !important;
    height: 48px !important;
    opacity: 0 !important;
    pointer-events: none !important;
}
</style>
"""

# Cuadro visible: centrado y discreto. Sigue recibiendo el foco igual.
CSS_CUADRO_VISIBLE = """
<style>
div[data-testid="stTextInput"] {
    max-width: 460px !important;
    margin: 0 auto 6px !important;
}
div[data-testid="stTextInput"] input {
    text-align: center !important;
    font-size: 20px !important;
    letter-spacing: 1px;
}
</style>
"""

# Pantalla 2connect: distribuir el contenido por la ALTURA real del visor.
# No cambiar el input oculto, FOCO_JS, ni la lógica del lector.
CSS += """
<style>
.stApp { background:#f4f8ff !important; }
.main-header {
  background:linear-gradient(110deg,#0b315f,#0757d4) !important;
  border-radius:14px !important;
  box-shadow:0 5px 14px rgba(8,60,130,.10) !important;
  padding:clamp(14px,3vh,24px) 48px !important;
  margin-bottom:clamp(12px,3vh,24px) !important;
}
.main-header h1 { font-size:clamp(22px,3.6vw,37px) !important; }
.main-header p { font-size:clamp(12px,1.5vw,16px) !important; }
.animated-barcode-card {
  width:min(460px,75vw) !important;
  max-width:100% !important;
  padding:clamp(12px,2vh,22px) clamp(15px,2vw,25px) 10px !important;
  margin:0 auto clamp(14px,3vh,24px) !important;
  border-radius:16px !important;
  box-shadow:0 6px 18px rgba(17,54,98,.10) !important;
}
.animated-bars { height:clamp(75px,18vh,140px) !important; }
.animated-barcode-caption { margin-top:7px !important; font-size:clamp(13px,1.6vw,17px) !important; }
.scan-title { font-size:clamp(22px,3.2vw,34px) !important; margin:0 !important; }
.scan-hint { color:#7c8ca6; text-align:center; font-weight:500;
  font-size:clamp(14px,1.8vw,19px); margin:5px auto 0; }
[data-testid="stImage"] { text-align:center !important; }
[data-testid="stImage"] img { object-fit:contain !important; width:auto !important; margin:auto !important; }
/* Pantalla horizontal del equipo: evitar el diseño miniatura anterior.
   Escalar tamaños con la altura útil en vez de reducirlos al mínimo. */
@media (orientation:landscape) and (min-width:600px) and (max-height:800px) {
  [data-testid="stMainBlockContainer"], .block-container {
    padding-top:0.25rem !important;
    padding-bottom:0.15rem !important;
  }
  [data-testid="stVerticalBlock"] { gap:clamp(4px,1.1vh,10px) !important; }
  .main-header {
    box-sizing:border-box !important;
    min-height:clamp(82px,20dvh,142px) !important;
    padding:clamp(12px,3vh,20px) 50px !important;
    margin-bottom:clamp(10px,2.5vh,18px) !important;
    display:flex !important;
    flex-direction:column !important;
    justify-content:center !important;
  }
  .main-header h1 { font-size:clamp(22px,5vh,34px) !important; }
  .main-header p { font-size:clamp(12px,2.7vh,16px) !important; margin-top:5px !important; }
  .animated-barcode-card {
    width:min(440px,70vw) !important;
    padding:clamp(10px,2vh,18px) 20px 9px !important;
    margin:0 auto clamp(12px,3vh,22px) !important;
  }
  .animated-bars { height:clamp(80px,21dvh,140px) !important; }
  .animated-barcode-caption { font-size:clamp(13px,2.8vh,17px) !important; margin-top:6px !important; }
  .scan-title { font-size:clamp(21px,4.8vh,32px) !important; }
  .scan-hint { font-size:clamp(13px,3vh,18px) !important; margin-top:5px !important; }
  [data-testid="stImage"] img { max-height:clamp(65px,16dvh,110px) !important; }
}
@media (orientation:landscape) and (min-width:600px) and (max-height:420px) {
  .main-header { min-height:72px !important; margin-bottom:6px !important; }
  .animated-barcode-card { margin-bottom:6px !important; padding:7px 16px 5px !important; }
  .animated-bars { height:clamp(60px,19dvh,90px) !important; }
  .scan-title { font-size:clamp(18px,4.8vh,24px) !important; }
  [data-testid="stImage"] img { max-height:clamp(48px,13dvh,70px) !important; }
}
@media (max-width:599px) {
  .main-header { padding:13px 38px !important; }
  .main-header h1 { font-size:clamp(17px,4.7vw,24px) !important; }
  .animated-barcode-card { width:min(330px,80vw) !important; }
  .scan-title { font-size:clamp(18px,5vw,24px) !important; }
}
</style>
"""

# Prioridad sobre reglas de pantallas compactas anteriores.
CSS += """
<style>
@media (max-height: 800px) and (min-width: 600px) {
  [data-testid="stImage"] { display: flex !important; justify-content: center !important; }
  [data-testid="stImage"] img {
    max-height: 112px !important;
    max-width: 145px !important;
    width: auto !important;
    object-fit: contain !important;
  }
}
</style>
"""
# Solo en PRODUCTO NO ENCONTRADO: barras rojas estáticas y fondo tenue.
CSS += """<style>
.animated-barcode-card.barcode-not-found {background:#fff1f2 !important;}
.animated-barcode-card.barcode-not-found .animated-bars {
  background:repeating-linear-gradient(90deg,#b91c1c 0px,#b91c1c 3px,transparent 3px,transparent 6px,#dc2626 6px,#dc2626 8px,transparent 8px,transparent 12px) !important;
  animation:none !important;
}
.animated-barcode-card.barcode-not-found .animated-scan-line,
.animated-barcode-card.barcode-not-found .animated-bars::before,
.animated-barcode-card.barcode-not-found .animated-bars::after {display:none !important;animation:none !important;}
.scan-title.scan-title-not-found {color:#b91c1c !important;font-weight:800 !important;}
</style>"""

# Diseño aprobado: producto sin fotografía, precio en franja azul.
CSS += """<style>
.resultado-pantalla {
  box-sizing: border-box !important;
  width: 100% !important;
  height: min(86dvh, 760px) !important;
  min-height: 250px !important;
  margin: 0 auto !important;
  border-radius: 15px !important;
  overflow: hidden !important;
  background: #f6faff !important;
  display: flex !important;
  flex-direction: column !important;
  box-shadow: 0 4px 18px rgba(14,49,101,.07);
  text-align: center !important;
}
.resultado-datos {
  flex: 1 1 53% !important;
  min-height: 0 !important;
  display: flex !important;
  flex-direction: column !important;
  align-items: center !important;
  justify-content: center !important;
  gap: clamp(4px, 1.2dvh, 12px) !important;
  padding: 8px 20px !important;
}
.resultado-etiqueta {color:#8799b4;letter-spacing:.15em;font-weight:800;font-size:clamp(12px,1.5vw,19px)}
.resultado-nombre {color:#0d2d58;font-weight:900;font-size:clamp(24px,3.3vw,56px);line-height:1.13;overflow-wrap:anywhere;max-width:100%;text-wrap:balance}
.resultado-codigo {color:#8497b2;font-size:clamp(13px,1.5vw,22px)}
.resultado-precio-panel {
  flex: 0 0 42% !important;
  min-height: 0 !important;
  background:linear-gradient(105deg,#0860e8,#0851d3) !important;
  color:white !important;
  display:flex !important;
  flex-direction:row !important;
  justify-content:center !important;
  align-items:center !important;
  gap:clamp(12px,2vw,35px) !important;
  padding:8px 18px !important;
}
.resultado-precio-etiqueta {font-weight:800;letter-spacing:.05em;font-size:clamp(13px,1.5vw,22px);white-space:nowrap;color:white}
.resultado-precio {font-weight:900;font-size:clamp(44px,5.9vw,105px);line-height:1.04;white-space:nowrap;color:white;font-variant-numeric:tabular-nums}
@media (max-width:650px) {
  .resultado-precio-panel {flex-direction:column !important;gap:4px !important;}
  .resultado-precio {font-size:clamp(38px,8vw,65px)}
}
@media (orientation:landscape) and (max-height:550px) {
  .resultado-pantalla {height:87dvh !important;}
  .resultado-datos {flex-basis:53% !important;padding:5px 14px !important;gap:4px !important;}
  .resultado-nombre {font-size:clamp(20px,3.3vw,43px) !important;}
  .resultado-precio-panel {flex-basis:43% !important;}
  .resultado-precio {font-size:clamp(40px,6vw,78px) !important;}
}
</style>"""


# Tipografía ampliada para el resultado, ajustada al 2connect horizontal.
# Se aplica al final para prevalecer sobre las reglas compactas anteriores.
CSS += """<style>
.resultado-pantalla .resultado-datos {
  padding: clamp(10px,2dvh,22px) clamp(14px,3vw,40px) !important;
  gap: clamp(8px,2dvh,16px) !important;
}
.resultado-pantalla .resultado-nombre {
  font-size: clamp(31px, 4.6vw, 72px) !important;
  line-height: 1.12 !important;
  max-width: 96% !important;
  text-wrap: balance !important;
}
.resultado-pantalla .resultado-etiqueta {
  font-size: clamp(15px, 1.8vw, 23px) !important;
}
.resultado-pantalla .resultado-codigo {
  font-size: clamp(17px, 2.1vw, 27px) !important;
}
.resultado-pantalla .resultado-precio-panel {
  flex-direction: column !important;
  gap: clamp(5px,1.2dvh,14px) !important;
}
.resultado-pantalla .resultado-precio-etiqueta {
  font-size: clamp(17px, 2.2vw, 27px) !important;
}
.resultado-pantalla .resultado-precio {
  font-size: clamp(64px, 9.5vw, 136px) !important;
  line-height: 1.05 !important;
}
@media (orientation: landscape) and (max-height: 550px) {
  .resultado-pantalla .resultado-nombre {font-size: clamp(29px,4.2vw,58px) !important;}
  .resultado-pantalla .resultado-precio {font-size: clamp(59px,8.7vw,112px) !important;}
  .resultado-pantalla .resultado-datos {gap: 6px !important;}
}
</style>"""

# Diseño final: TODO cabe en una pantalla (p. ej. 2connect 1024x600), sin
# desplazarse. Va al final para prevalecer sobre las reglas anteriores.
CSS += """<style>
/* Elementos que solo llevan estilos o scripts: no ocupan espacio ni separación. */
[data-testid="stElementContainer"]:has([data-testid="stMarkdownContainer"]):not(:has([data-testid="stMarkdownContainer"] > :not(style))) {
  display: none !important;
}
/* Streamlit pone márgenes negativos (-1rem) a los bloques de texto: subían el
   bloque siguiente y el código de barras se montaba sobre la franja azul.
   Se anulan aquí; la separación la da el espacio entre elementos (gap). */
[data-testid="stElementContainer"]:has(.main-header, .animated-barcode-card, .scan-title, .verif-imagenes),
[data-testid="stElementContainer"]:has(.main-header, .animated-barcode-card, .scan-title, .verif-imagenes) [data-testid="stMarkdown"],
[data-testid="stElementContainer"]:has(.main-header, .animated-barcode-card, .scan-title, .verif-imagenes) [data-testid="stMarkdownContainer"] {
  margin-top: 0 !important;
  margin-bottom: 0 !important;
}
.main-header, .animated-barcode-card { position: relative; }
/* Logo y QR */
.verif-imagenes {
  width: 100%; display: flex; justify-content: center; align-items: center;
  gap: clamp(18px, 5vw, 64px); margin: 0 auto;
}
.verif-logo {
  display: block; width: auto; height: auto; object-fit: contain;
  max-width: min(32vw, 300px); max-height: clamp(48px, 22dvh, 190px);
}
.verif-qr { display: flex; flex-direction: column; align-items: center; gap: 0.8dvh; }
/* Etiqueta destacada bajo el QR. */
.verif-qr span {
  display: inline-block; background: #0757d4; color: #ffffff;
  font-weight: 800; letter-spacing: .02em; white-space: nowrap;
  font-size: clamp(13px, 2.9dvh, 20px); line-height: 1.15;
  padding: 0.6dvh 12px; border-radius: 999px;
  box-shadow: 0 2px 6px rgba(7, 87, 212, .25);
}
.verif-qr img {
  display: block; width: auto; height: auto; object-fit: contain;
  max-height: clamp(48px, 20dvh, 170px); background: #fff; padding: 4px; border-radius: 8px;
}
/* Pantallas horizontales bajas (verificadores): repartir la altura con dvh. */
@media (orientation: landscape) and (max-height: 820px) {
  [data-testid="stMainBlockContainer"], .block-container {
    padding-top: 1.2dvh !important; padding-bottom: 0 !important;
  }
  [data-testid="stVerticalBlock"] { gap: 2.4dvh !important; }
  .main-header {
    min-height: 0 !important; padding: 2.8dvh 40px !important;
    margin: 0 0 0.5dvh !important; border-radius: 14px !important;
  }
  .main-header h1 { font-size: clamp(18px, 6.6dvh, 46px) !important; }
  .main-header p { font-size: clamp(11px, 3dvh, 20px) !important; margin-top: 0.6dvh !important; }
  .animated-barcode-card {
    width: min(560px, 60vw) !important; margin: 0 auto !important;
    padding: 1.6dvh 18px 1dvh !important;
  }
  .animated-bars { height: clamp(40px, 19dvh, 160px) !important; }
  .animated-barcode-caption { font-size: clamp(11px, 2.3dvh, 16px) !important; margin-top: 0.8dvh !important; }
  .scan-title { font-size: clamp(17px, 6.2dvh, 42px) !important; margin: 0 !important; }
  .scan-hint { font-size: clamp(11px, 3dvh, 20px) !important; margin: 0.4dvh auto 0 !important; }
}
</style>"""

# Cada <style> debe empezar en SU PROPIA línea: si queda pegado a un </style>
# anterior, Markdown lo trata como texto y puede mostrar el CSS en pantalla.
CSS = re.sub(r"</style>\s*<style>", "</style>\n<style>", CSS)
st.markdown(CSS, unsafe_allow_html=True)



for key, default in (
    ("scan_n", 0),
    ("last_searched_barcode", ""),
    ("current_product", None),
    ("result_time", None),
    ("not_found", False),
    ("external_job", None),
    ("external_started", None),
    ("consult_error", None),
    ("source_snapshot", None),
):
    if key not in st.session_state:
        st.session_state[key] = default


def buscar_producto(clave):
    query = str(st.session_state.get(clave, "")).strip()
    # Cada lectura usa un cuadro NUEVO y vacío (otra clave). Si quedara el código
    # anterior, la siguiente lectura se pegaría detrás ("123"+"123") y no se encontraría.
    st.session_state.scan_n += 1
    if not query:
        return
    st.session_state.last_searched_barcode = query
    st.session_state.current_product = None
    st.session_state.not_found = False
    st.session_state.consult_error = None
    st.session_state.external_job = None
    st.session_state.result_time = None
    try:
        mode, source_id = active_source()
        if mode == "local":
            # Consulta directa por clave primaria: no descarga el inventario completo.
            from inventarios import find_barcode
            product = find_barcode(query)
            if product is None:
                st.session_state.not_found = True
            else:
                st.session_state.current_product = product
            st.session_state.result_time = time.monotonic()
        elif mode == "google":
            from google_oauth_source import config as google_config, catalog as google_catalog
            cfg = google_config()
            if not cfg or not cfg.get("file_id"):
                raise RuntimeError("Configura el archivo de Google desde Administración.")
            df = google_catalog(cfg["kind"], cfg["file_id"], cfg["sheet_name"] or "",
                                cfg["code_column"], cfg["name_column"], cfg["price_column"])
            hits = df[df["barcode"].astype(str).str.strip() == query].head(1)
            if hits.empty:
                st.session_state.not_found = True
            else:
                st.session_state.current_product = hits.iloc[0].to_dict()
            st.session_state.result_time = time.monotonic()
        else:
            rows = admin_api("POST", "external_price_jobs", payload={
                "configuration_id": source_id,
                "barcode": query,
                "status": "pending",
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
            })
            if not rows or not rows[0].get("id"):
                raise RuntimeError("No se pudo registrar la consulta externa")
            st.session_state.external_job = rows[0]["id"]
            st.session_state.external_started = time.monotonic()
    except Exception as exc:
        st.session_state.consult_error = (
            "No se pudo consultar la fuente seleccionada: " + str(exc)
        )
        st.session_state.result_time = time.monotonic()


def check_external_result():
    jid = st.session_state.external_job
    if not jid:
        return
    if time.monotonic() - st.session_state.external_started > 25:
        st.session_state.external_job = None
        st.session_state.consult_error = (
            "La base externa no respondió a tiempo. No se consultó la base local."
        )
        st.session_state.result_time = time.monotonic()
        return
    try:
        rows = admin_api("GET", "external_price_jobs",
                         params={"id": "eq." + jid, "select": "status,result,error_message"})
        if not rows:
            raise RuntimeError("La solicitud externa no existe.")
        job = rows[0]
        if job["status"] == "done":
            result = job.get("result")
            if result:
                st.session_state.current_product = {
                    "barcode": result.get("barcode") or st.session_state.get("last_searched_barcode", ""),
                    "name": result.get("name", ""),
                    "price": result.get("price", 0),
                }
            else:
                st.session_state.not_found = True
            st.session_state.external_job = None
            st.session_state.result_time = time.monotonic()
        elif job["status"] == "error":
            st.session_state.external_job = None
            st.session_state.consult_error = (
                "No se pudo consultar SQL Server. Revisa el conector y la conexión externa."
            )
            st.session_state.result_time = time.monotonic()
    except (requests.RequestException, RuntimeError) as exc:
        st.session_state.external_job = None
        st.session_state.consult_error = "No se pudo obtener la respuesta de la base externa."
        st.session_state.result_time = time.monotonic()


@st.fragment(run_every=1.0)
def verificador():
    # Evitar mostrar resultados de una fuente distinta si el administrador la cambia.
    try:
        mode, source_id = active_source()
        snapshot = (mode, source_id)
        if st.session_state.source_snapshot != snapshot:
            st.session_state.source_snapshot = snapshot
            st.session_state.current_product = None
            st.session_state.not_found = False
            st.session_state.external_job = None
            st.session_state.result_time = None
            st.session_state.consult_error = None
            st.session_state.last_searched_barcode = ""
    except Exception:
        st.error("No se pudo leer la fuente activa. Revisa Configuración.")
        return

    if mode == "external":
        check_external_result()
    started = st.session_state.result_time

    # Los códigos inexistentes vuelven antes al lector; los productos encontrados
    # conservan el tiempo habitual para leer el precio.
    display_seconds = 7 if st.session_state.not_found else 10
    if started is not None and time.monotonic() - started >= display_seconds:
        st.session_state.current_product = None
        st.session_state.not_found = False
        st.session_state.consult_error = None
        st.session_state.result_time = None
        # El widget puede no existir cuando se muestra un resultado.
        # Streamlit limpia automaticamente su estado al ocultarlo.

    # Mantener el textbox nativo montado en TODOS los estados, incluso mientras
    # se muestra un producto o un código inexistente. Al desmontarlo, Streamlit
    # pierde el foco y puede descartar la siguiente lectura del escáner.
    try:
        from apariencia import obtener as obtener_apariencia
        vista = obtener_apariencia()
    except Exception:
        vista = {"mostrar_logo": True, "mostrar_qr": True, "mostrar_cuadro": False}
    st.markdown(CSS_CUADRO_VISIBLE if vista["mostrar_cuadro"] else CSS_CUADRO_OCULTO,
                unsafe_allow_html=True)

    clave_cuadro = f"search_input_{st.session_state.scan_n}"
    # Contenedor con clave fija: el script de enfoque lo localiza siempre.
    with st.container(key="cuadro_codigo"):
        st.text_input(
            "Código de barras",
            key=clave_cuadro,
            on_change=buscar_producto,
            args=(clave_cuadro,),
            label_visibility="collapsed",
            placeholder="Escanea o escribe el código y pulsa Enter",
        )

    product = st.session_state.current_product

    if product is not None:
        name = html.escape(str(product["name"]))
        barcode = html.escape(str(product["barcode"]))
        price = float(product["price"])

        st.markdown(
            '<div class="resultado-pantalla">'
            '<div class="resultado-datos">'
            '<div class="resultado-etiqueta">PRODUCTO</div>'
            f'<div class="resultado-nombre">{name}</div>'
            f'<div class="resultado-codigo">Código: {barcode}</div>'
            '</div>'
            '<div class="resultado-precio-panel">'
            '<div class="resultado-precio-etiqueta">PRECIO DE VENTA</div>'
            f'<div class="resultado-precio">RD$ {price:,.2f}</div>'
            '</div></div>', 
            unsafe_allow_html=True,
        )

    elif st.session_state.consult_error:
        st.error(st.session_state.consult_error)
    elif st.session_state.external_job:
        # Solo se muestra una animación amigable; no exponer detalles técnicos.
        st.markdown(
            '<div class="product-card search-card">'
            '<div class="search-label">VERIFICANDO PRECIO</div>'
            '<svg class="search-visual" viewBox="0 0 300 105" role="img" '
            'aria-label="Lupa buscando un código de barras">'
            '<g fill="#64748b">'
            + ''.join(
                f'<rect x="{15 + i * 9}" y="22" width="{4 if i % 3 == 0 else 2}" '
                f'height="{55 if i % 4 == 0 else 45}" />' for i in range(27)
            )
            + '</g><g class="search-lens">'
            '<circle cx="36" cy="42" r="23" fill="#e8f1ff" fill-opacity="0.9" '
            'stroke="#0759c9" stroke-width="5"/>'
            '<path d="M53 59 L78 84" stroke="#0759c9" stroke-width="9" '
            'stroke-linecap="round"/></g></svg>'
            '<div class="search-text">Buscando producto...</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="main-header">'
            '<h1>🏷️ CONSULTA DE PRECIOS</h1>'
            '<p>Consulta rápida de productos y precios</p>'
            '</div>',
            unsafe_allow_html=True,
        )

        # Codigo de barras animado: solo decorativo, no altera la lectura real.
        # Estado de error: barras rojas inmóviles, sin línea de escaneo.
        # Estado normal: conserva la animación original.
        clase_error = " barcode-not-found" if st.session_state.not_found else ""
        st.markdown(f"""
        <div class="animated-barcode-card{clase_error}" aria-label="Código de barras decorativo">
          <div class="animated-bars"><div class="animated-scan-line"></div></div>
          <div class="animated-barcode-caption">PRECIO &nbsp;•&nbsp; RD$</div>
        </div>
        """, unsafe_allow_html=True)

        # Conservar exactamente la misma pantalla de espera si no se encuentra
        # el producto; solo cambia el mensaje principal durante 3 segundos.
        titulo_escaneo = (
            "PRODUCTO NO ENCONTRADO"
            if st.session_state.not_found
            else "ESCANEA TU CÓDIGO AQUÍ"
        )
        st.markdown(
            f'<div class="scan-title{" scan-title-not-found" if st.session_state.not_found else ""}">{titulo_escaneo}</div>'
            + ('' if st.session_state.not_found else
               '<div class="scan-hint">El precio se mostrará automáticamente</div>'),
            unsafe_allow_html=True,
        )


        # Logo y QR según Apariencia, centrados respecto a TODA la pantalla.
        imagenes = []
        if vista["mostrar_logo"]:
            logo = imagen_base64("logo.png", 440, 260)
            if logo:
                imagenes.append(
                    '<img class="verif-logo" alt="Logo de la empresa" '
                    f'src="data:image/png;base64,{logo}">')
        if vista["mostrar_qr"]:
            qr = imagen_base64("qr-movil.png", 300, 300)
            if qr:
                imagenes.append(
                    '<div class="verif-qr"><img alt="Código QR para consultar desde el celular" '
                    f'src="data:image/png;base64,{qr}"><span>📱 Consulta desde tu celular</span></div>')
        if imagenes:
            st.markdown('<div class="verif-imagenes">' + "".join(imagenes) + '</div>',
                        unsafe_allow_html=True)



# Script del cursor: se instala UNA vez en la página principal (fuera del
# fragmento que se actualiza cada segundo) y desde ahí vigila el cuadro.
from shared import ejecutar_js_en_pagina
ejecutar_js_en_pagina(FOCO_JS, "foco_verificador_js")

try:
    verificador()
except Exception:
    st.error("No se pudo iniciar la consulta de precios. Revisa la conexión y la fuente seleccionada.")
