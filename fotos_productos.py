"""Fotos de productos que se alimentan solas desde internet.

Cuando un producto se consulta por primera vez y no tiene foto, se busca por su código de
barras en las bases abiertas de Open Food Facts (alimentos, belleza, mascotas y otros
productos). Si aparece, se guarda una copia en el almacenamiento del negocio y desde ahí
se usa siempre: en la Consulta en línea y en los equipos sin internet (que la descargan).
Si no aparece, se anota y se vuelve a intentar a los 30 días.

Prioridad: la foto subida a mano en Apariencia > Fotos de productos gana siempre.

Almacenamiento (Supabase Storage):
  imagenes-productos/<código>.png            fotos subidas a mano (privado)
  imagenes-productos/internet/<código>.jpg   fotos encontradas en internet (privado)
  logo-negocio/fotos-indice.json             códigos sin foto, rechazadas, pendientes
  equipos/fotos/<código>-<huella>.<ext>      copia pública para los equipos sin internet
  equipos/fotos.json                         {código: archivo} para los equipos

No depende de Streamlit para trabajar (lo usa también GitHub Actions).
"""
import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO

import requests

from codigos_barras import variantes_codigo
from supabase_cliente import cabeceras, clave_servidor, url

BUCKET = "imagenes-productos"
CARPETA_INTERNET = "internet"
INDICE = "logo-negocio/fotos-indice.json"
PUBLICO = "equipos"
MAPA_PUBLICO = "fotos.json"
REINTENTAR_DIAS = 30
MAX_POR_VUELTA = 40          # búsquedas por ejecución (las bases abiertas piden moderación)
MAX_BYTES = 4 * 1024 * 1024
LADO_MAXIMO = 480            # px: suficiente para la pantalla, liviano para los equipos
AGENTE = "ConsultaPrecios/1.0 (verificador de precios; github.com/supporthng/verificadordeprecios)"
FUENTES = (
    ("Open Food Facts", "https://world.openfoodfacts.org"),
    ("Open Beauty Facts", "https://world.openbeautyfacts.org"),
    ("Open Products Facts", "https://world.openproductsfacts.org"),
    ("Open Pet Food Facts", "https://world.openpetfoodfacts.org"),
)
CAMPOS_IMAGEN = ("image_front_url", "image_url", "image_front_small_url")


def _ahora():
    return datetime.now(timezone.utc)


def _conexion():
    base, clave = url(), clave_servidor()
    if not base or not clave:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SECRET_KEY en Secrets.")
    return base, cabeceras(clave)


def _codigo_valido(codigo):
    codigo = str(codigo or "").strip()
    return codigo if codigo.isdigit() and 6 <= len(codigo) <= 14 else None


# ---------------------------------------------------------------- almacenamiento
def _asegurar_bucket(base, headers, nombre=BUCKET, publico=False):
    r = requests.get(f"{base}/storage/v1/bucket/{nombre}", headers=headers, timeout=15)
    if r.ok:
        return
    requests.post(f"{base}/storage/v1/bucket", headers={**headers, "Content-Type": "application/json"},
                  json={"id": nombre, "name": nombre, "public": publico}, timeout=15)


def _subir(base, headers, ruta, datos, tipo, cache="no-cache"):
    r = requests.post(f"{base}/storage/v1/object/{ruta}",
                      headers={**headers, "Content-Type": tipo, "x-upsert": "true", "cache-control": cache},
                      data=datos, timeout=60)
    if not r.ok:
        raise RuntimeError(f"No se pudo guardar {ruta} (HTTP {r.status_code}): {r.text[:200]}")


def _leer(base, headers, ruta):
    try:
        r = requests.get(f"{base}/storage/v1/object/{ruta}", headers=headers, timeout=20)
    except requests.RequestException:
        return None
    return r.content if r.status_code == 200 and r.content else None


def _borrar(base, headers, bucket, rutas):
    if rutas:
        requests.delete(f"{base}/storage/v1/object/{bucket}", headers={**headers, "Content-Type": "application/json"},
                        json={"prefixes": list(rutas)}, timeout=30)


def _listar(base, headers, bucket, prefijo=""):
    """Archivos de una carpeta: {nombre: huella}. La huella cambia si el archivo cambia."""
    salida, desde = {}, 0
    while True:
        r = requests.post(f"{base}/storage/v1/object/list/{bucket}",
                          headers={**headers, "Content-Type": "application/json"},
                          json={"prefix": prefijo, "limit": 1000, "offset": desde,
                                "sortBy": {"column": "name", "order": "asc"}}, timeout=30)
        if r.status_code in (400, 404):
            return salida          # el almacenamiento todavía no existe
        if not r.ok:
            raise RuntimeError(f"No se pudo listar {bucket}/{prefijo} (HTTP {r.status_code}).")
        lote = r.json()
        for o in lote:
            if o.get("id"):        # las carpetas vienen sin id
                meta = o.get("metadata") or {}
                firma = f"{meta.get('eTag')}|{meta.get('size')}|{o.get('updated_at')}"
                salida[o["name"]] = hashlib.sha1(firma.encode()).hexdigest()[:10]
        if len(lote) < 1000:
            return salida
        desde += len(lote)


