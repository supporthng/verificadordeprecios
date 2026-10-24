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

# Archivos subidos a GitHub con la app ya funcionando: Streamlit puede seguir usando en memoria la
# versión VIEJA de los módulos del proyecto (y fallar con AttributeError). Recargar los que cambiaron.
def _recargar_modulos_cambiados():
    import importlib
    import os
    import sys
    raiz = os.path.dirname(os.path.abspath(__file__))
    for nombre, modulo in list(sys.modules.items()):
        archivo = getattr(modulo, "__file__", None) or ""
        if not archivo.startswith(raiz) or os.path.dirname(archivo) != raiz or nombre in ("__main__", "app"):
            continue
        try:
            fecha = os.path.getmtime(archivo)
        except OSError:
            continue
        anterior = getattr(modulo, "_fecha_archivo", None)
        if anterior != fecha:   # nunca revisado en este proceso, o el archivo cambió: recargar una vez
            try:
                modulo = importlib.reload(modulo)
            except Exception:
                continue
        try:
            modulo._fecha_archivo = fecha
        except Exception:
            pass


_recargar_modulos_cambiados()

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

@st.cache_resource
def _codigos_oauth_usados():
    """Huellas de los códigos OAuth ya canjeados (compartido entre sesiones del servidor)."""
    import threading
    return {"lock": threading.Lock(), "codigos": set()}


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
        if _oauth_error == "access_denied":
            raise RuntimeError(
                "Google no dio acceso (access_denied). Pasa por una de estas dos razones: "
                "1) en la pantalla de permisos no se marcó «Seleccionar todos» (las casillas de Drive y "
                "Hojas de cálculo) o se pulsó Cancelar; o "
                "2) la app de Google Cloud está en modo Prueba y esa cuenta no es usuario de prueba: "
                "agrega el correo en Google Cloud > Google Auth Platform > Público (Usuarios de prueba) "
                "o pulsa Publicar app. Luego vuelve a Conectar con Google.")
        if _oauth_error:
            raise RuntimeError("Google rechazó la autorización: " + _oauth_error)
        if not _oauth_code or not verify_state(_oauth_state):
            raise RuntimeError("Autorización inválida o vencida. Inicia nuevamente desde Administración.")
        # No depende del login de Streamlit. El state firmado fue emitido
        # únicamente desde la página administrativa protegida.
        # El código de Google sirve UNA vez. Si Streamlit procesa el regreso dos veces
        # (dos ejecuciones o dos sesiones seguidas), la segunda no debe volver a canjearlo.
        import hashlib as _hashlib
        _usados = _codigos_oauth_usados()
        _huella = _hashlib.sha256(_oauth_code.encode()).hexdigest()
        with _usados["lock"]:
            _ya = _huella in _usados["codigos"]
            _usados["codigos"].add(_huella)
        if not _ya:
            try:
                connect(exchange_code(_oauth_code))
            except Exception:
                with _usados["lock"]:
                    _usados["codigos"].discard(_huella)
                raise
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
# Cuenta kiosko: pasar a Escáner Móvil también exige clave de administrador.
st.session_state.setdefault("autorizar_cambio_movil", False)
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

# Verificador que entró por la ubicación del local (sin usuario): se comporta como la
# cuenta del verificador (kiosko) mientras la ubicación siga vigente.
import acceso_verificador as acceso
if str(st.query_params.get("personal", "")) == "1":
    st.session_state["acceso_personal"] = True     # el personal entra con su usuario
if not user and acceso.sesion_vigente() and acceso.modo() != "usuario":
    user = dict(acceso.USUARIO_UBICACION)

if user and not user.get("por_ubicacion"):
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
    # Acceso por ubicación: el verificador entra sin usuario si está en el local.
    _modo_acceso = acceso.modo()
    if (_modo_acceso != "usuario" and not st.session_state.get("acceso_personal")
            and (_modo_acceso == "ubicacion" or st.session_state.get("geo_verificador_pedido"))):
        if acceso.verificar_ubicacion():
            st.rerun()
        st.session_state["geo_verificador_pedido"] = False   # falló: queda el inicio de sesión
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
        if _modo_acceso in ("ambos", "ubicacion"):
            if st.button("📍 Entrar como verificador (ubicación del local)", use_container_width=True,
                         key="entrar_por_ubicacion"):
                st.session_state["geo_verificador_pedido"] = True
                st.session_state["acceso_personal"] = False
                st.rerun()
            st.caption("O inicia sesión con tu usuario:")
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
    if user and user.get("por_ubicacion"):
        # Salida autorizada del verificador por ubicación: mostrar el inicio de sesión del personal.
        acceso.terminar()
        st.session_state["acceso_personal"] = True
    st.session_state.autorizar_salida_consulta = False
    st.session_state.autorizar_cambio_movil = False
    st.session_state.usuario_id = None
    for permiso_temporal in ("admin_authenticated", "fuentes_admin_ok", "external_admin_ok"):
        st.session_state[permiso_temporal] = False
    # La cookie se borra en la siguiente carga (logout_pendiente).
    st.rerun()

