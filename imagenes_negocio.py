"""Logo, código QR y fotos de productos (bucket privado 'logo-negocio' de Supabase Storage).

Lo usa la página Apariencia. Después de cambiar el logo o el QR se republica para los
equipos sin internet (publicar_equipos.actualizar_si_publicado).
"""
import json
from datetime import datetime, timezone
from io import BytesIO

import requests
import streamlit as st
from PIL import Image

from supabase_cliente import cabeceras, clave_servidor

BUCKET = "logo-negocio"
LOGO = f"{BUCKET}/logo.png"
QR = f"{BUCKET}/qr-movil.png"
INFO_QR = f"{BUCKET}/qr-movil.json"   # de dónde vino el QR actual y cuándo


def conexion():
    url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
    key = clave_servidor()
    if not url or not key:
        raise RuntimeError("Falta configurar SUPABASE_URL o SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY).")
    return url, cabeceras(key)


def _asegurar_bucket(nombre=BUCKET):
    url, headers = conexion()
    estado = requests.get(f"{url}/storage/v1/bucket/{nombre}", headers=headers, timeout=15)
    if estado.status_code in (400, 404):
        creado = requests.post(f"{url}/storage/v1/bucket",
                               headers={**headers, "Content-Type": "application/json"},
                               json={"id": nombre, "name": nombre, "public": False}, timeout=15)
        if not creado.ok:
            # Otro proceso pudo crearlo al mismo tiempo: vale si ahora existe.
            if not requests.get(f"{url}/storage/v1/bucket/{nombre}", headers=headers, timeout=15).ok:
                raise RuntimeError(f"No se pudo crear el almacenamiento (HTTP {creado.status_code}).")
    elif not estado.ok:
        raise RuntimeError(f"No se pudo comprobar el almacenamiento (HTTP {estado.status_code}).")


def _subir(ruta, datos, tipo):
    url, headers = conexion()
    r = requests.post(f"{url}/storage/v1/object/{ruta}",
                      headers={**headers, "Content-Type": tipo, "x-upsert": "true"},
                      data=datos, timeout=25)
    if not r.ok:
        raise RuntimeError(f"No se pudo guardar (HTTP {r.status_code}): {r.text[:300]}")


def leer(ruta):
    """Bytes del archivo privado, o None si no existe o no se pudo leer."""
    try:
        url, headers = conexion()
        r = requests.get(f"{url}/storage/v1/object/{ruta}", headers=headers, timeout=12)
    except (RuntimeError, requests.RequestException):
        return None
    if r.ok and r.headers.get("Content-Type", "").startswith("image/"):
        return r.content
    return None


@st.cache_data(ttl=120, show_spinner=False)
def imagenes_actuales(_marca=0):
    """(logo, qr) en bytes para la vista previa. _marca cambia al guardar, para releer."""
    return leer(LOGO), leer(QR)


def _republicar():
    import publicar_equipos
    return publicar_equipos.actualizar_si_publicado()


# ---------------------------------------------------------------- logo
def preparar_logo(archivo):
    """PNG optimizado (máx. 1400×900) a partir de un JPG/PNG subido. Conserva la transparencia."""
    with Image.open(archivo) as im:
        im.verify()
    archivo.seek(0)
    with Image.open(archivo) as im:
        im.load()
        imagen = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im.copy()
    imagen.thumbnail((1400, 900))
    salida = BytesIO()
    imagen.save(salida, format="PNG", optimize=True)
    return salida.getvalue()


def guardar_logo(png):
    _asegurar_bucket()
    _subir(LOGO, png, "image/png")
    return _republicar()


def quitar_logo():
    url, headers = conexion()
    r = requests.delete(f"{url}/storage/v1/object/{LOGO}", headers=headers, timeout=15)
    if not r.ok and r.status_code not in (400, 404):
        raise RuntimeError(f"No se pudo quitar el logo (HTTP {r.status_code}).")
    return _republicar()