def leer_indice(base=None, headers=None):
    if base is None:
        base, headers = _conexion()
    datos = _leer(base, headers, INDICE)
    try:
        indice = json.loads(datos) if datos else {}
    except ValueError:
        indice = {}
    indice.setdefault("sin_foto", {})      # código -> {"fecha", "rechazada"?}
    indice.setdefault("pendientes", [])    # consultados que faltan buscar (límite por vuelta)
    indice.setdefault("revisado_hasta", None)
    indice.setdefault("origen", {})        # código -> {"fuente", "fecha"} de las fotos de internet
    return indice


def guardar_indice(indice, base=None, headers=None):
    if base is None:
        base, headers = _conexion()
    _subir(base, headers, INDICE, json.dumps(indice, ensure_ascii=False).encode("utf-8"), "application/json")


def fotos_guardadas(base=None, headers=None):
    """{código: (ruta privada, huella, origen)}; la foto subida a mano gana."""
    if base is None:
        base, headers = _conexion()
    fotos = {}
    for nombre, huella in _listar(base, headers, BUCKET, f"{CARPETA_INTERNET}/").items():
        codigo = nombre.rsplit(".", 1)[0]
        fotos[codigo] = (f"{BUCKET}/{CARPETA_INTERNET}/{nombre}", huella, "internet")
    for nombre, huella in _listar(base, headers, BUCKET, "").items():
        codigo, _, ext = nombre.rpartition(".")
        if codigo.isdigit() and ext.lower() in ("png", "jpg", "jpeg", "webp"):
            fotos[codigo] = (f"{BUCKET}/{nombre}", huella, "manual")
    return fotos


# ---------------------------------------------------------------- búsqueda en internet
def _reducir(datos):
    """JPEG de máx. 480 px. Sin Pillow (GitHub Actions) se guarda tal cual llegó."""
    try:
        from PIL import Image
    except ImportError:
        return datos, "image/jpeg"
    try:
        with Image.open(BytesIO(datos)) as im:
            im.load()
            if im.mode in ("RGBA", "LA", "P"):
                fondo = Image.new("RGB", im.size, "white")
                im = im.convert("RGBA")
                fondo.paste(im, mask=im.split()[-1])
                im = fondo
            else:
                im = im.convert("RGB")
            im.thumbnail((LADO_MAXIMO, LADO_MAXIMO))
            salida = BytesIO()
            im.save(salida, format="JPEG", quality=82, optimize=True)
            return salida.getvalue(), "image/jpeg"
    except (OSError, ValueError):
        return None, None


def _descargar_imagen(direccion):
    if not str(direccion).startswith("https://"):
        return None
    r = requests.get(direccion, headers={"User-Agent": AGENTE}, timeout=20, stream=True)
    if not r.ok or not r.headers.get("Content-Type", "").startswith("image/"):
        return None
    datos = b""
    for bloque in r.iter_content(65536):
        datos += bloque
        if len(datos) > MAX_BYTES:
            return None
    return datos or None


def buscar_en_internet(codigo):
    """(bytes JPEG, nombre de la fuente, alguna base respondió).
    Si ninguna base respondió (sin internet), no se debe anotar el código como "sin foto"."""
    respondio = False
    formas = [f for f in variantes_codigo(codigo) if f.isdigit()]
    # Las bases guardan casi siempre EAN-13 / UPC-A: probar primero los más largos.
    formas.sort(key=len, reverse=True)
    for nombre, sitio in FUENTES:
        for forma in formas[:4]:
            try:
                r = requests.get(f"{sitio}/api/v2/product/{forma}.json",
                                 params={"fields": ",".join(("code",) + CAMPOS_IMAGEN)},
                                 headers={"User-Agent": AGENTE}, timeout=12)
            except requests.RequestException:
                continue
            if r.status_code == 429:
                time.sleep(3)
                continue
            if r.status_code in (200, 404):
                respondio = True
            if not r.ok:
                continue
            try:
                producto = (r.json() or {}).get("product") or {}
            except ValueError:
                continue
            for campo in CAMPOS_IMAGEN:
                try:
                    datos = _descargar_imagen(producto.get(campo) or "")
                except requests.RequestException:
                    datos = None
                if datos:
                    reducida, _ = _reducir(datos)
                    if reducida:
                        return reducida, nombre, True
    return None, None, respondio


