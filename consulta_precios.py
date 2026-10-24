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
from registro_consultas import registrar
from supabase_cliente import cabeceras, clave_servidor, clave_publica

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
SUPABASE_ANON_KEY = clave_publica()

SUPABASE_SERVICE_ROLE_KEY = clave_servidor()

def admin_api(method, table, params=None, payload=None):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Falta SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY) en Secrets.")
    headers = {
        **cabeceras(SUPABASE_SERVICE_ROLE_KEY),
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
                **cabeceras(SUPABASE_SERVICE_ROLE_KEY),
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


# Diseño de la pantalla: el mismo de los equipos sin internet (pantalla_en_linea.py).
import pantalla_en_linea

CSS = """
<style>
.block-container { max-width: 100%; padding: .5rem .8rem .8rem; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
/* Elementos que solo llevan estilos o scripts: no ocupan espacio. */
[data-testid="stElementContainer"]:has([data-testid="stMarkdownContainer"]):not(:has([data-testid="stMarkdownContainer"] > :not(style))) {
  display: none !important;
}
[data-testid="stElementContainer"]:has(.vp),
[data-testid="stElementContainer"]:has(.vp) [data-testid="stMarkdown"],
[data-testid="stElementContainer"]:has(.vp) [data-testid="stMarkdownContainer"] { margin: 0 !important; }
div[data-testid="stTextInput"] input:focus,
div[data-testid="stTextInput"] input:focus-visible {
    outline: none !important;
    border-color: #16823c !important;
    box-shadow: 0 0 0 3px #d9f5df !important;
}
</style>
""" + pantalla_en_linea.CSS

# El textbox sigue en el DOM y recibe el foco y los codigos del escaner.
# Se oculta solo visualmente: NO usar display:none ni visibility:hidden.
# Se aplica o no según Apariencia (ver verificador()).
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

# Cuadro visible: flota abajo al centro, encima de la pantalla. Sigue recibiendo el foco igual.
CSS_CUADRO_VISIBLE = """
<style>
.st-key-cuadro_codigo {
    position: fixed !important; z-index: 1000 !important;
    left: 50% !important; transform: translateX(-50%) !important;
    bottom: clamp(8px, 2dvh, 20px) !important; top: auto !important;
    width: min(420px, 50vw) !important;
}
div[data-testid="stTextInput"] { max-width: 460px !important; margin: 0 auto !important; }
div[data-testid="stTextInput"] input { text-align: center !important; font-size: 20px !important; letter-spacing: 1px; }
</style>
"""

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


def _sucursal_actual():
    """Sucursal de esta pantalla (la del usuario o la detectada por ubicación), o None."""
    codigo = st.session_state.get("sucursal_codigo")
    if not codigo:
        return None
    try:
        import sucursales
        return sucursales.por_codigo(codigo)
    except Exception:
        return None


def _con_sucursal(producto, codigo):
    """La sucursal ya consulta su propia fuente (ver _fuente_consulta): el producto queda igual."""
    return producto


def _fuente_consulta():
    """(modo, id de la configuración de SQL Server, id de inventario, config de Google) para esta pantalla.
    La Principal usa la fuente activa; una sucursal, la fuente que eligió en Sucursales."""
    mode, source_id = active_source()
    suc = _sucursal_actual()
    if not suc:
        return mode, source_id, None, None
    import sucursales
    f = sucursales.fuente(suc)
    if f["tipo"] == "inventario":
        return "local", None, f["inventario_id"], None
    if f["tipo"] == "google":
        return "google", None, None, f["google"]
    if f["tipo"] == "external":
        return "external", f["external_id"], None, None
    return mode, source_id, None, None


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
        mode, source_id, inventario_id, google_suc = _fuente_consulta()
        if mode == "local":
            # Consulta directa por clave primaria: no descarga el inventario completo.
            from inventarios import find_barcode
            product = _con_sucursal(find_barcode(query, inventario_id), query)
            if product is None:
                st.session_state.not_found = True
            else:
                st.session_state.current_product = product
            st.session_state.result_time = time.monotonic()
            registrar(query, product is not None, product, "local", "verificador",
                      st.session_state.get("sucursal_codigo"))
        elif mode == "google":
            from google_oauth_source import config as google_config, catalog as google_catalog
            cfg = google_suc or google_config()
            if not cfg or not cfg.get("file_id"):
                raise RuntimeError("Configura el archivo de Google desde Administración.")
            df = google_catalog(cfg["kind"], cfg["file_id"], cfg["sheet_name"] or "",
                                cfg["code_column"], cfg["name_column"], cfg["price_column"])
            from shared import variantes_codigo
            formas = variantes_codigo(query)
            codigos = df["barcode"].astype(str).str.strip()
            hits = df[codigos.isin(formas)]
            if not hits.empty:   # la forma más parecida a la leída primero
                hits = hits.assign(_orden=codigos[hits.index].map(formas.index)).sort_values("_orden").head(1)
            producto = _con_sucursal(None if hits.empty else hits.iloc[0].to_dict(), query)
            if producto is None:
                st.session_state.not_found = True
            else:
                st.session_state.current_product = producto
            st.session_state.result_time = time.monotonic()
            registrar(query, producto is not None, producto, "google", "verificador",
                      st.session_state.get("sucursal_codigo"))
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
            buscado = st.session_state.get("last_searched_barcode", "")
            producto = None
            if result:
                producto = {
                    "barcode": result.get("barcode") or buscado,
                    "name": result.get("name", ""),
                    "price": result.get("price", 0),
                }
            producto = _con_sucursal(producto, buscado)
            if producto:
                st.session_state.current_product = producto
            else:
                st.session_state.not_found = True
            st.session_state.external_job = None
            st.session_state.result_time = time.monotonic()
            registrar(st.session_state.get("last_searched_barcode", ""), producto is not None,
                      st.session_state.current_product, "external", "verificador",
                      st.session_state.get("sucursal_codigo"))
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
    # app.py indica si la sesión es la cuenta del verificador (kiosko).
    modo_kiosko = bool(st.session_state.get("modo_kiosko", False))
    try:
        from apariencia import obtener as obtener_apariencia
        vista = obtener_apariencia()
    except Exception:
        vista = _apariencia_predeterminada()
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
    a = vista if "estilo" in vista else {**_apariencia_predeterminada(), **vista}
    logo = imagen_base64("logo.png", 700, 420) if a["mostrar_logo"] else None
    qr = imagen_base64("qr-movil.png", 300, 300) if a["mostrar_qr"] else None
    logo = f"data:image/png;base64,{logo}" if logo else None
    qr = f"data:image/png;base64,{qr}" if qr else None
    codigo = str(st.session_state.get("last_searched_barcode") or "")
    _suc = _sucursal_actual()
    comun = {"logo": logo, "qr": qr, "codigo": codigo, "fija": modo_kiosko,
             "sucursal": _suc["nombre"] if _suc else None}

    if product is not None:
        # La foto se decide UNA vez, al aparecer el precio: si no había, esta consulta sigue sin foto
        # (no aparece a mitad de camino). La que se encuentre en segundo plano sale en la próxima.
        consulta = (st.session_state.result_time, codigo)
        if st.session_state.get("foto_consulta") != consulta:
            st.session_state.foto_consulta = consulta
            st.session_state.foto_actual = (foto_producto(codigo, str(product.get("barcode") or ""))
                                            if a.get("mostrar_foto", True) else None)
        foto = st.session_state.foto_actual
        html_pantalla = pantalla_en_linea.pantalla(a, "producto", producto=product, foto=foto, **comun)
    elif st.session_state.consult_error:
        html_pantalla = pantalla_en_linea.pantalla(a, "error", **comun)
        if not modo_kiosko:   # el detalle técnico solo lo ve el personal
            st.error(st.session_state.consult_error)
    elif st.session_state.external_job:
        html_pantalla = pantalla_en_linea.pantalla(a, "buscando", **comun)
    else:
        html_pantalla = pantalla_en_linea.pantalla(a, "no" if st.session_state.not_found else "espera", **comun)
    st.markdown(html_pantalla, unsafe_allow_html=True)


def _apariencia_predeterminada():
    try:
        from apariencia import PREDETERMINADA
        return dict(PREDETERMINADA)
    except Exception:
        return {"nombre_negocio": "", "mostrar_nombre": True, "estilo": "claro", "color_marca": "#0757d4",
                "posicion_logo": "esquina", "titulo_espera": "Escanea tu producto",
                "mensaje_espera": "Pasa el código de barras por el lector",
                "texto_qr": "Consulta también desde tu celular", "moneda": "RD$",
                "mostrar_logo": True, "mostrar_qr": True, "mostrar_cuadro": False, "mostrar_foto": True}


_FOTOS = {}   # (códigos) -> (hora, foto): solo las que existen


def foto_producto(*codigos):
    """Foto YA guardada del producto (a mano o de internet) como data: URL, o None.
    Si no hay, no se espera ni se avisa nada: la búsqueda en internet corre aparte
    (registro_consultas) y la foto aparecerá desde la siguiente consulta."""
    clave = tuple(codigos)
    guardada = _FOTOS.get(clave)
    if guardada and time.monotonic() - guardada[0] < 600:
        return guardada[1]
    foto = _buscar_foto(*codigos)
    if foto:
        if len(_FOTOS) > 300:
            _FOTOS.clear()
        _FOTOS[clave] = (time.monotonic(), foto)
    return foto


def _buscar_foto(*codigos):
    try:
        import fotos_productos as fp
        from codigos_barras import variantes_codigo
        base, headers = fp._conexion()
        formas = []
        for c in codigos:
            if c:
                formas += [f for f in variantes_codigo(c) if f not in formas]
        for forma in formas[:6]:
            for ruta, tipo in ((f"{fp.BUCKET}/{forma}.png", "image/png"),
                               (f"{fp.BUCKET}/{fp.CARPETA_INTERNET}/{forma}.jpg", "image/jpeg")):
                datos = fp._leer(base, headers, ruta)
                if datos:
                    return f"data:{tipo};base64," + base64.b64encode(datos).decode("ascii")
    except Exception:
        pass
    return None



# Script del cursor: se instala UNA vez en la página principal (fuera del
# fragmento que se actualiza cada segundo) y desde ahí vigila el cuadro.
from shared import ejecutar_js_en_pagina
ejecutar_js_en_pagina(FOCO_JS, "foco_verificador_js")
ejecutar_js_en_pagina(pantalla_en_linea.AJUSTE_JS, "ajuste_precio_js")

try:
    verificador()
except Exception:
    st.error("No se pudo iniciar la consulta de precios. Revisa la conexión y la fuente seleccionada.")