# La X de consulta exige la contraseña de la cuenta administradora.
# No cerrar ni invalidar la sesión hasta validar la clave en el servidor.
if (solicitar_salida or st.session_state.autorizar_salida_consulta
        or st.session_state.autorizar_cambio_movil) and es_kiosko(user):
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
        modo_cambio = bool(st.session_state.autorizar_cambio_movil)
        if not nombre_admin and transcurridos >= 10:
            st.session_state.autorizar_salida_consulta = False
            st.session_state.autorizar_cambio_movil = False
            st.session_state.pop("inicio_autorizacion_admin", None)
            if "salir" in st.query_params:
                del st.query_params["salir"]
            st.rerun(scope="app")

        if modo_cambio:
            st.title("🔐 Autorizar cambio a Escáner Móvil")
            st.info("Para cambiar este verificador a Escáner Móvil, introduce el usuario y la contraseña del administrador.")
        else:
            st.title("🔐 Autorizar salida")
            st.info("Para cerrar cualquiera de los verificadores, introduce el usuario y la contraseña del administrador.")
        st.text_input("Usuario administrador", key="salida_usuario_admin")
        if not nombre_admin:
            st.caption(f"Regreso automático a Consulta de Precios en {max(0, 10 - int(transcurridos))} segundos si no escribe el usuario.")
        with st.form("formulario_credenciales_admin_para_salir", clear_on_submit=False):
            clave_administrador = st.text_input("Contraseña del administrador", type="password", key="salida_clave_admin")
            if modo_cambio:
                confirmar_salida = st.form_submit_button("Confirmar cambio a Escáner Móvil", use_container_width=True)
                iniciar_admin = False
            else:
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
                if modo_cambio:
                    # El cambio de página se hace después de st.navigation (más abajo).
                    st.session_state.autorizar_cambio_movil = False
                    st.session_state.cambio_movil_autorizado = True
                    st.rerun(scope="app")
                elif iniciar_admin:
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
            st.session_state.autorizar_cambio_movil = False
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

# Sucursal de esta sesión: la del usuario (encargado o verificador de una sucursal) o, si entró
# por ubicación, la sucursal en cuya zona está el equipo. Vacío = negocio general.
try:
    import sucursales as _suc
    _sucursal_sesion = (_suc.por_codigo(st.session_state.get("sucursal_geo")) if user.get("por_ubicacion")
                        else _suc.de_usuario(user))
except Exception:
    _sucursal_sesion = None
st.session_state["sucursal_codigo"] = _sucursal_sesion["codigo"] if _sucursal_sesion else None
st.session_state["sucursal_nombre"] = _sucursal_sesion["nombre"] if _sucursal_sesion else None
# Usuario general: sin sucursal asignada. Los encargados no ven la configuración común.
es_usuario_general = not user.get("sucursal_id")

# La cuenta exclusiva de consulta no necesita navegación lateral.
es_solo_consulta = es_kiosko(user)
# consulta_precios.py lo usa para mostrar la pantalla adaptada al alto del equipo.
st.session_state["modo_kiosko"] = es_solo_consulta
if not es_solo_consulta:
    # Marca arriba del menú (y su ícono cuando el menú está plegado).
    try:
        st.logo("assets/logo_menu.png", size="large", icon_image="assets/icono_menu.png")
    except Exception:
        pass
    with st.sidebar:
        import html as _html
        _nombre = str(user["username"])
        _rol = "Administrador" if user.get("role") == "admin" else "Usuario"
        st.markdown(
            f'<div class="menu-usuario"><div class="menu-avatar">{_html.escape(_nombre[:1].upper())}</div>'
            f'<div><div class="menu-nombre">{_html.escape(_nombre)}</div>'
            f'<div class="menu-rol">{_rol}</div></div></div>', unsafe_allow_html=True)
        # Usuarios normales y administradores salen directamente; solo la
        # cuenta kiosko (sin barra lateral) exige la clave del administrador.
        if st.button("Cerrar sesión", key="sidebar_logout", icon=":material/logout:",
                     use_container_width=True):
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

# El verificador (kiosko) entra directo a la consulta; el personal, al Inicio con el resumen.
pagina_tradicional = st.Page("consulta_precios.py", title="Consulta de precios", icon="🏷️",
                             default=es_solo_consulta)
pagina_movil = st.Page("pages/8_Escaner_Movil.py", title="Escáner móvil", icon="📱")
if es_solo_consulta:
    pages = {"Principal": [pagina_tradicional]}   # el verificador no usa la cámara
