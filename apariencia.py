"""Apariencia de la pantalla de Consulta de Precios.

Se guarda como apariencia.json en el bucket privado 'logo-negocio' de Supabase
Storage (el mismo del logo y el QR), así que no requiere tablas nuevas.
Los equipos sin internet la reciben dentro de estado.json (publicar_equipos).
"""
import json
import re

import requests
import streamlit as st
from supabase_cliente import cabeceras, clave_servidor

ARCHIVO = "logo-negocio/apariencia.json"

# Estilos de la pantalla lectora: clave -> (nombre, descripción corta)
ESTILOS = {
    "claro": ("Claro", "Fondo blanco, precio en el color del negocio. El más limpio."),
    "noche": ("Noche", "Fondo azul noche y letras claras. Ideal con mucha luz o pantallas brillantes."),
    "marca": ("Color del negocio", "Toda la pantalla en el color del negocio."),
    "etiqueta": ("Etiqueta de góndola", "El precio aparece en una etiqueta amarilla, como en el estante."),
    "panel": ("Panel lateral", "Franja con logo, nombre y QR siempre visible; el precio al lado."),
}
POSICIONES_LOGO = {"esquina": "Arriba, en la esquina", "centro": "Grande, en el centro"}
COLOR_PREDETERMINADO = "#0757d4"

PREDETERMINADA = {
    "nombre_negocio": "",
    "mostrar_nombre": True,
    "estilo": "claro",
    "color_marca": COLOR_PREDETERMINADO,
    "posicion_logo": "esquina",
    "titulo_espera": "Escanea tu producto",
    "mensaje_espera": "Pasa el código de barras por el lector",
    "texto_qr": "Consulta también desde tu celular",
    "moneda": "RD$",
    "mostrar_logo": True,     # logo del negocio
    "mostrar_qr": True,       # QR de Consulta Móvil (si se subió uno)
    "mostrar_cuadro": False,  # cuadro donde escribe el escáner (siempre activo)
}
LARGOS = {"nombre_negocio": 60, "titulo_espera": 60, "mensaje_espera": 90, "texto_qr": 60, "moneda": 6}
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalizar(datos):
    """Devuelve una apariencia completa y válida a partir de lo que venga
    (valores viejos, faltantes o mal escritos se reemplazan por los predeterminados)."""
    datos = datos if isinstance(datos, dict) else {}
    limpio = {}
    for clave, defecto in PREDETERMINADA.items():
        valor = datos.get(clave, defecto)
        if isinstance(defecto, bool):
            limpio[clave] = bool(valor)
        elif clave == "estilo":
            limpio[clave] = valor if valor in ESTILOS else defecto
        elif clave == "posicion_logo":
            limpio[clave] = valor if valor in POSICIONES_LOGO else defecto
        elif clave == "color_marca":
            limpio[clave] = valor.lower() if isinstance(valor, str) and _COLOR.match(valor) else defecto
        else:
            texto = " ".join(str(valor if valor is not None else "").split())[:LARGOS[clave]]
            # Los textos de la pantalla no pueden quedar vacíos (el nombre sí: es opcional).
            limpio[clave] = texto if (texto or clave == "nombre_negocio") else defecto
    return limpio


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
    try:
        url, headers = _conexion()
        r = requests.get(f"{url}/storage/v1/object/{ARCHIVO}", headers=headers, timeout=8)
        if r.status_code == 200:
            return normalizar(r.json())
    except (RuntimeError, requests.RequestException, ValueError):
        pass
    return dict(PREDETERMINADA)


def guardar(cambios):
    """Guarda la apariencia (se combina con la vigente). Devuelve lo guardado."""
    datos = normalizar({**obtener(), **(cambios or {})})
    url, headers = _conexion()

    def _subir():
        return requests.post(f"{url}/storage/v1/object/{ARCHIVO}",
                             headers={**headers, "Content-Type": "application/json", "x-upsert": "true"},
                             data=json.dumps(datos, ensure_ascii=False).encode("utf-8"), timeout=15)

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