def _toca_buscar(codigo, indice, fotos):
    if codigo in fotos:
        return False
    marca = indice["sin_foto"].get(codigo)
    if not marca:
        return True
    if marca.get("rechazada"):
        return False
    try:
        return _ahora() - datetime.fromisoformat(marca["fecha"]) > timedelta(days=REINTENTAR_DIAS)
    except (KeyError, ValueError):
        return True


def buscar_y_guardar(codigo, base, headers, indice):
    """Busca la foto de un código y la guarda. Devuelve la fuente o None. Actualiza el índice."""
    datos, fuente, respondio = buscar_en_internet(codigo)
    if not respondio:
        raise RuntimeError("Las bases de fotos no respondieron (¿sin internet?).")
    if datos:
        _asegurar_bucket(base, headers)
        _subir(base, headers, f"{BUCKET}/{CARPETA_INTERNET}/{codigo}.jpg", datos, "image/jpeg")
        indice["sin_foto"].pop(codigo, None)
        indice["origen"][codigo] = {"fuente": fuente, "fecha": _ahora().isoformat(timespec="seconds")}
        return fuente
    indice["sin_foto"][codigo] = {"fecha": _ahora().isoformat(timespec="seconds")}
    return None


# ---------------------------------------------------------------- consultas → fotos
def _codigos_consultados(base, headers, desde):
    """Códigos ENCONTRADOS en el registro de consultas desde una fecha (de todos los canales)."""
    codigos, inicio = [], 0
    while True:
        r = requests.get(f"{base}/rest/v1/price_lookup_log", headers=headers, timeout=30,
                         params={"select": "barcode,created_at", "found": "eq.true",
                                 "created_at": f"gt.{desde}", "order": "created_at.asc",
                                 "offset": inicio, "limit": 1000})
        if not r.ok:
            raise RuntimeError(f"No se pudo leer el registro de consultas (HTTP {r.status_code}).")
        lote = r.json()
        codigos += [(f.get("barcode"), f.get("created_at")) for f in lote]
        if len(lote) < 1000 or inicio > 50000:
            return codigos
        inicio += len(lote)


def procesar_pendientes(maximo=MAX_POR_VUELTA, dias_iniciales=60, registro=print):
    """Busca fotos de los productos consultados desde la última vuelta. Devuelve un resumen."""
    base, headers = _conexion()
    indice = leer_indice(base, headers)
    fotos = fotos_guardadas(base, headers)
    desde = indice["revisado_hasta"] or (_ahora() - timedelta(days=dias_iniciales)).isoformat(timespec="seconds")
    consultados = _codigos_consultados(base, headers, desde)
    cola = list(dict.fromkeys(indice["pendientes"] + [_codigo_valido(c) for c, _ in consultados]))
    cola = [c for c in cola if c and _toca_buscar(c, indice, fotos)]
    if consultados:
        indice["revisado_hasta"] = max(f for _, f in consultados if f)
    halladas, sin_foto = 0, 0
    hechas = 0
    for codigo in cola[:maximo]:
        try:
            fuente = buscar_y_guardar(codigo, base, headers, indice)
        except RuntimeError as exc:
            registro(f"⚠️ {exc}")
            break
        hechas += 1
        if fuente:
            halladas += 1
            registro(f"📷 {codigo}: foto de {fuente}")
        else:
            sin_foto += 1
        time.sleep(0.6)      # amable con las bases abiertas
    indice["pendientes"] = cola[hechas:]
    guardar_indice(indice, base, headers)
    return {"buscadas": hechas, "halladas": halladas, "sin_foto": sin_foto,
            "pendientes": len(indice["pendientes"])}


_en_curso = set()
_candado = threading.Lock()


def asegurar_en_segundo_plano(codigo):
    """Para la Consulta en línea: si el producto no tiene foto, la busca sin demorar al cliente."""
    codigo = _codigo_valido(codigo)
    if not codigo:
        return
    with _candado:
        if codigo in _en_curso:
            return
        _en_curso.add(codigo)
    try:
        base, headers = _conexion()
    except RuntimeError:
        _en_curso.discard(codigo)
        return

    def trabajo():
        try:
            fotos_existe = any(_leer_existe(base, headers, r) for r in (
                f"{BUCKET}/{codigo}.png", f"{BUCKET}/{CARPETA_INTERNET}/{codigo}.jpg"))
            if fotos_existe:
                return
            indice = leer_indice(base, headers)
            if not _toca_buscar(codigo, indice, {}):
                return
            buscar_y_guardar(codigo, base, headers, indice)
            guardar_indice(indice, base, headers)
        except Exception:
            pass   # nunca afecta la consulta
        finally:
            with _candado:
                _en_curso.discard(codigo)

    threading.Thread(target=trabajo, name="foto-producto", daemon=True).start()