else:
    pagina_inicio = st.Page("pages/0_Inicio.py", title="Inicio", icon="🏠", default=True)
    pages = {"Principal": [pagina_inicio, pagina_tradicional, pagina_movil]}
# Menú agrupado por tarea, con nombres cortos (caben sin cortarse en la barra lateral).
# "admin" = solo administradores. Las direcciones de las páginas no cambian (salen del archivo).
MENU = {
    "Precios": [
        ("cargar_archivo", "pages/10_Inventarios.py", "Inventarios (Excel)", "📚"),
        ("fuentes", "pages/11_Seleccion_Fuentes.py", "Fuente activa", "🎯"),
        ("configurar", "pages/7_Google_Drive.py", "Google Drive / Sheets", "☁️"),
        ("consultar_base", "pages/4_Listado_Productos.py", "Buscar productos", "📋"),
    ],
    "Equipos y pantallas": [
        ("admin", "pages/14_Equipos_sin_internet.py", "Equipos sin internet", "📴"),
        ("logo", "pages/12_Apariencia.py", "Apariencia", "🎨"),
        ("admin", "pages/9_Ubicacion_Movil.py", "Ubicación y acceso", "📍"),
    ],
    "Informes": [
        ("consultar_base", "pages/13_Registro_Consultas.py", "Registro de consultas", "📊"),
    ],
    "Administración": [
        ("usuarios", "pages/5_Administrador_Usuarios.py", "Usuarios", "👥"),
        ("sucursales", "pages/15_Sucursales.py", "Sucursales", "🏬"),
    ],
    "SQL Server": [
        ("fuentes", "pages/2_Fuentes_de_datos.py", "Servidores", "🔌"),
        ("configurar", "pages/3_Consulta_Bases_de_Datos.py", "Consulta externa", "⚙️"),
    ],
}
# Configuración común a todas las sucursales: solo la ven los usuarios generales.
SOLO_GENERAL = {"pages/10_Inventarios.py", "pages/11_Seleccion_Fuentes.py", "pages/7_Google_Drive.py",
                "pages/14_Equipos_sin_internet.py", "pages/12_Apariencia.py", "pages/9_Ubicacion_Movil.py",
                "pages/2_Fuentes_de_datos.py", "pages/3_Consulta_Bases_de_Datos.py"}


st.session_state["paginas_solo_general"] = SOLO_GENERAL


def _puede_ver(perm, path):
    if path in SOLO_GENERAL and not es_usuario_general:
        return False
    if perm == "sucursales":   # el general la administra; el encargado ve los precios de su sucursal
        return (es_administrador_autenticado and es_usuario_general) or (
            not es_usuario_general and allowed(user, "cargar_archivo"))
    return es_administrador_autenticado if perm == "admin" else allowed(user, perm)


