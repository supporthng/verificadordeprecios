"""Respaldo y restauración de todo el sistema (base de datos de Supabase + archivos privados).

El respaldo es un ZIP con:
- manifest.json: fecha, versión del formato y cuántas filas/archivos trae cada parte.
- tablas/<tabla>.json: las filas de cada tabla.
- archivos/<ruta>: los archivos del almacenamiento privado (apariencia, logo, QR, fotos…).

Restaurar escribe encima (upsert): lo que existe se actualiza con lo del respaldo y lo que no
está en el respaldo se deja como está. Los inventarios se emparejan por NOMBRE (su número
interno lo asigna la base de datos) y se ajustan las sucursales que los usan.

Respaldos automáticos: publicar_automatico.py (GitHub Actions) llama a automatico() y guarda
uno por día en el almacenamiento privado "respaldos", conservando los últimos 14.
"""
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import requests

from supabase_cliente import cabeceras, clave_servidor, url

FORMATO = 1
PRIVADO = "logo-negocio"
BUCKET_RESPALDOS = "respaldos"
CONSERVAR_AUTOMATICOS = 14

# (tabla, clave para escribir encima, ¿opcional?, descripción)
TABLAS = [
    ("price_source_settings", "id", False, "Fuente de precios de la Principal"),
    ("mobile_geo_settings", "id", False, "Ubicación de la Principal"),
    ("google_price_source", "id", False, "Archivo y cuenta de Google"),
    ("external_price_sources", "id", False, "Configuraciones de SQL Server"),
    ("price_inventories", "name", False, "Inventarios"),
    ("price_inventory_items", None, False, "Productos de los inventarios"),
    ("sucursales", "id", False, "Sucursales"),
    ("sucursal_precios", "sucursal_id,barcode", False, "Precios propios (versión anterior)"),
    ("verificador_usuarios", "username", False, "Usuarios"),
    ("price_lookup_log", None, True, "Registro de consultas"),
]
PARTES = {
    "configuracion": ("⚙️ Configuración (fuentes, Google, SQL Server, ubicación)",
                      ["price_source_settings", "mobile_geo_settings", "google_price_source", "external_price_sources"]),
    "inventarios": ("📚 Inventarios y sus productos", ["price_inventories", "price_inventory_items"]),
    "sucursales": ("🏬 Sucursales", ["sucursales", "sucursal_precios"]),
    "usuarios": ("👥 Usuarios", ["verificador_usuarios"]),
    "registro": ("📊 Registro de consultas", ["price_lookup_log"]),
    "archivos": ("🎨 Apariencia, logo, QR y fotos", []),
}
# Archivos privados que NO se respaldan: los regenera el conector o son de un solo uso.
EXCLUIR = ("catalogo-externo", "conector-clave")
CARPETAS_FOTOS = ("imagenes-productos/", "fotos/")


def _conexion():
    base, clave = url(), clave_servidor()
    if not base or not clave:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SECRET_KEY en Secrets.")
    return base, cabeceras(clave)


