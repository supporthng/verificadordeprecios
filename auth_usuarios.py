"""Autenticación administrativa y permisos en Supabase."""
import base64
import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

URL = str(st.secrets.get("SUPABASE_URL", "")).rstrip("/")
KEY = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", ""))
PERMISOS = {
    "cargar_archivo": "Cargar Archivo Local",
    "consultar_base": "Consulta de Base de Datos",
    "fuentes": "Fuentes de Datos",
    "configurar": "Configurar Consulta",
    "logo": "Logo del Negocio",
    "usuarios": "Administrador de Usuarios",
    "solo_consulta": "Modo verificador (kiosko): solo Consulta de Precios",
}
MAX_FALLOS = 5
BLOQUEO_SEGUNDOS = 300
MENSAJE_GENERICO = "Usuario o contraseña incorrectos."
_HASH_FICTICIO = None


def api(method, params=None, data=None):
    if not URL or not KEY:
        raise RuntimeError("Faltan las credenciales técnicas de Supabase en Secrets.")
    r = requests.request(method, URL + "/rest/v1/verificador_usuarios",
        headers={"apikey": KEY, "Authorization": "Bearer " + KEY,
                 "Content-Type": "application/json", "Prefer": "return=representation"},
        params=params, json=data, timeout=15)
    if not r.ok:
        raise RuntimeError("Supabase HTTP %s: %s" % (r.status_code, r.text[:350]))
    return r.json() if r.content else []


def hash_password(password):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600000)
    return "pbkdf2_sha256$600000$%s$%s" % (
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verificar(password, stored):
    try:
        kind, rounds, salt, expected = stored.split("$")
        if kind != "pbkdf2_sha256" or int(rounds) < 200000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
            base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError, AttributeError):
        return False


def get_user(username):
    rows = api("GET", {"username": "eq." + str(username).lower().strip(),
                       "select": "*", "limit": 1})
    return rows[0] if rows else None


# --- Roles -------------------------------------------------------------
def es_admin(user):
    """Administrador por ROL, no por nombre de usuario."""
    return bool(user and user.get("active") and user.get("role") == "admin")


def es_kiosko(user):
    """Cuenta de verificador: solo Consulta de Precios, salida con clave de admin.
    Se mantiene el nombre 'consulta' por compatibilidad con instalaciones previas."""
    if not user or user.get("role") == "admin":
        return False
    return ("solo_consulta" in (user.get("permissions") or [])
            or str(user.get("username", "")).strip().lower() == "consulta")


def allowed(user, permission):
    return bool(user and not user["must_change_password"] and
                (user["role"] == "admin" or permission in (user.get("permissions") or [])))


# --- Inicio de sesión con bloqueo guardado en la base ------------------
def _ahora():
    return datetime.now(timezone.utc)


def _bloqueado_hasta(cuenta):
    valor = cuenta.get("locked_until")
    if not valor:
        return None
    try:
        hasta = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    return hasta if hasta > _ahora() else None


def intentar_login(username, password):
    """Valida credenciales. Devuelve (cuenta, "") o (None, mensaje).

    Tras MAX_FALLOS intentos fallidos la cuenta queda bloqueada
    BLOQUEO_SEGUNDOS en Supabase: recargar la página no reinicia el contador.
    Si aún no se ejecutó MIGRACION_002, funciona sin bloqueo en la base.
    """
    global _HASH_FICTICIO
    nombre = str(username or "").strip()
    cuenta = get_user(nombre) if nombre else None
    if not cuenta:
        # Mismo costo de cálculo que una cuenta real: no revela si el usuario existe.
        if _HASH_FICTICIO is None:
            _HASH_FICTICIO = hash_password("x")
        verificar(str(password), _HASH_FICTICIO)
        return None, MENSAJE_GENERICO

    soporta_bloqueo = "failed_attempts" in cuenta
    hasta = _bloqueado_hasta(cuenta) if soporta_bloqueo else None
    if hasta:
        minutos = max(1, int((hasta - _ahora()).total_seconds() // 60) + 1)
        return None, f"Demasiados intentos fallidos. Intenta de nuevo en {minutos} min."

    if cuenta.get("active") and verificar(str(password), cuenta["password_hash"]):
        if soporta_bloqueo and (cuenta.get("failed_attempts") or cuenta.get("locked_until")):
            api("PATCH", {"id": "eq." + str(cuenta["id"])},
                {"failed_attempts": 0, "locked_until": None})
        return cuenta, ""

    if soporta_bloqueo:
        fallos = int(cuenta.get("failed_attempts") or 0) + 1
        cambios = {"failed_attempts": fallos}
        if fallos >= MAX_FALLOS:
            cambios = {"failed_attempts": 0,
                       "locked_until": (_ahora() + timedelta(seconds=BLOQUEO_SEGUNDOS)).isoformat()}
        try:
            api("PATCH", {"id": "eq." + str(cuenta["id"])}, cambios)
        except RuntimeError:
            pass
    return None, MENSAJE_GENERICO


def bootstrap():
    """Crear el primer administrador solo si la tabla está vacía.

    La clave inicial sale de ADMIN_INITIAL_PASSWORD en Secrets; nunca 'admin'.
    """
    rows = api("GET", {"select": "id", "limit": 1})
    if rows:
        return
    inicial = str(st.secrets.get("ADMIN_INITIAL_PASSWORD", "")).strip()
    if len(inicial) < 12:
        raise RuntimeError(
            "No hay usuarios creados. Define ADMIN_INITIAL_PASSWORD (12+ caracteres) "
            "en Streamlit Secrets para crear el administrador inicial 'admin'.")
    try:
        api("POST", data={"username": "admin", "password_hash": hash_password(inicial),
                          "role": "admin", "permissions": [p for p in PERMISOS if p != "solo_consulta"],
                          "must_change_password": True, "active": True})
    except RuntimeError:
        # Puede haber sido creado en otra sesión concurrente.
        if not get_user("admin"):
            raise


def current_user():
    uid = st.session_state.get("usuario_id")
    if not uid:
        return None
    rows = api("GET", {"id": "eq." + str(uid), "select": "*", "limit": 1})
    if not rows or not rows[0]["active"]:
        st.session_state.usuario_id = None
        return None
    return rows[0]


def require(permission):
    u = current_user()
    if not allowed(u, permission):
        st.error("Acceso restringido. Inicia sesión con un usuario autorizado.")
        st.stop()
    return u


def require_admin():
    u = current_user()
    if not es_admin(u) or u["must_change_password"]:
        st.error("Esta sección requiere una cuenta con rol administrador.")
        st.stop()
    return u


def cambiar_password(user, nueva):
    if len(nueva) < 8:
        raise ValueError("La nueva contraseña debe tener al menos 8 caracteres.")
    if verificar(nueva, user["password_hash"]):
        raise ValueError("La nueva contraseña debe ser distinta de la actual.")
    cambios = {"password_hash": hash_password(nueva), "must_change_password": False}
    if "failed_attempts" in user:
        cambios.update(failed_attempts=0, locked_until=None)
    api("PATCH", {"id": "eq." + str(user["id"])}, cambios)
