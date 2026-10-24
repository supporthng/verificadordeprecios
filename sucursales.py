"""Sucursales: tiendas del negocio, su fuente de precios y su ubicación.

- Los inventarios se cargan y se identifican en Precios › Inventarios (Excel).
- Cada sucursal ELIGE su fuente de precios: la misma de la Principal, uno de los inventarios,
  Google Drive / Sheets o SQL Server (guardado en sucursales.excepciones_config["fuente"]).
- Un usuario con sucursal_id es encargado de esa sucursal y solo ve lo suyo; sin
  sucursal_id es usuario general (ve todo).
Requiere sql/MIGRACION_006_sucursales.sql. Sin ella todo sigue funcionando como antes
(una sola tienda).
"""
import math
import re
import unicodedata

import requests
import streamlit as st

from codigos_barras import variantes_codigo
from supabase_cliente import cabeceras, clave_servidor, url

LOTE = 500


def _api(metodo, tabla, params=None, datos=None, prefer="return=representation"):
    base, clave = url(), clave_servidor()
    if not base or not clave:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SECRET_KEY en Secrets.")
    r = requests.request(metodo, f"{base}/rest/v1/{tabla}", params=params, json=datos, timeout=30,
                         headers=cabeceras(clave, {"Content-Type": "application/json", "Prefer": prefer}))
    if not r.ok:
        raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else []


def instalado():
    """True si ya se ejecutó MIGRACION_006 (existe la tabla de sucursales)."""
    try:
        listar()
        return True
    except RuntimeError:
        return False


@st.cache_data(ttl=30, show_spinner=False)
def listar(solo_activas=False):
    params = {"select": "*", "order": "nombre.asc"}
    if solo_activas:
        params["activa"] = "eq.true"
    return _api("GET", "sucursales", params)


def limpiar_cache():
    listar.clear()
    _excepciones.clear()


def por_id(sucursal_id):
    if not sucursal_id:
        return None
    try:
        return next((s for s in listar() if s["id"] == sucursal_id), None)
    except RuntimeError:
        return None


def por_codigo(codigo):
    if not codigo:
        return None
    try:
        return next((s for s in listar() if s["codigo"] == codigo), None)
    except RuntimeError:
        return None