for seccion, opciones in MENU.items():
    visibles = [st.Page(path, title=title, icon=icon) for perm, path, title, icon in opciones
                if _puede_ver(perm, path)]
    if visibles:
        pages[seccion] = visibles
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
    # Páginas del personal: sin el espacio vacío que Streamlit deja arriba del contenido
    # y del menú. La barra superior (menú ☰, Share) se mantiene, pero más baja.
    st.markdown("""
    <style>
      header[data-testid="stHeader"] { height: 2.75rem !important; min-height: 2.75rem !important; }
      [data-testid="stMainBlockContainer"], .block-container {
          padding-top: 2.9rem !important; padding-bottom: 2rem !important;
      }
      [data-testid="stSidebarHeader"] {
          height: 2.75rem !important; min-height: 0 !important; padding-top: .4rem !important;
          padding-bottom: 0 !important; margin-bottom: 0 !important;
      }
      [data-testid="stSidebarUserContent"] { padding-top: .5rem !important; }
      [data-testid="stSidebarNav"] { padding-top: 0 !important; }
      /* ---------- Menú lateral ---------- */
      [data-testid="stSidebar"] {
          background: linear-gradient(180deg, #f8fbff 0%, #eef3fb 100%) !important;
          border-right: 1px solid #e1e9f5 !important;
      }
      [data-testid="stSidebarHeader"] { padding-left: 1.1rem !important; }
      [data-testid="stSidebarHeader"] img { height: 2.1rem !important; max-height: 2.1rem !important; }
      [data-testid="stSidebarNavItems"] { padding: .25rem .6rem 0 !important; }
      /* Títulos de sección: pequeños y discretos */
      [data-testid="stNavSectionHeader"], [data-testid="stSidebarNavItems"] header {
          font-size: .7rem !important; font-weight: 800 !important; letter-spacing: .09em !important;
          text-transform: uppercase !important; color: #8a99b3 !important;
          margin: 1rem .4rem .3rem !important; padding: 0 !important;
      }
      [data-testid="stNavSectionHeader"] * { color: #8a99b3 !important; font-size: .7rem !important; }
      [data-testid="stSidebarNavItems"] > *:first-child [data-testid="stNavSectionHeader"] { margin-top: .2rem !important; }
      /* Opciones */
      [data-testid="stSidebarNavLink"] {
          border-radius: 10px !important; padding: .42rem .7rem !important; margin: 1px 0 !important;
          transition: background .12s, transform .12s;
      }
      [data-testid="stSidebarNavLink"] span { color: #23395d !important; font-weight: 600 !important; font-size: .92rem !important; }
      [data-testid="stSidebarNavLink"]:hover { background: #e3ecfb !important; }
      [data-testid="stSidebarNavLink"]:hover span { color: #0757d4 !important; }
      /* Página actual: resaltada en azul */
      [data-testid="stSidebarNavLink"][aria-current="page"] {
          background: linear-gradient(105deg, #0757d4, #2f7bf0) !important;
          box-shadow: 0 4px 12px rgba(7, 87, 212, .25) !important;
      }
      [data-testid="stSidebarNavLink"][aria-current="page"] span { color: #ffffff !important; }
      [data-testid="stSidebarNavSeparator"] { margin: .8rem .6rem !important; }
      /* Tarjeta del usuario */
      .menu-usuario {
          display: flex; align-items: center; gap: 12px; background: #ffffff; border: 1px solid #e1e9f5;
          border-radius: 14px; padding: 10px 12px; box-shadow: 0 2px 8px rgba(16, 43, 80, .05);
      }
      .menu-avatar {
          width: 38px; height: 38px; border-radius: 50%; flex: 0 0 auto; display: grid; place-items: center;
          background: linear-gradient(135deg, #0757d4, #ff9d20); color: #fff; font-weight: 800; font-size: 17px;
      }
      .menu-nombre { font-weight: 700; color: #0d2d58; font-size: 15px; line-height: 1.2; }
      .menu-rol { color: #7c8ca6; font-size: 12.5px; }
      .st-key-sidebar_logout button {
          border-radius: 10px !important; border: 1px solid #f3c9c9 !important; background: #fff !important;
          color: #b42318 !important; font-weight: 600 !important;
      }
      .st-key-sidebar_logout button:hover { background: #fff1f1 !important; border-color: #e8a0a0 !important; }
      .st-key-sidebar_logout button * { color: #b42318 !important; }
      /* Elementos invisibles (estilos, guardado de sesión, scripts): Streamlit les deja
         16 px de separación a cada uno. Se sacan del flujo, pero siguen funcionando. */
      [data-testid="stMain"] [data-testid="stElementContainer"]:has([data-testid="stMarkdownContainer"]):not(:has([data-testid="stMarkdownContainer"] > :not(style))) {
          display: none !important;
      }
      [data-testid="stMain"] [data-testid="stElementContainer"]:has(iframe[height="0"]),
      [data-testid="stMain"] [data-testid="stElementContainer"]:has(iframe[style*="height: 0"]) {
          position: absolute !important; width: 0 !important; height: 0 !important;
          overflow: hidden !important; margin: 0 !important;
      }
    </style>
    """, unsafe_allow_html=True)

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
    /* Fondo claro y redondo: visibles sobre cualquier contenido. */
    background: rgba(255, 255, 255, .92) !important;
    border: 1px solid #d5e1f1 !important;
    border-radius: 50% !important;
    box-shadow: 0 2px 6px rgba(16, 43, 80, .12) !important;
    color: #12376b !important;
    font-size: 24px !important;
    line-height: 1 !important;
}
/* Streamlit dibuja el texto del botón en un <p> con su propio tamaño. */
.st-key-boton_salida_x_consulta button p,
.st-key-boton_cambio_verificador button p {
    font-size: 24px !important;
    line-height: 1 !important;
    margin: 0 !important;
    font-weight: 700 !important;
}
.st-key-boton_salida_x_consulta button:hover,
.st-key-boton_cambio_verificador button:hover,
.st-key-boton_salida_x_consulta button:focus,
.st-key-boton_cambio_verificador button:focus {
    background: #ffffff !important;
    border: 1px solid #b9cbe6 !important;
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
try:   # expanded=True: todo el menú a la vista, sin "View more / View less"
    navegacion = st.navigation(pages, position=posicion_navegacion, expanded=True)
except TypeError:
    navegacion = st.navigation(pages, position=posicion_navegacion)
if es_solo_consulta:
    if st.button("✕", key="boton_salida_x_consulta", help="Cerrar: requiere contraseña de administrador"):
        st.session_state.autorizar_salida_consulta = True
        st.rerun()
# La pantalla de consulta es de consulta rápida con el lector: sin botón para pasar a la cámara.
# (El personal abre Escáner móvil desde el menú; los clientes, desde el QR.)
navegacion.run()
