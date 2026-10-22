"""Navegación con inicio de sesión obligatorio, incluso para consultar precios."""
import inspect
import time
import json
import hmac
import hashlib
import base64
import requests
import streamlit as st
from streamlit_cookies_controller import CookieController
from auth_usuarios import (allowed, bootstrap, cambiar_password, current_user,
                           es_admin, es_kiosko, intentar_login)

st.set_page_config(
    page_title="Consulta de Precios",
    page_icon="🏷️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Acceso público exclusivo a Consulta Móvil, por ruta directa o enlace antiguo.
# Se ejecuta ANTES del inicio de sesión y de cualquier navegación privada.
# La página móvil realiza su propia comprobación geográfica antes de consultar.
from urllib.parse import urlsplit

try:
    _ruta_actual = urlsplit(st.context.url).path.rstrip("/").lower()
except (AttributeError, TypeError, ValueError):
    _ruta_actual = ""

_escaner_publico = (
    _ruta_actual == "/escaner_movil"
    or str(st.query_params.get("movil", "")) == "1"
)
if _escaner_publico:
    st.session_state["mobile_public_access"] = True
    pagina_publica = st.Page(
        "pages/8_Escaner_Movil.py",
        title="Consulta Móvil",
        icon="📱",
        url_path="Escaner_Movil",
        default=True,
    )
    st.navigation([pagina_publica], position="hidden").run()
    st.stop()
st.session_state["mobile_public_access"] = False

try:
    bootstrap()
except Exception as exc:
    st.error("No se pudo inicializar el sistema de usuarios: " + str(exc))
    st.stop()

# Sesión persistente y cifrada en una cookie del navegador.
# No se guardan contraseñas en el navegador.
_cookie_secret = str(st.secrets.get("SESSION_COOKIE_KEY", "")).strip()
if not _cookie_secret:
    st.error("Falta SESSION_COOKIE_KEY en Streamlit Secrets para activar las sesiones persistentes.")
    st.stop()
cookies = CookieController()

COOKIE_NAME = "consulta_precios_login_v2"
# La sesión dura hasta que el usuario pulse "Cerrar sesión". La cookie se
# renueva en cada visita, así que un equipo en uso nunca llega a vencer.
COOKIE_SECONDS = 60 * 60 * 24 * 365

def _token(usuario):
    # Vencimiento redondeado al día: el token no cambia en cada recarga.
    vence = (int(time.time()) // 86400) * 86400 + COOKIE_SECONDS
    payload = {"id": str(usuario["id"]), "exp": vence,
               "v": hashlib.sha256(usuario["password_hash"].encode()).hexdigest()[:24]}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_cookie_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return body + "." + sig

def _recover(token):
    """Devuelve (estado, id). estado: 'ok', 'invalida' (borrar cookie) o
    'temporal' (Supabase no respondió: conservar la cookie y reintentar)."""
    try:
        body, sig = token.rsplit(".", 1)
        correct = hmac.new(_cookie_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, correct):
            return "invalida", None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if int(payload["exp"]) <= time.time():
            return "invalida", None
    except (ValueError, KeyError, TypeError, OverflowError):
        return "invalida", None
    try:
        from auth_usuarios import api
        rows = api("GET", {"id": "eq." + str(payload["id"]), "select": "id,username,password_hash,active,role", "limit": 1})
    except (RuntimeError, requests.RequestException):
        # Fallo de red o de Supabase: NO cerrar la sesión por esto.
        return "temporal", None
    try:
        # Cuenta eliminada, desactivada o con contraseña cambiada: sesión inválida.
        if not rows or not rows[0]["active"]:
            return "invalida", None
        version = hashlib.sha256(rows[0]["password_hash"].encode()).hexdigest()[:24]
        if not hmac.compare_digest(payload["v"], version):
            return "invalida", None
        return "ok", rows[0]["id"]
    except (ValueError, KeyError, TypeError):
        return "invalida", None

# Procesar el retorno OAuth en la raíz ANTES del login y de st.navigation.
# El regreso desde accounts.google.com crea una sesión nueva de Streamlit:
# st.session_state NO es una ubicación fiable para retener el código OAuth.
# La autorización solo puede haberse iniciado desde la página administrativa,
# que genera un state firmado con caducidad (verify_state).
if "code" in st.query_params or "error" in st.query_params:
    _oauth_code = str(st.query_params.get("code", ""))
    _oauth_state = str(st.query_params.get("state", ""))
    _oauth_error = str(st.query_params.get("error", ""))
    try:
        from google_oauth_source import verify_state, exchange_code, connect
        if _oauth_error:
            raise RuntimeError("Google rechazó la autorización: " + _oauth_error)
        if not _oauth_code or not verify_state(_oauth_state):
            raise RuntimeError("Autorización inválida o vencida. Inicia nuevamente desde Administración.")
        # No depende del login de Streamlit. El state firmado fue emitido
        # únicamente desde la página administrativa protegida.
        connect(exchange_code(_oauth_code))
        st.session_state["google_oauth_notice"] = (
            "success", "Cuenta de Google conectada correctamente. Inicia sesión como administrador para continuar."
        )
    except Exception as exc:
        st.session_state["google_oauth_notice"] = (
            "error", "No se pudo completar la conexión Google: " + str(exc)
        )
    finally:
        # Limpiar el código de un solo uso después de intentar el canje.
        for _key in ("code", "state", "scope", "authuser", "prompt", "error", "iss"):
            if _key in st.query_params:
                del st.query_params[_key]

# La X solicita autorización; nunca cierra sesión sin contraseña de admin.
solicitar_salida = str(st.query_params.get("salir", "")) == "1"

st.session_state.setdefault("usuario_id", None)
# Impide que una cookie antigua reactive la sesión inmediatamente después de salir.
st.session_state.setdefault("logout_pendiente", False)
st.session_state.setdefault("autorizar_salida_consulta", False)
st.session_state.setdefault("fallos_login", 0)
st.session_state.setdefault("bloqueo_hasta", 0.0)


def _leer_cookie():
    """Lee la cookie de sesión. st.context.cookies la entrega AL INSTANTE al
    abrir la página; CookieController queda como respaldo (llega con retraso)."""
    try:
        valor = st.context.cookies.get(COOKIE_NAME)
        if valor:
            return valor
    except Exception:
        pass
    try:
        return cookies.get(COOKIE_NAME)
    except Exception:
        return None


def _escribir_cookie(valor, max_age):
    """Escribe (o borra con max_age=0) la cookie con JavaScript en la página
    principal. Se repite en cada carga completa, así nunca queda sin guardar."""
    from shared import ejecutar_js_en_pagina
    js = ("(function(){var c=%s+'='+%s+'; Max-Age=%d; Path=/; SameSite=Lax';"
          "if(location.protocol==='https:')c+='; Secure';document.cookie=c;})();"
          % (json.dumps(COOKIE_NAME), json.dumps(valor), int(max_age)))
    ejecutar_js_en_pagina(js, "sesion_cookie_js")


# Recuperar sesión al refrescar la página o reabrir el navegador.
if not st.session_state.usuario_id and not st.session_state.logout_pendiente:
    token = _leer_cookie()
    if token:
        estado, restored_id = _recover(token)
        if estado == "ok":
            st.session_state.usuario_id = restored_id
        elif estado == "invalida":
            _escribir_cookie("", 0)
        # estado "temporal": se conserva la cookie y se reintenta abajo.

# CookieController recibe las cookies del navegador de forma asíncrona.
# En una sesión nueva, el primer get() puede devolver None antes de que
# el componente termine de inicializarse. Reintentar sin pedir credenciales.
if not st.session_state.usuario_id and not st.session_state.logout_pendiente:
    @st.fragment(run_every="1s")
    def _esperar_cookie_recordada():
        if st.session_state.get("usuario_id"):
            return
        token_persistente = cookies.get(COOKIE_NAME)
        if token_persistente:
            estado, identificador = _recover(token_persistente)
            if estado == "ok":
                st.session_state.usuario_id = identificador
                st.rerun(scope="app")
            elif estado == "invalida":
                try:
                    cookies.remove(COOKIE_NAME)
                except Exception:
                    pass
            else:
                # Se reintenta cada segundo hasta que Supabase responda.
                st.info("Reconectando con el servidor… tu sesión sigue abierta.")
    _esperar_cookie_recordada()

try:
    user = current_user()
except (RuntimeError, requests.RequestException):
    # Supabase no respondió: no cerrar la sesión; reintentar en unos segundos.
    st.warning("Sin conexión con el servidor. Reintentando… tu sesión sigue abierta.")
    time.sleep(3)
    st.rerun()

if user:
    # Sesión abierta: (re)escribir la cookie en cada carga. Así se guarda aunque
    # una carga anterior se haya interrumpido, y su vencimiento se renueva.
    _escribir_cookie(_token(user), COOKIE_SECONDS)
elif st.session_state.logout_pendiente:
    # Sesión cerrada con el botón: borrar la cookie mientras se muestra el login.
    _escribir_cookie("", 0)
    try:
        cookies.remove(COOKIE_NAME)
    except Exception:
        pass
if not user:
    _oauth_login_notice = st.session_state.get("google_oauth_notice")
    if _oauth_login_notice:
        if _oauth_login_notice[0] == "success":
            st.success(_oauth_login_notice[1])
        else:
            st.error(_oauth_login_notice[1])
    st.markdown("""
    <style>
      .stApp { background: radial-gradient(ellipse at 4% 92%, #dce8ff 0%, transparent 46%),
                radial-gradient(ellipse at 98% 0%, #e9f1ff 0%, transparent 40%), #f7faff; }
      [data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none !important; }
      .block-container { max-width: 1100px; padding-top: clamp(35px, 9vh, 115px); }
      .login-head { text-align:center; padding: 20px 10px 15px; width:100%; margin:0 auto; }
      .login-icon { display:inline-flex; align-items:center; justify-content:center;
          width:70px; height:70px; border-radius:20px; background:#eaf1ff;
          font-size:36px; margin-bottom:14px; }
      .login-title { font-weight:800; font-size:clamp(18px, 3.1vw, 40px); color:#172f56;
          margin:0 0 8px; line-height:1.2; white-space:nowrap; letter-spacing:-.5px; }
      .login-subtitle { color:#71809a; font-size:15px; margin:10px 0 8px; }
      [data-testid="stForm"] { background:white; border:1px solid #e3eaf6;
          border-radius:22px; padding:22px 28px 30px;
          box-shadow:0 16px 45px rgba(27, 57, 112, .11); }
      /* Colores explícitos: Safari iOS y temas oscuros de Streamlit */
      [data-testid="stForm"] [data-testid="stTextInput"] input {
          background:#f9fbff !important; color:#172f56 !important;
          -webkit-text-fill-color:#172f56 !important;
          caret-color:#172f56 !important; border-radius:11px; min-height:46px;
          font-size:16px !important; color-scheme:light;
      }
      [data-testid="stForm"] [data-testid="stTextInput"] input::placeholder {
          color:#65758d !important; -webkit-text-fill-color:#65758d !important; opacity:1 !important;
      }
      [data-testid="stForm"] [data-testid="stWidgetLabel"],
      [data-testid="stForm"] [data-testid="stWidgetLabel"] p,
      [data-testid="stForm"] label,
      [data-testid="stForm"] [data-testid="stCheckbox"] p,
      [data-testid="stForm"] [data-testid="stCheckbox"] label {
          color:#172f56 !important;
      }
      [data-testid="stForm"] [data-testid="stTextInput"] input:focus {
          border-color:#2563eb !important;
      }
      [data-testid="stForm"] button[kind="secondaryFormSubmit"] {
          background:linear-gradient(105deg,#1679ee,#265cf1); color:white;
          border:0; border-radius:11px; min-height:48px; font-weight:700;
          box-shadow:0 5px 15px rgba(24,102,232,.20); }
      [data-testid="stForm"] button[kind="secondaryFormSubmit"]:hover {
          color:white; background:#165cda; }
      @media (max-width:600px) {
          .block-container { padding:24px 12px 20px; }
          [data-testid="stForm"] { padding:16px 18px 22px; }
          .login-icon { width:60px; height:60px; font-size:30px; }
          .login-title { font-size:clamp(13px, 3.4vw, 20px); letter-spacing:-.6px; }
      }
    </style>
    """, unsafe_allow_html=True)
    # Encabezado a todo el ancho para centrar el título sin saltos de línea.
    st.markdown("""
    <div class="login-head">
      <div class="login-icon">🔐</div>
      <h1 class="login-title">Sistema de Consulta de Precios</h1>
      <p class="login-subtitle">Inicia sesión para acceder al sistema</p>
    </div>
    """, unsafe_allow_html=True)
    _, centro, _ = st.columns([1, 1.05, 1], gap="small")
    with centro:
        with st.form("inicio_sesion"):
            nombre = st.text_input("👤 Usuario", placeholder="Ingresa tu usuario")
            clave = st.text_input("🔒 Contraseña", type="password", placeholder="Ingresa tu contraseña")
            st.caption("La sesión queda abierta en este equipo hasta que pulses "
                       "«Cerrar sesión». No se guarda la contraseña.")
            entrar = st.form_submit_button("➜  Iniciar sesión", use_container_width=True)
        if entrar:
            # Límite por sesión (cubre usuarios inexistentes). El bloqueo
            # por cuenta se guarda en Supabase dentro de intentar_login().
            if time.monotonic() < st.session_state.bloqueo_hasta:
                st.error("Demasiados intentos. Espera 5 minutos.")
            else:
                mensaje = ""
                try:
                    cuenta, mensaje = intentar_login(nombre, clave)
                except RuntimeError as exc:
                    st.error(str(exc))
                    cuenta = None
                valido = cuenta is not None
                if valido:
                    st.session_state.usuario_id = cuenta["id"]
                    st.session_state.logout_pendiente = False
                    st.session_state.fallos_login = 0
                    st.session_state.logout_pendiente = False
                    if "salir" in st.query_params:
                        del st.query_params["salir"]
                    # El acceso ya está validado: mostrar Consulta de Precios
                    # inmediatamente. No bloquear la página esperando la cookie.
                    st.rerun()
                else:
                    st.session_state.fallos_login += 1
                    if st.session_state.fallos_login >= 5:
                        st.session_state.bloqueo_hasta = time.monotonic() + 300
                        st.session_state.fallos_login = 0
                    if mensaje:
                        st.error(mensaje)
    st.stop()

def _cerrar_sesion():
    # Bloquear recuperación desde la cookie durante el cambio a login.
    st.session_state.logout_pendiente = True
    st.session_state.autorizar_salida_consulta = False
    st.session_state.usuario_id = None
    for permiso_temporal in ("admin_authenticated", "fuentes_admin_ok", "external_admin_ok"):
        st.session_state[permiso_temporal] = False
    # La cookie se borra en la siguiente carga (logout_pendiente).
    st.rerun()

# La X de consulta exige la contraseña de la cuenta administradora.
# No cerrar ni invalidar la sesión hasta validar la clave en el servidor.
if (solicitar_salida or st.session_state.autorizar_salida_consulta) and es_kiosko(user):
    # Temporizador en el servidor: no depende de que el navegador ejecute JavaScript.
    if "inicio_autorizacion_admin" not in st.session_state:
        st.session_state.inicio_autorizacion_admin = time.monotonic()

    @st.fragment(run_every="1s")
    def pantalla_autorizacion_admin():
        st.markdown("""
        <style>
          [data-testid="stSidebar"], [data-testid="collapsedControl"],
          [data-testid="stSidebarCollapsedControl"] {display:none!important;}
          .block-container {max-width:580px!important; padding-top:clamp(50px,12vh,130px)!important;}
        </style>
        """, unsafe_allow_html=True)

        # Campo fuera del formulario para detectar si el usuario comienza a escribir.
        nombre_admin = str(st.session_state.get("salida_usuario_admin", "")).strip()
        transcurridos = time.monotonic() - st.session_state.inicio_autorizacion_admin
        if not nombre_admin and transcurridos >= 10:
            st.session_state.autorizar_salida_consulta = False
            st.session_state.pop("inicio_autorizacion_admin", None)
            if "salir" in st.query_params:
                del st.query_params["salir"]
            st.rerun(scope="app")

        st.title("🔐 Autorizar salida")
        st.info("Para cerrar cualquiera de los verificadores, introduce el usuario y la contraseña del administrador.")
        st.text_input("Usuario administrador", key="salida_usuario_admin")
        if not nombre_admin:
            st.caption(f"Regreso automático a Consulta de Precios en {max(0, 10 - int(transcurridos))} segundos si no escribe el usuario.")
        with st.form("formulario_credenciales_admin_para_salir", clear_on_submit=False):
            clave_administrador = st.text_input("Contraseña del administrador", type="password", key="salida_clave_admin")
            confirmar_salida = st.form_submit_button("Confirmar salida", use_container_width=True)
            iniciar_admin = st.form_submit_button("Iniciar sesión como administrador", use_container_width=True)
        if confirmar_salida or iniciar_admin:
            try:
                # Cualquier cuenta con rol administrador; aplica el mismo bloqueo por intentos.
                administrador, _ = intentar_login(nombre_admin, clave_administrador)
                valido_admin = es_admin(administrador)
            except (RuntimeError, ValueError, TypeError, KeyError):
                administrador = None
                valido_admin = False
            if valido_admin:
                st.session_state.pop("inicio_autorizacion_admin", None)
                st.session_state.autorizar_salida_consulta = False
                st.session_state.pop("salida_usuario_admin", None)
                st.session_state.pop("salida_clave_admin", None)
                if "salir" in st.query_params:
                    del st.query_params["salir"]
                if iniciar_admin:
                    # Cambiar la sesión actual por la del administrador.
                    st.session_state.usuario_id = administrador["id"]
                    st.session_state.logout_pendiente = False
                    st.rerun(scope="app")
                else:
                    _cerrar_sesion()
            else:
                st.error("Usuario o contraseña del administrador incorrectos. La sesión no ha cambiado.")
        if st.button("Cancelar y volver al verificador", key="cancelar_salida_consulta"):
            st.session_state.autorizar_salida_consulta = False
            st.session_state.pop("inicio_autorizacion_admin", None)
            if "salir" in st.query_params:
                del st.query_params["salir"]
            st.rerun(scope="app")

    pantalla_autorizacion_admin()
    st.stop()

# La autenticación principal del administrador también autoriza los módulos
# antiguos que antes pedían una segunda contraseña por separado.
# Se recalcula en cada ejecución: nunca heredar permisos de otro usuario.
es_administrador_autenticado = es_admin(user) and not user["must_change_password"]
st.session_state["admin_authenticated"] = es_administrador_autenticado
st.session_state["fuentes_admin_ok"] = allowed(user, "fuentes")
st.session_state["external_admin_ok"] = allowed(user, "fuentes")

# La cuenta exclusiva de consulta no necesita navegación lateral.
es_solo_consulta = es_kiosko(user)
if not es_solo_consulta:
    with st.sidebar:
        st.caption("Sesión: " + user["username"])
        # Usuarios normales y administradores salen directamente; solo la
        # cuenta kiosko (sin barra lateral) exige la clave del administrador.
        if st.button("🚪 Cerrar sesión", key="sidebar_logout"):
            _cerrar_sesion()

if user and user["must_change_password"]:
    st.title("Cambio obligatorio de contraseña")
    st.warning("Debes cambiar la contraseña inicial antes de entrar a Configuración.")
    with st.form("cambio_inicial"):
        a = st.text_input("Nueva contraseña", type="password")
        b = st.text_input("Repetir contraseña", type="password")
        guardar = st.form_submit_button("Cambiar contraseña")
    if guardar:
        if a != b:
            st.error("Las contraseñas no coinciden.")
        elif a.strip().lower() in ("admin", str(user["username"]).strip().lower()):
            st.error("La contraseña no puede ser 'admin' ni igual a tu usuario.")
        else:
            try:
                cambiar_password(user, a)
                # La contraseña cambió: la cookie anterior deja de valer; emitir una nueva.
                st.success("Contraseña cambiada.")
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
    st.stop()

# Mostrar el resultado al administrador al terminar de iniciar sesión.
_oauth_notice = st.session_state.pop("google_oauth_notice", None)
if _oauth_notice:
    if _oauth_notice[0] == "success":
        st.success(_oauth_notice[1])
    else:
        st.error(_oauth_notice[1])

pagina_tradicional = st.Page("consulta_precios.py", title="Consulta de Precios", icon="🏷️", default=True)
pagina_movil = st.Page("pages/8_Escaner_Movil.py", title="Escáner Móvil", icon="📱")
pages = {"Principal": [pagina_tradicional, pagina_movil]}
config = [
    ("cargar_archivo", "pages/10_Inventarios.py", "Inventarios independientes", "📚"),
    ("consultar_base", "pages/4_Listado_Productos.py", "Consulta de Base de Datos", "📋"),
    ("fuentes", "pages/2_Fuentes_de_datos.py", "Administración de Fuentes de Datos", "🔌"),
    ("fuentes", "pages/11_Seleccion_Fuentes.py", "Selección de Fuentes de Datos", "🎯"),
    ("configurar", "pages/7_Google_Drive.py", "Conexión Google Drive / Sheets", "☁️"),
    ("configurar", "pages/3_Consulta_Bases_de_Datos.py", "Configurar Consulta", "⚙️"),
    ("logo", "pages/3_Logo_del_negocio.py", "Logo del Negocio", "🖼️"),
    ("logo", "pages/12_Apariencia.py", "Apariencia", "🎨"),
    ("usuarios", "pages/5_Administrador_Usuarios.py", "Administrador de Usuarios", "👥"),
    ("ubicacion_movil", "pages/9_Ubicacion_Movil.py", "Ubicación Consulta Móvil", "📍"),
]
habilitadas = [st.Page(path, title=title, icon=icon)
                for perm, path, title, icon in config if (es_administrador_autenticado if perm == "ubicacion_movil" else allowed(user, perm))]
if habilitadas:
    pages["Configuración"] = habilitadas
if es_solo_consulta:
    # Ocultar la barra por completo, incluso si el navegador recuerda que estaba abierta.
    # No se modifica el lector ni el script de enfoque de consulta_precios.py.
    st.markdown("""
    <style>
      [data-testid="stSidebar"],
      [data-testid="collapsedControl"],
      [data-testid="stSidebarCollapsedControl"],
      [data-testid="stSidebarCollapseButton"] { display: none !important; }
      [data-testid="stAppViewContainer"] { margin-left: 0 !important; }
      /* Verificador: sin la barra superior de Streamlit (Fork / GitHub / menú). */
      header[data-testid="stHeader"], [data-testid="stToolbar"],
      [data-testid="stDecoration"] { display: none !important; }
    </style>
    """, unsafe_allow_html=True)
    posicion_navegacion = "hidden"
else:
    posicion_navegacion = "sidebar"

# Controles discretos, transparentes y anclados abajo a la izquierda.
st.markdown("""<style>
.st-key-boton_salida_x_consulta, .st-key-boton_cambio_verificador {
    position: fixed !important;
    bottom: max(14px, env(safe-area-inset-bottom)) !important;
    top: auto !important;
    z-index: 999999 !important;
    width: 44px !important;
    margin: 0 !important;
    padding: 0 !important;
}
.st-key-boton_salida_x_consulta { left: 12px !important; }
.st-key-boton_cambio_verificador { left: 62px !important; }
.st-key-boton_salida_x_consulta button,
.st-key-boton_cambio_verificador button {
    width: 44px !important;
    min-height: 44px !important;
    height: 44px !important;
    padding: 0 !important;
    background: transparent !important;
    border: 0 !important;
    border-radius: 8px !important;
    box-shadow: none !important;
    color: #12376b !important;
    font-size: 25px !important;
    line-height: 1 !important;
}
.st-key-boton_salida_x_consulta button:hover,
.st-key-boton_cambio_verificador button:hover,
.st-key-boton_salida_x_consulta button:focus,
.st-key-boton_cambio_verificador button:focus {
    background: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
}
.st-key-boton_salida_x_consulta button:focus-visible,
.st-key-boton_cambio_verificador button:focus-visible {
    outline: 2px solid #12376b !important;
    outline-offset: 2px !important;
}
/* No reservar espacio superior para los controles flotantes. */
.st-key-boton_salida_x_consulta, .st-key-boton_cambio_verificador { flex: 0 0 auto !important; }
@media(max-width: 700px) {
    .st-key-boton_salida_x_consulta,
    .st-key-boton_cambio_verificador {
        bottom: max(16px, env(safe-area-inset-bottom)) !important;
    }
}
</style>""", unsafe_allow_html=True)

# Ejecutar el navegador exactamente una vez.
navegacion = st.navigation(pages, position=posicion_navegacion)
if es_solo_consulta:
    if st.button("✕", key="boton_salida_x_consulta", help="Cerrar: requiere contraseña de administrador"):
        st.session_state.autorizar_salida_consulta = True
        st.rerun()
# Mostrar el botón de cambio en TODAS las sesiones, incluidas admin y consulta.
if True:
    en_movil = navegacion.title == "Escáner Móvil"
    if st.button("▥" if en_movil else "▯", key="boton_cambio_verificador",
                 help="Cambiar a Consulta de Precios" if en_movil else "Cambiar a Escáner Móvil"):
        st.switch_page(pagina_tradicional if en_movil else pagina_movil)
navegacion.run()