def codigo_desde_nombre(nombre):
    t = unicodedata.normalize("NFKD", str(nombre or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return (t or "sucursal")[:30]


def guardar(datos, sucursal_id=None):
    """Crea (sin id) o actualiza una sucursal. Devuelve la fila."""
    permitidos = {"codigo", "nombre", "activa", "geo_enabled", "latitude", "longitude", "radius_m",
                  "excepciones_fuente", "excepciones_config"}
    fila = {k: v for k, v in datos.items() if k in permitidos}
    if sucursal_id:
        res = _api("PATCH", "sucursales", {"id": f"eq.{sucursal_id}"}, fila)
    else:
        res = _api("POST", "sucursales", datos=fila)
    limpiar_cache()
    return res[0] if res else None


def usuarios_de(sucursal_id):
    return _api("GET", "verificador_usuarios", {"select": "id,username,active", "sucursal_id": f"eq.{sucursal_id}"})


def eliminar(sucursal_id):
    """Borra la sucursal y sus precios propios. No se permite si tiene usuarios: al quedar sin
    sucursal pasarían a ser usuarios GENERALES (con acceso a todo)."""
    usuarios = usuarios_de(sucursal_id)
    if usuarios:
        raise RuntimeError("La sucursal tiene usuarios (" + ", ".join(u["username"] for u in usuarios[:6])
                           + "). Pásalos a otra sucursal o elimínalos en Usuarios antes de borrarla.")
    _api("DELETE", "sucursales", {"id": f"eq.{sucursal_id}"}, prefer="return=minimal")
    limpiar_cache()


# ---------------------------------------------------------------- usuarios
def de_usuario(usuario):
    """Sucursal del usuario (encargado), o None si es general."""
    return por_id((usuario or {}).get("sucursal_id"))


def es_general(usuario):
    return bool(usuario) and not usuario.get("sucursal_id")


# ---------------------------------------------------------------- la Principal
def nombre_principal():
    """Nombre que se le dio a la Principal (Sucursales › Principal › Datos), o «Principal»."""
    try:
        import apariencia
        return apariencia.obtener().get("nombre_principal") or "Principal"
    except Exception:
        return "Principal"


# ---------------------------------------------------------------- fuente de precios
FUENTES = ("principal", "inventario", "google", "external")


CAMPOS_GOOGLE = ("kind", "file_id", "file_name", "sheet_name", "code_column", "name_column", "price_column")


def fuente(sucursal):
    """Fuente de precios de la sucursal:
    {"tipo": principal|inventario|google|external, "inventario_id": int|None,
     "google": {kind, file_id, file_name, sheet_name, code_column, name_column, price_column}|None,
     "external_id": id de la configuración de SQL Server|None}.
    Una elección incompleta (sin inventario, sin archivo o sin configuración) vale como «Principal»."""
    cfg = (sucursal or {}).get("excepciones_config") or {}
    tipo = cfg.get("fuente") if cfg.get("fuente") in FUENTES else "principal"
    inv = cfg.get("inventario_id")
    try:
        inv = int(inv) if inv is not None else None
    except (TypeError, ValueError):
        inv = None
    google = cfg.get("google") if isinstance(cfg.get("google"), dict) else None
    if google:
        google = {k: str(google.get(k) or "") for k in CAMPOS_GOOGLE}
    externa = str(cfg.get("external_id") or "") or None
    if (tipo == "inventario" and inv is None) \
            or (tipo == "google" and not (google and google["file_id"] and google["code_column"]
                                          and google["name_column"] and google["price_column"])) \
            or (tipo == "external" and not externa):
        tipo = "principal"
    return {"tipo": tipo,
            "inventario_id": inv if tipo == "inventario" else None,
            "google": google if tipo == "google" else None,
            "external_id": externa if tipo == "external" else None}


def guardar_fuente(sucursal, tipo, inventario_id=None, google=None, external_id=None):
    if tipo not in FUENTES:
        raise ValueError("Fuente desconocida.")
    cfg = dict(sucursal.get("excepciones_config") or {})
    cfg.update({"fuente": tipo,
                "inventario_id": int(inventario_id) if tipo == "inventario" and inventario_id is not None else None,
                "google": {k: str((google or {}).get(k) or "") for k in CAMPOS_GOOGLE} if tipo == "google" else None,
                "external_id": str(external_id) if tipo == "external" and external_id else None})
    return guardar({"excepciones_config": cfg,
                    "excepciones_fuente": {"google": "google", "external": "external"}.get(tipo, "excel")},
                   sucursal["id"])


def que_usan_externa(config_id):
    """Sucursales que usan esa configuración de SQL Server."""
    try:
        return [s for s in listar() if fuente(s)["external_id"] == str(config_id)]
    except RuntimeError:
        return []


def que_usan_inventario(inventario_id):
    """Sucursales cuya fuente es ese inventario."""
    try:
        return [s for s in listar() if fuente(s)["inventario_id"] == int(inventario_id)]
    except RuntimeError:
        return []


# ---------------------------------------------------------------- excepciones de precio (versión anterior)
def contar_excepciones(sucursal_id):
    base, clave = url(), clave_servidor()
    r = requests.head(f"{base}/rest/v1/sucursal_precios", timeout=15,
                      params={"select": "barcode", "sucursal_id": f"eq.{sucursal_id}"},
                      headers=cabeceras(clave, {"Prefer": "count=exact", "Range": "0-0"}))
    try:
        return int(r.headers.get("Content-Range", "*/0").split("/")[-1])
    except ValueError:
        return 0


def listar_excepciones(sucursal_id):
    filas, desde = [], 0
    while True:
        lote = _api("GET", "sucursal_precios", {"select": "barcode,name,price", "sucursal_id": f"eq.{sucursal_id}",
                                                 "order": "barcode.asc", "offset": desde, "limit": 1000})
        filas += lote
        if len(lote) < 1000:
            return filas
        desde += len(lote)


def reemplazar_excepciones(sucursal_id, filas):
    """Reemplaza TODAS las excepciones de la sucursal. filas: [{barcode, name|None, price}]."""
    vistos, limpias = set(), []
    for f in filas:
        codigo = str(f.get("barcode") or "").strip()
        if not codigo or codigo in vistos:
            continue
        vistos.add(codigo)
        nombre = f.get("name")
        if nombre is None or (isinstance(nombre, float) and math.isnan(nombre)) or str(nombre).strip().lower() in ("nan", "none"):
            nombre = None
        else:
            nombre = str(nombre).strip()[:200] or None
        limpias.append({"sucursal_id": sucursal_id, "barcode": codigo[:64], "name": nombre,
                        "price": round(float(f["price"]), 2)})
    _api("DELETE", "sucursal_precios", {"sucursal_id": f"eq.{sucursal_id}"}, prefer="return=minimal")
    for i in range(0, len(limpias), LOTE):
        _api("POST", "sucursal_precios", datos=limpias[i:i + LOTE], prefer="return=minimal")
    _excepciones.clear()
    return len(limpias)


@st.cache_data(ttl=30, show_spinner=False)
def _excepciones(sucursal_id):
    return {f["barcode"]: f for f in listar_excepciones(sucursal_id)}


def aplicar(producto, codigo, sucursal):
    """Precio de la sucursal para un código: la excepción manda sobre el catálogo general.

    producto: lo que encontró el catálogo general ({barcode, name, price}) o None.
    Devuelve (producto final o None, True si vino de la excepción)."""
    if not sucursal:
        return producto, False
    try:
        excepciones = _excepciones(sucursal["id"])
    except RuntimeError:
        return producto, False
    for forma in variantes_codigo(codigo) + ([str(producto.get("barcode"))] if producto else []):
        fila = excepciones.get(forma)
        if fila:
            nombre = fila.get("name") or (producto or {}).get("name") or ""
            return {"barcode": fila["barcode"], "name": nombre, "price": float(fila["price"])}, True
    return producto, False


# ---------------------------------------------------------------- ubicación
def _distancia_m(a_lat, a_lon, b_lat, b_lon):
    r = 6371000
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def con_ubicacion():
    try:
        return [s for s in listar(solo_activas=True)
                if s.get("geo_enabled") and s.get("latitude") is not None and s.get("longitude") is not None]
    except RuntimeError:
        return []


def por_ubicacion(lat, lon, precision=0):
    """La sucursal (activa y con ubicación) en cuya zona está el punto, la más cercana si hay varias.
    Devuelve (sucursal o None, distancia en metros a la más cercana o None)."""
    try:
        lat, lon, precision = float(lat), float(lon), float(precision or 0)
    except (TypeError, ValueError):
        return None, None
    mejor, distancia = None, None
    for s in con_ubicacion():
        d = _distancia_m(lat, lon, s["latitude"], s["longitude"])
        if distancia is None or d < distancia:
            mejor, distancia = s, d
    if mejor is not None and distancia - min(precision, 150) <= mejor["radius_m"]:
        return mejor, distancia
    return None, distancia