# ---------------------------------------------------------------- QR
def leer_enlace_qr(datos_imagen):
    """Lee el QR de una imagen y devuelve el texto/dirección que contiene (o None)."""
    try:
        import zxingcpp
        with Image.open(BytesIO(datos_imagen)) as im:
            encontrados = zxingcpp.read_barcodes(im.convert("RGB"))
        return encontrados[0].text if encontrados else None
    except Exception:
        return None


def leer_info_qr():
    try:
        url, headers = conexion()
        r = requests.get(f"{url}/storage/v1/object/{INFO_QR}", headers=headers, timeout=10)
        return r.json() if r.ok else {}
    except (RuntimeError, requests.RequestException, ValueError):
        return {}


def guardar_qr(datos_png, origen, enlace=None):
    """Guarda el QR y registra su origen ("generado" o "subido"), la dirección y la fecha."""
    _asegurar_bucket()
    _subir(QR, datos_png, "image/png")
    info = {"origen": origen, "enlace": enlace,
            "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:   # el registro es informativo: si falla, el QR igual quedó guardado
        _subir(INFO_QR, json.dumps(info).encode("utf-8"), "application/json")
    except (RuntimeError, requests.RequestException):
        pass
    return _republicar()


def generar_qr_png(enlace):
    """QR del enlace como PNG nítido (cuadros negros sobre blanco)."""
    import segno
    salida = BytesIO()
    segno.make(enlace, error="m", micro=False).save(
        salida, kind="png", scale=12, border=3, dark="#000000", light="#ffffff")
    return salida.getvalue()


def preparar_qr(archivo):
    with Image.open(archivo) as original:
        imagen = original.convert("RGB")
    imagen.thumbnail((900, 900))
    salida = BytesIO()
    imagen.save(salida, format="PNG", optimize=True)
    return salida.getvalue()


def enlace_consulta_movil():
    """Dirección pública de Consulta Móvil, sin el marco de Streamlit (embed=true).
    Usa la dirección RAÍZ con ?movil=1: en modo embed, Streamlit Cloud no reconoce
    la ruta /Escaner_Movil y muestra "Page not found". light_theme evita el tema
    oscuro del teléfono, con el que algunos textos no se leen bien."""
    from urllib.parse import urlsplit
    try:
        partes = urlsplit(st.context.url)
        base = f"{partes.scheme}://{partes.netloc}" if partes.netloc else ""
    except (AttributeError, TypeError, ValueError):
        base = ""
    return (base or "https://TU-APP.streamlit.app") + "/?movil=1&embed=true&embed_options=light_theme"


def revisar_enlace_qr(enlace):
    """(nivel, mensaje) sobre a dónde lleva el QR. nivel: success | info | warning."""
    if not enlace:
        return "warning", "No se pudo leer el contenido de este QR (imagen borrosa o no es un QR)."
    if "escaner_movil" not in enlace.lower() and "movil=1" not in enlace:
        return "warning", "Este QR **no** lleva a Consulta Móvil. Genera uno nuevo."
    if "embed=true" not in enlace:
        return "info", ("Lleva a Consulta Móvil, pero con la barra y los íconos de Streamlit. "
                        "Si generas uno nuevo, se abrirá sin ellos.")
    if "/escaner_movil" in enlace.lower() or "light_theme" not in enlace:
        return "info", ("Lleva a Consulta Móvil, pero es de una versión anterior: puede mostrar el aviso "
                        "«Page not found» o el tema oscuro. Pulsa «Generar y guardar QR» para actualizarlo.")
    return "success", "Correcto: lleva a Consulta Móvil sin el marco de Streamlit."


# ---------------------------------------------------------------- fotos de productos
def guardar_foto_producto(codigo, archivo):
    with Image.open(archivo) as original:
        imagen = original.convert("RGB")
    imagen.thumbnail((800, 800))
    salida = BytesIO()
    imagen.save(salida, format="PNG", optimize=True)
    _asegurar_bucket("imagenes-productos")
    _subir(f"imagenes-productos/{codigo}.png", salida.getvalue(), "image/png")
    return salida.getvalue()
