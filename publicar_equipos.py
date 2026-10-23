"""Publicación para los equipos sin internet (verificador y celulares con la app offline).

Los equipos NO consultan Supabase en cada escaneo: guardan una copia del catálogo
y la renuevan solo cuando cambia. Para eso se publican archivos en el bucket
PÚBLICO 'equipos' de Supabase Storage:

    estado.json               pequeño (~1 KB): versión vigente, apariencia, logo, QR,
                              verificación de la clave de salida. Los equipos lo
                              revisan cada minuto cuando hay internet.
    catalogo-<version>.json   el catálogo completo. Su nombre cambia con el contenido,
                              así que un equipo lo descarga UNA vez por cambio de precios.
    logo.png / qr.png         copias públicas del logo y del QR.

La versión es una huella del contenido: publicar dos veces el mismo catálogo no
obliga a los equipos a descargar nada.

Nada de esto es secreto: el inventario activo ya es legible con la clave pública.
La clave de salida se publica solo como verificación PBKDF2 (no la clave misma);
por eso es una clave PROPIA del verificador, distinta de cualquier contraseña de usuario.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

import requests

from supabase_cliente import cabeceras, clave_publica, clave_servidor, url

BUCKET = "equipos"
PRIVADO = "logo-negocio"
CLAVE_SALIDA = f"{PRIVADO}/clave-salida.json"
ITERACIONES = 210_000          # PBKDF2-SHA256: también lo calcula el navegador (WebCrypto)
LARGO_MINIMO_CLAVE = 4
FORMATO = 1                    # sube si cambia la estructura de los archivos


def _conexion():
    base, clave = url(), clave_servidor()
    if not base or not clave:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY) en Secrets.")
    return base, cabeceras(clave)


def url_publica(nombre=""):
    return f"{url()}/storage/v1/object/public/{BUCKET}/{nombre}"


# ---------------------------------------------------------------- almacenamiento
def _asegurar_bucket(base, headers):
    r = requests.get(f"{base}/storage/v1/bucket/{BUCKET}", headers=headers, timeout=15)
    if r.status_code == 200:
        if not r.json().get("public"):
            requests.put(f"{base}/storage/v1/bucket/{BUCKET}",
                         headers={**headers, "Content-Type": "application/json"},
                         json={"public": True}, timeout=15)
        return
    creado = requests.post(f"{base}/storage/v1/bucket", headers={**headers, "Content-Type": "application/json"},
                           json={"id": BUCKET, "name": BUCKET, "public": True}, timeout=15)
    if not creado.ok and "already exists" not in creado.text.lower():
        raise RuntimeError(f"No se pudo crear el almacenamiento público (HTTP {creado.status_code}): {creado.text[:300]}")


def _subir(base, headers, nombre, datos, tipo, cache):
    r = requests.post(f"{base}/storage/v1/object/{BUCKET}/{nombre}",
                      headers={**headers, "Content-Type": tipo, "x-upsert": "true", "cache-control": cache},
                      data=datos, timeout=120)
    if not r.ok:
        raise RuntimeError(f"No se pudo subir {nombre} (HTTP {r.status_code}): {r.text[:300]}")


def _leer_privado(base, headers, ruta):
    r = requests.get(f"{base}/storage/v1/object/{ruta}", headers=headers, timeout=20)
    return r.content if r.status_code == 200 and r.content else None


def _borrar_catalogos_viejos(base, headers, conservar):
    try:
        r = requests.post(f"{base}/storage/v1/object/list/{BUCKET}",
                          headers={**headers, "Content-Type": "application/json"},
                          json={"prefix": "", "limit": 1000}, timeout=20)
        viejos = [o["name"] for o in (r.json() if r.ok else [])
                  if o.get("name", "").startswith("catalogo-") and o["name"] not in conservar]
        if viejos:
            requests.delete(f"{base}/storage/v1/object/{BUCKET}",
                            headers={**headers, "Content-Type": "application/json"},
                            json={"prefixes": viejos}, timeout=30)
    except (requests.RequestException, ValueError):
        pass   # limpieza opcional: si falla, solo quedan archivos de más


# ---------------------------------------------------------------- lectura
def estado():
    """estado.json publicado, o None si nunca se publicó."""
    try:
        r = requests.get(url_publica("estado.json"), params={"t": datetime.now().timestamp()}, timeout=10)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def fuente_activa(base=None, headers=None):
    """'local' (Excel / inventario), 'google' o 'external' (SQL Server)."""
    if base is None:
        base, headers = _conexion()
    r = requests.get(f"{base}/rest/v1/price_source_settings", headers=headers, timeout=20,
                     params={"id": "eq.1", "select": "source_type"})
    if not r.ok:
        raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
    return (r.json() or [{"source_type": "local"}])[0]["source_type"]


def _catalogo_google():
    """Catálogo desde el archivo de Google Drive / Sheets configurado."""
    import google_oauth_source as g
    cfg = g.config()
    if not cfg or not cfg.get("file_id"):
        raise RuntimeError("Configura el archivo de Google en Precios > Google Drive / Sheets.")
    g.read_file.clear()   # leer SIEMPRE la versión actual del archivo
    g.catalog.clear()
    df = g.catalog(cfg["kind"], cfg["file_id"], cfg.get("sheet_name") or "",
                   cfg["code_column"], cfg["name_column"], cfg["price_column"])
    filas = sorted([str(b), str(n), round(float(p), 2)]
                   for b, n, p in df[["barcode", "name", "price"]].itertuples(index=False))
    nombre = "Google " + ("Sheets" if cfg["kind"] == "sheets" else "Drive")
    if cfg.get("sheet_name"):
        nombre += " · " + str(cfg["sheet_name"])
    return nombre, filas


def _catalogo_activo(base, headers):
    """(nombre, [[código, nombre, precio], ...]) de la fuente activa: Excel o Google."""
    fuente = fuente_activa(base, headers)
    if fuente == "google":
        return _catalogo_google()
    if fuente == "external":
        return _catalogo_externo(base, headers)
    return _catalogo_local(base, headers)


def catalogo_externo_info():
    """Fecha y tamaño del último catálogo que envió el conector de Windows, o None."""
    try:
        base, headers = _conexion()
        datos = _leer_privado(base, headers, f"{PRIVADO}/catalogo-externo.json")
        if not datos:
            return None
        d = json.loads(datos)
        return {"generado": d.get("generado"), "productos": len(d.get("productos") or []),
                "inventario": d.get("inventario")}
    except (RuntimeError, ValueError, requests.RequestException):
        return None


def _catalogo_externo(base, headers):
    """SQL Server: el conector de Windows envía la tabla completa cada pocos minutos
    (logo-negocio/catalogo-externo.json). La app no llega a la red del negocio."""
    datos = _leer_privado(base, headers, f"{PRIVADO}/catalogo-externo.json")
    if not datos:
        raise RuntimeError("El conector de Windows todavía no envió el catálogo de SQL Server. Actualízalo a "
                           "la versión 5 y déjalo encendido: lo envía cada 15 minutos.")
    d = json.loads(datos)
    productos = d.get("productos") or []
    if not productos:
        raise RuntimeError("El catálogo que envió el conector está vacío.")
    return d.get("inventario") or "SQL Server", productos


def _catalogo_local(base, headers):
    """(nombre del inventario, [[código, nombre, precio], ...]) del inventario activo."""
    inv = requests.get(f"{base}/rest/v1/price_inventories", headers=headers, timeout=20,
                       params={"select": "id,name", "is_active": "eq.true", "limit": 1})
    if not inv.ok:
        raise RuntimeError(f"Supabase {inv.status_code}: {inv.text[:300]}")
    if not inv.json():
        raise RuntimeError("No hay un inventario activo. Activa uno en Precios > Inventarios (Excel).")
    inventario = inv.json()[0]
    filas, desde = [], 0
    while True:
        r = requests.get(f"{base}/rest/v1/price_inventory_items", headers=headers, timeout=60,
                         params={"select": "barcode,name,price", "inventory_id": f"eq.{inventario['id']}",
                                 "order": "barcode.asc", "limit": 1000, "offset": desde})
        if not r.ok:
            raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
        lote = r.json()
        if not lote:
            break
        filas += [[str(f["barcode"]), str(f["name"] or ""), round(float(f["price"] or 0), 2)] for f in lote]
        desde += len(lote)
    return inventario["name"], filas


# ---------------------------------------------------------------- clave de salida
def _verificacion(clave):
    sal = os.urandom(16)
    huella = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, ITERACIONES)
    return {"algoritmo": "PBKDF2-SHA256", "iteraciones": ITERACIONES, "sal": sal.hex(), "hash": huella.hex()}


def comprobar_clave(clave, verificacion):
    """Misma comprobación que hará el equipo sin internet (útil para pruebas)."""
    if not verificacion:
        return False
    huella = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), bytes.fromhex(verificacion["sal"]),
                                 int(verificacion["iteraciones"]))
    return huella.hex() == verificacion["hash"]


def hay_clave_salida():
    base, headers = _conexion()
    return _leer_privado(base, headers, CLAVE_SALIDA) is not None


def guardar_clave_salida(clave):
    clave = str(clave or "")
    if len(clave) < LARGO_MINIMO_CLAVE:
        raise ValueError(f"La clave de salida debe tener al menos {LARGO_MINIMO_CLAVE} caracteres.")
    base, headers = _conexion()
    datos = json.dumps({**_verificacion(clave),
                        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds")}).encode("utf-8")
    r = requests.post(f"{base}/storage/v1/object/{CLAVE_SALIDA}",
                      headers={**headers, "Content-Type": "application/json", "x-upsert": "true"},
                      data=datos, timeout=15)
    if not r.ok and "bucket" in r.text.lower() and "not found" in r.text.lower():
        requests.post(f"{base}/storage/v1/bucket", headers={**headers, "Content-Type": "application/json"},
                      json={"id": PRIVADO, "name": PRIVADO, "public": False}, timeout=15)
        r = requests.post(f"{base}/storage/v1/object/{CLAVE_SALIDA}",
                          headers={**headers, "Content-Type": "application/json", "x-upsert": "true"},
                          data=datos, timeout=15)
    if not r.ok:
        raise RuntimeError(f"No se pudo guardar la clave de salida (HTTP {r.status_code}): {r.text[:300]}")


# ---------------------------------------------------------------- app de los equipos
APP_EQUIPOS = f"{PRIVADO}/equipos-app.json"


def app_equipos():
    """Dirección de la app sin internet (GitHub Pages) guardada por el administrador, o ""."""
    try:
        base, headers = _conexion()
        datos = _leer_privado(base, headers, APP_EQUIPOS)
        return str(json.loads(datos).get("url") or "") if datos else ""
    except (RuntimeError, ValueError, requests.RequestException):
        return ""


def guardar_app_equipos(direccion):
    from urllib.parse import urlsplit
    direccion = str(direccion or "").strip()
    partes = urlsplit(direccion)
    if partes.scheme != "https" or not partes.netloc:
        raise ValueError("Escribe la dirección completa, empezando por https://")
    direccion = f"https://{partes.netloc}{partes.path.rstrip('/')}/"
    base, headers = _conexion()
    r = requests.post(f"{base}/storage/v1/object/{APP_EQUIPOS}",
                      headers={**headers, "Content-Type": "application/json", "x-upsert": "true"},
                      data=json.dumps({"url": direccion}).encode("utf-8"), timeout=15)
    if not r.ok:
        raise RuntimeError(f"No se pudo guardar la dirección (HTTP {r.status_code}): {r.text[:300]}")
    return direccion


def enlace_instalacion(direccion_app):
    from urllib.parse import quote
    return f"{direccion_app}?estado={quote(url_publica('estado.json'), safe='')}"


def _app_en_linea():
    """Dirección de esta app de Streamlit (para el botón 'Abrir la app en línea' del equipo)."""
    try:
        import streamlit as st
        from urllib.parse import urlsplit
        partes = urlsplit(st.context.url)
        return f"{partes.scheme}://{partes.netloc}/" if partes.netloc else None
    except Exception:
        return None


# ---------------------------------------------------------------- publicar
def publicar(apariencia_actual=None):
    """Publica catálogo, apariencia, logo, QR y clave de salida. Devuelve el estado publicado."""
    base, headers = _conexion()
    _asegurar_bucket(base, headers)
    anterior = estado() or {}

    inventario, productos = _catalogo_activo(base, headers)
    contenido = json.dumps(productos, ensure_ascii=False, separators=(",", ":"))
    version = hashlib.sha256((inventario + "\n" + contenido).encode("utf-8")).hexdigest()[:16]
    archivo = f"catalogo-{version}.json"
    if anterior.get("version") != version:
        catalogo = ('{"formato":%d,"version":"%s","inventario":%s,"productos":%s}'
                    % (FORMATO, version, json.dumps(inventario, ensure_ascii=False), contenido))
        _subir(base, headers, archivo, catalogo.encode("utf-8"), "application/json",
               "max-age=31536000")   # nombre único por versión: se puede guardar para siempre

    imagenes = {}
    for clave, origen, destino in (("logo", f"{PRIVADO}/logo.png", "logo.png"),
                                   ("qr", f"{PRIVADO}/qr-movil.png", "qr.png")):
        datos = _leer_privado(base, headers, origen)
        if datos:
            huella = hashlib.sha256(datos).hexdigest()[:12]
            if not str(anterior.get(clave) or "").endswith(huella):
                _subir(base, headers, destino, datos, "image/png", "max-age=60")
            imagenes[clave] = f"{destino}?v={huella}"
        else:
            imagenes[clave] = None

    if apariencia_actual is None:
        import apariencia
        apariencia_actual = apariencia.obtener()
    salida = _leer_privado(base, headers, CLAVE_SALIDA)
    salida = {k: v for k, v in json.loads(salida).items() if k != "fecha"} if salida else None

    publicado = {
        "formato": FORMATO,
        "version": version,
        "catalogo": archivo,
        "inventario": inventario,
        "productos": len(productos),
        # Fecha del último CAMBIO de precios (no de la última revisión).
        "publicado": (anterior.get("publicado") if anterior.get("version") == version
                      else datetime.now(timezone.utc).isoformat(timespec="seconds")),
        "apariencia": dict(apariencia_actual),
        "logo": imagenes["logo"],
        "qr": imagenes["qr"],
        "salida": salida,
        "app_en_linea": _app_en_linea() or anterior.get("app_en_linea"),
        # Para que los equipos suban su registro de consultas hechas sin internet.
        # La clave pública solo permite AGREGAR filas 'offline-*' (ver MIGRACION_004).
        "registro": {"url": base, "clave": clave_publica()} if clave_publica() else None,
    }
    if publicado == anterior:
        return anterior          # nada cambió: no se reescribe nada
    _subir(base, headers, "estado.json", json.dumps(publicado, ensure_ascii=False).encode("utf-8"),
           "application/json", "no-cache")
    _borrar_catalogos_viejos(base, headers, {archivo, anterior.get("catalogo")})
    return publicado


def actualizar_si_publicado():
    """Tras cambiar precios, logo, QR o apariencia: si los equipos ya están en uso,
    republicar. Devuelve (True, estado) | (False, None si nunca se publicó) | (False, 'error')."""
    if estado() is None:
        return False, None
    try:
        return True, publicar()
    except Exception as exc:  # nunca debe romper la página que llamó
        return False, str(exc)


# ---------------------------------------------------------------- estado de los equipos
def equipos():
    """Equipos que reportaron (tabla device_status, MIGRACION_005), más recientes primero."""
    base, headers = _conexion()
    r = requests.get(f"{base}/rest/v1/device_status", headers=headers, timeout=20,
                     params={"select": "*", "order": "ultima_vez.desc", "limit": 200})
    if not r.ok:
        raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
    return r.json()


def olvidar_equipo(device_id):
    base, headers = _conexion()
    r = requests.delete(f"{base}/rest/v1/device_status", headers=headers, timeout=20,
                        params={"device_id": f"eq.{device_id}"})
    if not r.ok:
        raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
