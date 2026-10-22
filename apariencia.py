"""Apariencia de la pantalla de Consulta de Precios.

Se guarda como apariencia.json en el bucket privado 'logo-negocio' de Supabase
Storage (el mismo del logo y el QR), así que no requiere tablas nuevas.
"""
import json

import requests
import streamlit as st
from supabase_cliente import cabeceras, clave_servidor, clave_publica

ARCHIVO = "logo-negocio/apariencia.json"
PREDETERMINADA = {
    "mostrar_logo": True,     # logo del negocio bajo el lector
    "mostrar_qr": True,       # QR de Consulta Móvil (si se subió uno)
    "mostrar_cuadro": False,  # cuadro donde escribe el escáner (siempre activo)
}


def _conexion():
    url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
    key = clave_servidor()
    if not url or not key:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY) en Secrets.")
    return url, cabeceras(key)


@st.cache_data(ttl=10, show_spinner=False)
def obtener():
    """Configuración vigente. Ante cualquier fallo devuelve la predeterminada,
    para que el verificador nunca deje de funcionar por esto."""
    datos = dict(PREDETERMINADA)
    try:
        url, headers = _conexion()
        r = requests.get(f"{url}/storage/v1/object/{ARCHIVO}", headers=headers, timeout=8)
        if r.status_code == 200:
            guardado = r.json()
            if isinstance(guardado, dict):
                datos.update({k: bool(guardado[k]) for k in PREDETERMINADA if k in guardado})
    except (RuntimeError, requests.RequestException, ValueError):
        pass
    return datos


def guardar(cambios):
    datos = {k: bool(cambios.get(k, v)) for k, v in PREDETERMINADA.items()}
    url, headers = _conexion()

    def _subir():
        return requests.post(f"{url}/storage/v1/object/{ARCHIVO}",
                             headers={**headers, "Content-Type": "application/json", "x-upsert": "true"},
                             data=json.dumps(datos).encode("utf-8"), timeout=15)

    r = _subir()
    if not r.ok and "bucket" in r.text.lower() and "not found" in r.text.lower():
        # El bucket privado aún no existe (nunca se subió un logo): crearlo y reintentar.
        requests.post(f"{url}/storage/v1/bucket",
                      headers={**headers, "Content-Type": "application/json"},
                      json={"id": "logo-negocio", "name": "logo-negocio", "public": False},
                      timeout=15)
        r = _subir()
    if not r.ok:
        raise RuntimeError(f"Supabase Storage HTTP {r.status_code}: {r.text[:300]}")
    obtener.clear()  # aplicar de inmediato en todas las pantallas
    return datos