def _leer_existe(base, headers, ruta):
    try:
        r = requests.head(f"{base}/storage/v1/object/{ruta}", headers=headers, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False


# ---------------------------------------------------------------- administración
def quitar(codigo, base=None, headers=None):
    """Borra la foto de internet de un código y no la vuelve a buscar (salvo que se suba a mano)."""
    if base is None:
        base, headers = _conexion()
    _borrar(base, headers, BUCKET, [f"{CARPETA_INTERNET}/{codigo}.jpg"])
    indice = leer_indice(base, headers)
    indice["sin_foto"][codigo] = {"fecha": _ahora().isoformat(timespec="seconds"), "rechazada": True}
    indice["origen"].pop(codigo, None)
    guardar_indice(indice, base, headers)


def volver_a_buscar(codigo, base=None, headers=None):
    if base is None:
        base, headers = _conexion()
    indice = leer_indice(base, headers)
    indice["sin_foto"].pop(codigo, None)
    fuente = buscar_y_guardar(codigo, base, headers, indice)
    guardar_indice(indice, base, headers)
    return fuente


def quitar_manual(codigo, base=None, headers=None):
    if base is None:
        base, headers = _conexion()
    _borrar(base, headers, BUCKET, [f"{codigo}.{e}" for e in ("png", "jpg", "jpeg", "webp")])


def leer_foto(ruta, base=None, headers=None):
    if base is None:
        base, headers = _conexion()
    return _leer(base, headers, ruta)


# ---------------------------------------------------------------- equipos sin internet
def publicar_para_equipos(base, headers, anterior=None):
    """Copia las fotos al almacenamiento público y publica fotos.json.
    Devuelve (referencia para estado.json, cantidad). Solo sube lo que cambió."""
    fotos = fotos_guardadas(base, headers)
    mapa = {}
    for codigo, (ruta, huella, _) in sorted(fotos.items()):
        ext = ruta.rsplit(".", 1)[-1].lower().replace("jpeg", "jpg")
        mapa[codigo] = f"fotos/{codigo}-{huella}.{ext}"
    contenido = json.dumps(mapa, separators=(",", ":"), sort_keys=True).encode("utf-8")
    version = hashlib.sha256(contenido).hexdigest()[:12]
    referencia = f"{MAPA_PUBLICO}?v={version}"
    if anterior == referencia:
        return referencia, len(mapa)
    try:
        r = requests.get(f"{base}/storage/v1/object/{PUBLICO}/{MAPA_PUBLICO}", headers=headers, timeout=20)
        publicado = r.json() if r.ok else {}
    except (requests.RequestException, ValueError):
        publicado = {}
    for codigo, archivo in mapa.items():
        if publicado.get(codigo) == archivo:
            continue
        datos = _leer(base, headers, fotos[codigo][0])
        if not datos:
            continue
        tipo = "image/png" if archivo.endswith(".png") else "image/webp" if archivo.endswith(".webp") else "image/jpeg"
        _subir(base, headers, f"{PUBLICO}/{archivo}", datos, tipo, "max-age=31536000")
    _subir(base, headers, f"{PUBLICO}/{MAPA_PUBLICO}", contenido, "application/json", "no-cache")
    viejos = [a for c, a in publicado.items() if mapa.get(c) != a]
    try:
        _borrar(base, headers, PUBLICO, viejos)
    except requests.RequestException:
        pass
    return referencia, len(mapa)


def resumen(base=None, headers=None):
    """Para la página de administración."""
    if base is None:
        base, headers = _conexion()
    fotos = fotos_guardadas(base, headers)
    indice = leer_indice(base, headers)
    return fotos, indice


def enlaces_firmados(rutas, segundos=3600, base=None, headers=None):
    """{ruta: dirección temporal} para mostrar fotos privadas en la página (una sola llamada)."""
    if base is None:
        base, headers = _conexion()
    por_bucket = {}
    for ruta in rutas:
        bucket, _, resto = ruta.partition("/")
        por_bucket.setdefault(bucket, []).append(resto)
    salida = {}
    for bucket, partes in por_bucket.items():
        r = requests.post(f"{base}/storage/v1/object/sign/{bucket}",
                          headers={**headers, "Content-Type": "application/json"},
                          json={"expiresIn": int(segundos), "paths": partes}, timeout=20)
        if not r.ok:
            continue
        for fila in r.json():
            if fila.get("signedURL") and fila.get("path"):
                salida[f"{bucket}/{fila['path']}"] = f"{base}/storage/v1{fila['signedURL']}"
    return salida