def _rest(metodo, tabla, params=None, datos=None, prefer=None):
    base, h = _conexion()
    headers = {**h, "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    r = requests.request(metodo, f"{base}/rest/v1/{tabla}", params=params, json=datos, headers=headers, timeout=60)
    if not r.ok:
        raise RuntimeError(f"{tabla}: Supabase {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else []


def _leer_tabla(tabla):
    filas, desde = [], 0
    while True:
        try:
            lote = _rest("GET", tabla, {"select": "*", "limit": 1000, "offset": desde})
        except RuntimeError as exc:
            if "404" in str(exc) or "42P01" in str(exc) or "PGRST205" in str(exc):
                return None          # la tabla no existe en esta instalación
            raise
        filas += lote
        if len(lote) < 1000:
            return filas
        desde += len(lote)


# ---------------------------------------------------------------- archivos privados
def _listar(bucket, prefijo=""):
    """Rutas de todos los archivos del almacenamiento (recorre las carpetas)."""
    base, h = _conexion()
    rutas, desde = [], 0
    while True:
        r = requests.post(f"{base}/storage/v1/object/list/{bucket}", headers={**h, "Content-Type": "application/json"},
                          json={"prefix": prefijo, "limit": 1000, "offset": desde,
                                "sortBy": {"column": "name", "order": "asc"}}, timeout=30)
        if not r.ok:
            return rutas
        lote = r.json()
        for o in lote:
            ruta = f"{prefijo}{o['name']}"
            if o.get("id") is None:          # carpeta
                rutas += _listar(bucket, ruta + "/")
            else:
                rutas.append((ruta, (o.get("metadata") or {}).get("size") or 0, o.get("updated_at") or o.get("created_at")))
        if len(lote) < 1000:
            return rutas
        desde += len(lote)


def _descargar(bucket, ruta):
    base, h = _conexion()
    r = requests.get(f"{base}/storage/v1/object/{bucket}/{ruta}", headers=h, timeout=60)
    return r.content if r.status_code == 200 else None


def _subir(bucket, ruta, datos, tipo="application/octet-stream"):
    base, h = _conexion()
    r = requests.post(f"{base}/storage/v1/object/{bucket}/{ruta}",
                      headers={**h, "Content-Type": tipo, "x-upsert": "true"}, data=datos, timeout=120)
    if not r.ok and "bucket" in r.text.lower() and "not found" in r.text.lower():
        requests.post(f"{base}/storage/v1/bucket", headers={**h, "Content-Type": "application/json"},
                      json={"id": bucket, "name": bucket, "public": False}, timeout=15)
        r = requests.post(f"{base}/storage/v1/object/{bucket}/{ruta}",
                          headers={**h, "Content-Type": tipo, "x-upsert": "true"}, data=datos, timeout=120)
    if not r.ok:
        raise RuntimeError(f"No se pudo guardar {ruta} (HTTP {r.status_code}): {r.text[:200]}")


def _tipo(ruta):
    ext = ruta.rsplit(".", 1)[-1].lower()
    return {"json": "application/json", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "svg": "image/svg+xml"}.get(ext, "application/octet-stream")


# ---------------------------------------------------------------- crear
def crear(incluir_registro=False, incluir_fotos=True, progreso=None):
    """Arma el respaldo y devuelve (bytes del ZIP, manifest)."""
    paso = progreso or (lambda texto: None)
    manifest = {"formato": FORMATO, "creado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "tablas": {}, "archivos": 0, "incluye_registro": bool(incluir_registro),
                "incluye_fotos": bool(incluir_fotos)}
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        for tabla, _, opcional, descripcion in TABLAS:
            if tabla == "price_lookup_log" and not incluir_registro:
                continue
            paso(f"Leyendo {descripcion.lower()}…")
            filas = _leer_tabla(tabla)
            if filas is None:
                continue
            manifest["tablas"][tabla] = len(filas)
            z.writestr(f"tablas/{tabla}.json", json.dumps(filas, ensure_ascii=False, default=str))
        paso("Copiando apariencia, logo, QR y fotos…")
        for ruta, _, _ in _listar(PRIVADO):
            if any(ruta.startswith(x) for x in EXCLUIR):
                continue
            if not incluir_fotos and ruta.startswith(CARPETAS_FOTOS):
                continue
            datos = _descargar(PRIVADO, ruta)
            if datos is not None:
                z.writestr(f"archivos/{ruta}", datos)
                manifest["archivos"] += 1
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return salida.getvalue(), manifest


def nombre_archivo(manifest, prefijo="respaldo"):
    fecha = datetime.fromisoformat(manifest["creado"]).astimezone(timezone(timedelta(hours=-4)))
    return f"{prefijo}-{fecha:%Y%m%d-%H%M}.zip"


# ---------------------------------------------------------------- leer un respaldo
def leer(datos):
    """Abre un respaldo y devuelve (manifest, {tabla: filas}, {ruta: bytes}). Valida el formato."""
    try:
        z = zipfile.ZipFile(io.BytesIO(datos))
        manifest = json.loads(z.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise ValueError("Este archivo no es un respaldo del sistema (falta manifest.json).")
    if manifest.get("formato") != FORMATO:
        raise ValueError(f"Formato de respaldo desconocido ({manifest.get('formato')}).")
    validas = {t for t, *_ in TABLAS}
    tablas, archivos = {}, {}
    for nombre in z.namelist():
        if nombre.startswith("tablas/") and nombre.endswith(".json"):
            tabla = nombre[7:-5]
            if tabla in validas:
                tablas[tabla] = json.loads(z.read(nombre))
        elif nombre.startswith("archivos/") and not nombre.endswith("/"):
            ruta = nombre[9:]
            if ".." not in ruta.split("/") and not any(ruta.startswith(x) for x in EXCLUIR):
                archivos[ruta] = z.read(nombre)
    return manifest, tablas, archivos


def resumen(manifest, tablas, archivos):
    """Filas para mostrar qué trae cada parte."""
    filas = []
    for clave, (titulo, lista) in PARTES.items():
        if clave == "archivos":
            n = len(archivos)
            detalle = f"{n} archivo(s)"
        else:
            n = sum(len(tablas.get(t) or []) for t in lista)
            detalle = ", ".join(f"{len(tablas[t]):,} {d.lower()}" for t, _, _, d in TABLAS if t in lista and t in tablas)
        if n:
            filas.append({"clave": clave, "Parte": titulo, "Contenido": detalle or "—"})
    return filas


# ---------------------------------------------------------------- restaurar
def _escribir(tabla, filas, clave):
    for i in range(0, len(filas), 500):
        _rest("POST", tabla, {"on_conflict": clave} if clave else None, filas[i:i + 500],
              prefer=("resolution=merge-duplicates," if clave else "") + "return=minimal")


def restaurar(datos, partes, progreso=None):
    """Restaura las partes elegidas de un respaldo. Devuelve una lista de textos con lo hecho."""
    paso = progreso or (lambda texto: None)
    manifest, tablas, archivos = leer(datos)
    hecho = []

    if "configuracion" in partes:
        for tabla in PARTES["configuracion"][1]:
            filas = tablas.get(tabla)
            if filas:
                paso(f"Restaurando {tabla}…")
                if tabla == "external_price_sources":
                    # La habilitada se marca al final (solo puede haber una).
                    _escribir(tabla, [{**f, "enabled": False} for f in filas], "id")
                    activa = next((f for f in filas if f.get("enabled")), None)
                    if activa:
                        _rest("PATCH", tabla, {"enabled": "eq.true"}, {"enabled": False}, prefer="return=minimal")
                        _rest("PATCH", tabla, {"id": f"eq.{activa['id']}"}, {"enabled": True}, prefer="return=minimal")
                else:
                    _escribir(tabla, filas, "id")
                hecho.append(next(d for t, _, _, d in TABLAS if t == tabla))

    mapa_inventarios = {}
    if "inventarios" in partes and tablas.get("price_inventories"):
        invs = tablas["price_inventories"]
        paso("Restaurando inventarios…")
        _escribir("price_inventories", [{"name": i["name"]} for i in invs], "name")
        actuales = {i["name"]: int(i["id"]) for i in _rest("GET", "price_inventories", {"select": "id,name"})}
        mapa_inventarios = {int(i["id"]): actuales[i["name"]] for i in invs if i["name"] in actuales}
        productos = {}
        for p in tablas.get("price_inventory_items") or []:
            nuevo = mapa_inventarios.get(int(p["inventory_id"]))
            if nuevo is not None:
                productos.setdefault(nuevo, []).append({"barcode": p["barcode"], "name": p["name"],
                                                        "price": float(p["price"])})
        for viejo, nuevo in mapa_inventarios.items():
            nombre = next(i["name"] for i in invs if int(i["id"]) == viejo)
            paso(f"Restaurando los productos de «{nombre}»…")
            lista = productos.get(nuevo, [])
            _rest("POST", "rpc/replace_price_inventory", datos={"target_id": nuevo, "new_items": lista})
            hecho.append(f"Inventario «{nombre}»: {len(lista):,} productos")
        activo = next((i for i in invs if i.get("is_active")), None)
        if activo and int(activo["id"]) in mapa_inventarios:
            _rest("POST", "rpc/activate_price_inventory", datos={"target_id": mapa_inventarios[int(activo["id"])]})
            hecho.append(f"La Principal usa «{activo['name']}»")

    if "sucursales" in partes and tablas.get("sucursales"):
        paso("Restaurando sucursales…")
        filas = []
        for s in tablas["sucursales"]:
            s = dict(s)
            cfg = dict(s.get("excepciones_config") or {})
            if cfg.get("inventario_id") is not None:
                # Su inventario puede tener otro número interno en esta base de datos.
                viejo = int(cfg["inventario_id"])
                if mapa_inventarios:
                    cfg["inventario_id"] = mapa_inventarios.get(viejo, viejo)
                else:
                    nombre = next((i["name"] for i in tablas.get("price_inventories") or []
                                   if int(i["id"]) == viejo), None)
                    if nombre:
                        hallado = _rest("GET", "price_inventories", {"select": "id", "name": f"eq.{nombre}"})
                        if hallado:
                            cfg["inventario_id"] = int(hallado[0]["id"])
            s["excepciones_config"] = cfg
            filas.append(s)
        _escribir("sucursales", filas, "id")
        hecho.append(f"{len(filas)} sucursal(es)")
        if tablas.get("sucursal_precios"):
            _escribir("sucursal_precios", tablas["sucursal_precios"], "sucursal_id,barcode")
        try:
            import sucursales
            sucursales.limpiar_cache()
        except Exception:
            pass

    if "usuarios" in partes and tablas.get("verificador_usuarios"):
        paso("Restaurando usuarios…")
        filas = [{k: v for k, v in u.items() if k != "id"} for u in tablas["verificador_usuarios"]]
        _escribir("verificador_usuarios", filas, "username")
        hecho.append(f"{len(filas)} usuario(s)")

    if "registro" in partes and tablas.get("price_lookup_log"):
        paso("Restaurando el registro de consultas…")
        # Solo las consultas que no están (misma fecha y código), para no duplicar al restaurar dos veces.
        filas = tablas["price_lookup_log"]
        desde = min(str(f["created_at"]) for f in filas)
        existentes = set()
        pagina = 0
        while True:
            lote = _rest("GET", "price_lookup_log", {"select": "created_at,barcode", "created_at": f"gte.{desde}",
                                                      "limit": 1000, "offset": pagina})
            existentes |= {(str(x["created_at"])[:19], x["barcode"]) for x in lote}
            if len(lote) < 1000:
                break
            pagina += len(lote)
        nuevas = [{k: v for k, v in f.items() if k != "id"} for f in filas
                  if (str(f["created_at"])[:19], f["barcode"]) not in existentes]
        _escribir("price_lookup_log", nuevas, None)
        hecho.append(f"{len(nuevas):,} consulta(s) agregadas al registro")

    if "archivos" in partes and archivos:
        paso("Restaurando apariencia, logo, QR y fotos…")
        for ruta, contenido in archivos.items():
            _subir(PRIVADO, ruta, contenido, _tipo(ruta))
        hecho.append(f"{len(archivos)} archivo(s)")
        try:
            import apariencia
            apariencia.obtener.clear()
        except Exception:
            pass

    paso("Enviando los cambios a los equipos…")
    try:
        import publicar_equipos
        publicar_equipos.actualizar_si_publicado()
    except Exception:
        pass
    return hecho


# ---------------------------------------------------------------- respaldos automáticos
def automaticos():
    """[(nombre, tamaño, fecha)] de los respaldos guardados en la nube, el más nuevo primero."""
    lista = [x for x in _listar(BUCKET_RESPALDOS) if x[0].endswith(".zip")]
    return sorted(lista, key=lambda x: x[0], reverse=True)


def descargar_automatico(nombre):
    return _descargar(BUCKET_RESPALDOS, nombre)


def guardar_en_la_nube(datos, manifest, prefijo="respaldo"):
    nombre = nombre_archivo(manifest, prefijo)
    _subir(BUCKET_RESPALDOS, nombre, datos, "application/zip")
    return nombre


def automatico(horas=20):
    """Uno por día (lo llama GitHub Actions cada 30 min): si el último tiene menos de `horas`, no hace nada.
    Incluye todo menos el registro de consultas (que puede ser muy grande). Devuelve el nombre del respaldo creado o None."""
    existentes = [x for x in automaticos() if x[0].startswith("auto-")]
    if existentes:
        try:
            ultimo = datetime.strptime(existentes[0][0][5:18], "%Y%m%d-%H%M").replace(tzinfo=timezone(timedelta(hours=-4)))
            if datetime.now(timezone.utc) - ultimo < timedelta(hours=horas):
                return None
        except ValueError:
            pass
    datos, manifest = crear(incluir_registro=False, incluir_fotos=True)
    nombre = guardar_en_la_nube(datos, manifest, "auto")
    viejos = [x[0] for x in automaticos() if x[0].startswith("auto-")][CONSERVAR_AUTOMATICOS:]
    if viejos:
        base, h = _conexion()
        requests.delete(f"{base}/storage/v1/object/{BUCKET_RESPALDOS}", headers={**h, "Content-Type": "application/json"},
                        json={"prefixes": viejos}, timeout=30)
    return nombre
