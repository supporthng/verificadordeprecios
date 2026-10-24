"""Cómo se entra a la pantalla de Consulta de Precios (verificador) en la app en línea.

- "usuario":   como siempre, con usuario y contraseña (la cuenta del verificador).
- "ubicacion": sin usuario: el equipo entra solo si está dentro de la zona autorizada
               (la misma ubicación y radio de la Consulta Móvil).
- "ambos":     la pantalla de inicio de sesión ofrece también "Entrar con la ubicación".

El personal siempre puede iniciar sesión con su usuario ("Acceso del personal").
Se guarda en logo-negocio/acceso.json (bucket privado), sin tablas nuevas.
"""
import json
import time

import requests
import streamlit as st

from supabase_cliente import cabeceras, clave_servidor, url

ARCHIVO = "logo-negocio/acceso.json"
MODOS = {
    "usuario": "Con usuario y contraseña",
    "ubicacion": "Por ubicación del local (sin usuario)",
    "ambos": "Cualquiera de los dos",
}
VALIDEZ_HORAS = 12          # cada cuánto se vuelve a comprobar la ubicación del equipo

# "Usuario" de la sesión que entró por ubicación: solo ve la Consulta de Precios.
USUARIO_UBICACION = {
    "id": None, "username": "verificador (ubicación)", "role": "usuario",
    "permissions": ["solo_consulta"], "active": True, "must_change_password": False,
    "por_ubicacion": True,
}


@st.cache_data(ttl=10, show_spinner=False)
def modo():
    try:
        r = requests.get(f"{url()}/storage/v1/object/{ARCHIVO}", headers=cabeceras(clave_servidor()), timeout=8)
        if r.status_code == 200:
            valor = r.json().get("modo")
            if valor in MODOS:
                return valor
    except (requests.RequestException, ValueError):
        pass
    return "usuario"


def guardar(nuevo):
    if nuevo not in MODOS:
        raise ValueError("Modo de acceso desconocido.")
    r = requests.post(f"{url()}/storage/v1/object/{ARCHIVO}",
                      headers=cabeceras(clave_servidor(), {"Content-Type": "application/json", "x-upsert": "true"}),
                      data=json.dumps({"modo": nuevo}).encode("utf-8"), timeout=15)
    if not r.ok:
        raise RuntimeError(f"Supabase Storage HTTP {r.status_code}: {r.text[:300]}")
    modo.clear()


def sesion_vigente():
    return st.session_state.get("geo_verificador_hasta", 0) > time.time()


def terminar():
    st.session_state.pop("geo_verificador_hasta", None)
    st.session_state.pop("geo_verificador_pedido", None)
    st.session_state.pop("sucursal_geo", None)


def verificar_ubicacion():
    """Pide la ubicación al navegador y la compara con la zona autorizada.
    Devuelve True si está autorizada; si está esperando o falla, muestra el aviso y detiene la página."""
    from mobile_geofence import get_settings, validate_location
    from streamlit_js_eval import get_geolocation
    import sucursales
    con_zona = sucursales.con_ubicacion()     # sucursales con su propia ubicación (MIGRACION_006)
    try:
        zona = get_settings()
    except Exception:
        if not con_zona:
            st.error("No se pudo leer la zona autorizada. Revisa Equipos y pantallas > Ubicación y acceso.")
            return False
        zona = {"enabled": False}
    if not zona.get("enabled") and not con_zona:
        st.warning("El acceso por ubicación necesita la zona autorizada activa "
                   "(Equipos y pantallas > Ubicación y acceso). Entra con tu usuario.")
        return False
    respuesta = get_geolocation()
    if not respuesta:
        st.info("📍 Verificando la ubicación del equipo… Si el navegador lo pide, toca «Permitir».")
        st.stop()
    if isinstance(respuesta, dict) and respuesta.get("error"):
        st.error("El navegador no pudo obtener la ubicación: " + str(respuesta["error"])
                 + ". Activa la ubicación del equipo o entra con tu usuario.")
        return False
    coords = respuesta.get("coords", respuesta) if isinstance(respuesta, dict) else {}
    lugar = {k: (coords or {}).get(k) for k in ("latitude", "longitude", "accuracy")}
    # Primero las sucursales: el equipo queda asignado a la sucursal en cuya zona está.
    if con_zona:
        sucursal, distancia = sucursales.por_ubicacion(lugar.get("latitude"), lugar.get("longitude"),
                                                      lugar.get("accuracy"))
        if sucursal:
            st.session_state["sucursal_geo"] = sucursal["codigo"]
            st.session_state["geo_verificador_hasta"] = time.time() + VALIDEZ_HORAS * 3600
            return True
        if not zona.get("enabled"):
            st.warning("Este equipo no está dentro de ninguna sucursal"
                       + (f" (la más cercana está a {distancia:,.0f} m)." if distancia is not None else ".")
                       + " Entra con tu usuario.")
            return False
    st.session_state.pop("sucursal_geo", None)
    ok, mensaje = validate_location(lugar, zona)
    if not ok:
        st.warning(mensaje.replace("Consulta Móvil", "la Consulta de Precios"))
        return False
    st.session_state["geo_verificador_hasta"] = time.time() + VALIDEZ_HORAS * 3600
    return True
