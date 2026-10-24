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
MAX_POR_VUELTA = 25          # búsquedas por ejecución (UPCitemdb gratis: 100 al día)
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


NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/124.0 Safari/537.36")


def _descargar_imagen(direccion, motivo=None):
    """Bytes de la imagen o None. Las fotos de tiendas en línea suelen venir por http, con tipo
    "application/octet-stream" o bloquear agentes desconocidos: se prueba https y http, con
    un agente de navegador, y se acepta cualquier tipo (luego Pillow comprueba que sea imagen)."""
    direccion = str(direccion or "").strip()
    if not direccion.startswith(("https://", "http://")):
        return None
    opciones = [direccion]
    if direccion.startswith("http://"):
        opciones.insert(0, "https://" + direccion[len("http://"):])
    ultimo = "sin respuesta"
    for u in opciones:
        try:
            from urllib.parse import urlsplit
            partes = urlsplit(u)
            r = requests.get(u, headers={"User-Agent": NAVEGADOR, "Accept": "image/*,*/*;q=0.8",
                                         "Referer": f"{partes.scheme}://{partes.netloc}/"},
                             timeout=20, stream=True, allow_redirects=True)
        except requests.RequestException as exc:
            ultimo = f"sin respuesta ({type(exc).__name__})"
            continue
        if not r.ok:
            ultimo = f"HTTP {r.status_code}"
            continue
        tipo = r.headers.get("Content-Type", "").lower()
        if tipo.startswith(("text/", "application/json")):
            ultimo = f"no es una imagen ({tipo.split(';')[0]})"
            continue
        datos = b""
        for bloque in r.iter_content(65536):
            datos += bloque
            if len(datos) > MAX_BYTES:
                datos = b""
                ultimo = "imagen demasiado grande"
                break
        if datos:
            return datos
    if motivo is not None:
        motivo.append(ultimo)
    return None


UPCITEMDB = "https://api.upcitemdb.com/prod/trial/lookup"   # gratis: 100 consultas al día
DDG = "https://duckduckgo.com/"


def _duckduckgo_imagenes(consulta, anotar, nombre=None, codigo=None):
    """Direcciones de imágenes para una búsqueda (DuckDuckGo, gratis y sin clave).
    Devuelve None si el buscador no respondió. Es un servicio no oficial: si algún día deja de
    responder, el resto de la búsqueda sigue funcionando igual."""
    import re
    cab = {"User-Agent": NAVEGADOR, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}
    try:
        r = requests.get(DDG, params={"q": consulta, "iax": "images", "ia": "images"}, headers=cab, timeout=12)
        m = re.search(r"vqd=['\"]?([\d-]+)", r.text or "")
        if not m:
            anotar("Buscador DuckDuckGo", consulta, f"no respondió (HTTP {r.status_code})")
            return None
        r = requests.get(DDG + "i.js", timeout=12,
                         params={"l": "us-en", "o": "json", "q": consulta, "vqd": m.group(1), "f": ",,,,,", "p": "1"},
                         headers={**cab, "Referer": DDG, "Accept": "application/json"})
        resultados = ((r.json() or {}).get("results") or []) if r.ok else []
    except (requests.RequestException, ValueError) as exc:
        anotar("Buscador DuckDuckGo", consulta, f"sin respuesta ({type(exc).__name__})")
        return None
    total = len(resultados)
    resultados = [x for x in resultados if es_del_producto(" ".join(str(x.get(k) or "") for k in ("title", "url", "source")),
                                                          nombre, codigo)]
    anotar("Buscador DuckDuckGo", consulta, _texto_resultados(total, len(resultados)))
    urls = []
    for res in resultados[:10]:
        # La original y, de respaldo, la miniatura (siempre se puede descargar).
        urls += [u for u in (res.get("image"), res.get("thumbnail")) if isinstance(u, str) and u.startswith("http")]
    return urls


# Tiendas en línea donde buscar fotos. Sirena viene incluida; el administrador puede agregar más
# desde Apariencia (se detecta sola si la tienda usa VTEX o Shopify, que tienen catálogo público).
TIENDAS_PREDETERMINADAS = ({"nombre": "Sirena", "sitio": "https://www.sirena.do", "plataforma": "vtex"},)
ARCHIVO_TIENDAS = "logo-negocio/fotos-tiendas.json"
PARECIDO_MINIMO = 0.6
_tiendas_cache = {"hora": 0, "lista": None}
_PALABRAS_VACIAS = {"de", "del", "la", "el", "los", "las", "en", "con", "sin", "y", "x", "para", "a", "al", "e", "o",
                    "u", "und", "unidad", "unidades", "pack", "paquete"}


def _palabras(texto):
    """Palabras normalizadas de un nombre: sin acentos ni mayúsculas, con la medida pegada al número
    ("355 ml" -> "355ml", "2 Lt" -> "2lt")."""
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"(\d)[\s.]*(ml|lt|l|oz|onzas|onz|g|gr|kg|lb|lbs|cc|un|uds)\b", r"\1\2", t)
    t = t.replace("onzas", "oz").replace("onz", "oz")
    return [w for w in re.split(r"[^a-z0-9]+", t) if w and w not in _PALABRAS_VACIAS]


def parecido(nuestro, otro):
    """Qué tanto se parece el nombre de una tienda al nuestro (0 a 1). Las abreviaturas cuentan
    ("bot" = "botella"), y si nuestro nombre tiene una medida (355ml, 2lt) la otra debe tenerla."""
    a, b = _palabras(nuestro), _palabras(otro)
    if not a or not b:
        return 0.0

    def coincide(x, y):
        if x == y:
            return True
        if x[0].isdigit() or y[0].isdigit():
            return x.rstrip("s") == y.rstrip("s")
        return len(x) >= 3 and len(y) >= 3 and (x.startswith(y) or y.startswith(x))

    medidas = [w for w in a if w[0].isdigit()]
    if medidas and not any(coincide(m, w) for m in medidas for w in b):
        return 0.0
    return sum(1 for x in a if any(coincide(x, y) for y in b)) / len(a)


def _sitio(direccion):
    from urllib.parse import urlsplit
    direccion = str(direccion or "").strip()
    if not direccion.startswith(("http://", "https://")):
        direccion = "https://" + direccion
    partes = urlsplit(direccion)
    return f"https://{partes.netloc}" if partes.netloc else ""


def detectar_plataforma(sitio):
    """'vtex', 'shopify' o None, según el catálogo público que tenga la tienda."""
    cab = {"User-Agent": NAVEGADOR, "Accept": "application/json"}
    try:
        r = requests.get(f"{sitio}/api/catalog_system/pub/products/search", params={"_from": 0, "_to": 0},
                         headers=cab, timeout=12)
        if r.status_code in (200, 206) and isinstance(r.json(), list):
            return "vtex"
    except (requests.RequestException, ValueError):
        pass
    try:
        r = requests.get(f"{sitio}/products.json", params={"limit": 1}, headers=cab, timeout=12)
        if r.ok and isinstance(r.json().get("products"), list):
            return "shopify"
    except (requests.RequestException, ValueError, AttributeError):
        pass
    return None


def tiendas_configuradas(base=None, headers=None):
    """Tiendas donde buscar (predeterminadas + las agregadas en Apariencia). Se recuerda 5 min."""
    if _tiendas_cache["lista"] is not None and time.time() - _tiendas_cache["hora"] < 300:
        return _tiendas_cache["lista"]
    lista = [dict(t) for t in TIENDAS_PREDETERMINADAS]
    try:
        if base is None:
            base, headers = _conexion()
        datos = _leer(base, headers, ARCHIVO_TIENDAS)
        for t in (json.loads(datos).get("tiendas") if datos else []) or []:
            if t.get("sitio") and t.get("plataforma") and all(t["sitio"] != x["sitio"] for x in lista):
                lista.append(t)
    except (RuntimeError, ValueError, AttributeError):
        pass
    _tiendas_cache.update(hora=time.time(), lista=lista)
    return lista


def guardar_tiendas(direcciones, base=None, headers=None):
    """Guarda las tiendas agregadas por el administrador. Devuelve [(sitio, plataforma o None)]."""
    if base is None:
        base, headers = _conexion()
    resultado, tiendas = [], []
    for direccion in direcciones:
        sitio = _sitio(direccion)
        if not sitio or any(sitio == t["sitio"] for t in TIENDAS_PREDETERMINADAS) or any(sitio == t["sitio"] for t in tiendas):
            continue
        plataforma = detectar_plataforma(sitio)
        resultado.append((sitio, plataforma))
        if plataforma:
            nombre = sitio.split("//", 1)[1].replace("www.", "").split(".")[0].capitalize()
            tiendas.append({"nombre": nombre, "sitio": sitio, "plataforma": plataforma})
    _subir(base, headers, ARCHIVO_TIENDAS, json.dumps({"tiendas": tiendas}, ensure_ascii=False).encode("utf-8"),
           "application/json")
    _tiendas_cache["lista"] = None
    return resultado


def _imagenes_vtex_de(producto):
    return list(dict.fromkeys(img.get("imageUrl") for item in producto.get("items") or []
                              for img in item.get("images") or [] if img.get("imageUrl")))


def _vtex_por_nombre(tienda, sitio, nombre, anotar):
    """Busca por NOMBRE en una tienda VTEX y devuelve las fotos del más parecido (o [])."""
    try:
        r = requests.get(f"{sitio}/api/catalog_system/pub/products/search", timeout=12,
                         params={"ft": " ".join(_palabras(nombre))[:80], "_from": 0, "_to": 9},
                         headers={"User-Agent": NAVEGADOR, "Accept": "application/json"})
        productos = r.json() if r.status_code in (200, 206) else []
    except (requests.RequestException, ValueError):
        return []
    mejor, puntaje = None, 0.0
    for p in productos if isinstance(productos, list) else []:
        valor = parecido(nombre, p.get("productName", ""))
        if valor > puntaje:
            mejor, puntaje = p, valor
    if mejor is None or puntaje < PARECIDO_MINIMO:
        anotar(f"Tienda {tienda} (por nombre)", nombre, "ninguno se parece lo suficiente")
        return []
    anotar(f"Tienda {tienda} (por nombre)", nombre, f"{mejor.get('productName')} (parecido {puntaje:.0%})")
    return _imagenes_vtex_de(mejor)


def _shopify_producto(sitio, enlace):
    from urllib.parse import urlsplit
    ruta = urlsplit(enlace).path.rstrip("/")
    try:
        r = requests.get(f"{sitio}{ruta}.js", headers={"User-Agent": NAVEGADOR}, timeout=12)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def _shopify_imagenes(tienda, sitio, formas, nombre, anotar, por_nombre=False):
    """Tienda Shopify: por código (comprueba el código de barras de las variantes) o por nombre."""
    buscados = {f.lstrip("0") for f in formas}
    consulta = " ".join(_palabras(nombre))[:80] if por_nombre else formas[0]
    if not consulta:
        return []
    try:
        r = requests.get(f"{sitio}/search/suggest.json", timeout=12, headers={"User-Agent": NAVEGADOR},
                         params={"q": consulta, "resources[type]": "product", "resources[limit]": 6})
        productos = (((r.json() or {}).get("resources") or {}).get("results") or {}).get("products") or [] if r.ok else []
    except (requests.RequestException, ValueError, AttributeError):
        anotar(f"Tienda {tienda}", consulta, "no respondió")
        return None
    elegido, puntaje = None, 0.0
    for p in productos:
        detalle = _shopify_producto(sitio, p.get("url", ""))
        if not detalle:
            continue
        codigos = {str(v.get("barcode") or "").lstrip("0") for v in detalle.get("variants") or []}
        if codigos & buscados:
            elegido, puntaje = detalle, 1.0
            break
        if por_nombre:
            valor = parecido(nombre, detalle.get("title", ""))
            if valor > puntaje:
                elegido, puntaje = detalle, valor
    etiqueta = f"Tienda {tienda}" + (" (por nombre)" if por_nombre else "")
    if not elegido or puntaje < (PARECIDO_MINIMO if por_nombre else 1.0):
        anotar(etiqueta, consulta, "no lo tiene" if not por_nombre else "ninguno se parece lo suficiente")
        return []
    fotos = [("https:" + u if u.startswith("//") else u) for u in (detalle_fotos(elegido))]
    anotar(etiqueta, consulta, f"{elegido.get('title')}: {len(fotos)} foto(s)")
    return fotos


def detalle_fotos(producto):
    fotos = list(producto.get("images") or [])
    if producto.get("featured_image"):
        fotos.insert(0, producto["featured_image"])
    return [u for u in dict.fromkeys(fotos) if isinstance(u, str)]


def _codigos_del_producto(producto):
    """Todos los códigos que una tienda VTEX guarda para un producto (EAN, referencia, PLU)."""
    vistos = set()
    for clave in ("productReference", "productReferenceCode"):
        if producto.get(clave):
            vistos.add(str(producto[clave]))
    for item in producto.get("items") or []:
        if item.get("ean"):
            vistos.add(str(item["ean"]))
        for ref in item.get("referenceId") or []:
            if ref.get("Value"):
                vistos.add(str(ref["Value"]))
    return {"".join(ch for ch in v if ch.isdigit()).lstrip("0") for v in vistos if v}


def _vtex_imagenes(tienda, sitio, formas, anotar):
    """Fotos del producto en una tienda VTEX, buscando por EAN, por referencia y por texto.
    Solo se aceptan productos cuyo código coincide (no "parecidos"). None si no respondió."""
    buscados = {f.lstrip("0") for f in formas}
    pruebas = []
    for forma in formas[:3]:
        pruebas += [{"fq": f"alternateIds_Ean:{forma}"}, {"fq": f"alternateIds_RefId:A{forma}"}]
    pruebas += [{"ft": formas[0]}]
    respondio = False
    for params in pruebas:
        try:
            r = requests.get(f"{sitio}/api/catalog_system/pub/products/search", params=params, timeout=12,
                             headers={"User-Agent": NAVEGADOR, "Accept": "application/json"})
        except requests.RequestException as exc:
            anotar(f"Tienda {tienda}", formas[0], f"sin respuesta ({type(exc).__name__})")
            return None
        if r.status_code not in (200, 206, 404):
            continue
        respondio = True
        try:
            productos = r.json() if r.status_code in (200, 206) else []
        except ValueError:
            productos = []
        for producto in productos if isinstance(productos, list) else []:
            if not (_codigos_del_producto(producto) & buscados):
                continue
            urls = [img.get("imageUrl") for item in producto.get("items") or []
                    for img in item.get("images") or [] if img.get("imageUrl")]
            if urls:
                anotar(f"Tienda {tienda}", formas[0], f"{producto.get('productName', 'producto')}: {len(urls)} foto(s)")
                return list(dict.fromkeys(urls))
    anotar(f"Tienda {tienda}", formas[0], "no lo tiene" if respondio else "no respondió")
    return [] if respondio else None


# Índice de tiendas sin catálogo público (lo arma fotos_navegador una vez por semana).
ARCHIVO_INDICES = "logo-negocio/indice-tiendas.json"
_indices_cache = {"hora": 0, "datos": None}


def leer_indices_tiendas(base=None, headers=None):
    try:
        if base is None:
            base, headers = _conexion()
        datos = _leer(base, headers, ARCHIVO_INDICES)
        return json.loads(datos) if datos else {}
    except (RuntimeError, ValueError):
        return {}


def _indices():
    if _indices_cache["datos"] is None or time.time() - _indices_cache["hora"] > 600:
        _indices_cache.update(datos=leer_indices_tiendas(), hora=time.time())
    return _indices_cache["datos"] or {}


def _productos_indice(datos):
    """El último índice completo más lo que ya se recorrió del que se está armando."""
    return (datos.get("productos") or []) + ((datos.get("en_curso") or {}).get("productos") or [])


def _indice_por_codigo(formas, anotar):
    buscados = {f.lstrip("0") for f in formas}
    for tienda, datos in _indices().items():
        for codigo, nombre, foto in _productos_indice(datos):
            if codigo and codigo.lstrip("0") in buscados:
                anotar(f"Tienda {tienda}", formas[0], f"{nombre}: 1 foto(s)")
                yield tienda, foto


def _indice_por_nombre(nombre, anotar):
    for tienda, datos in _indices().items():
        mejor, puntaje = None, 0.0
        for _codigo, otro, foto in _productos_indice(datos):
            valor = parecido(nombre, otro)
            if valor > puntaje:
                mejor, puntaje = (otro, foto), valor
        if mejor and puntaje >= PARECIDO_MINIMO:
            anotar(f"Tienda {tienda} (por nombre)", nombre, f"{mejor[0]} (parecido {puntaje:.0%})")
            yield tienda, mejor[1]


BING = "https://www.bing.com/images/search"


def imagenes_de_bing(html_pagina):
    """De una página de resultados de Bing Imágenes: [(original, miniatura)].
    La miniatura la sirve Bing y siempre se puede descargar, aunque la tienda bloquee la original."""
    import html as html_mod
    import json as json_mod
    import re
    pares = []
    for crudo in re.findall(r'class="iusc"[^>]*?\sm="([^"]+)"', html_pagina or "") + \
            re.findall(r'\sm="([^"]+)"[^>]*?class="iusc"', html_pagina or ""):
        try:
            datos = json_mod.loads(html_mod.unescape(crudo))
        except ValueError:
            continue
        original, miniatura = datos.get("murl"), datos.get("turl")
        if (original or miniatura) and all(p[:2] != (original, miniatura) for p in pares):
            texto = " ".join(str(datos.get(k) or "") for k in ("t", "purl", "desc"))
            pares.append((original, miniatura, texto))
    return pares


def es_del_producto(texto, nombre=None, codigo=None):
    """¿La imagen de un buscador es de ESTE producto? Su título o página debe mencionar el código
    (en cualquiera de sus formas) o parecerse al nombre del producto."""
    texto = str(texto or "")
    if codigo:
        digitos = "".join(c if c.isdigit() else " " for c in texto).split()
        formas = {f.lstrip("0") for f in variantes_codigo(codigo) if len(f) >= 8}
        if any(d.lstrip("0") in formas for d in digitos):
            return True
    return bool(nombre) and parecido(nombre, texto) >= PARECIDO_MINIMO


def _texto_resultados(total, validos):
    if not total:
        return "sin resultados"
    if not validos:
        return f"{total} imagen(es), ninguna de este producto"
    return f"{validos} de {total} imagen(es) son de este producto"


def _bing_imagenes(consulta, anotar, nombre=None, codigo=None):
    """Bing Imágenes sin clave (página normal de resultados). None si no respondió."""
    try:
        r = requests.get(BING, params={"q": consulta, "form": "HDRSC2", "first": 1},
                         headers={"User-Agent": NAVEGADOR, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}, timeout=15)
    except requests.RequestException as exc:
        anotar("Buscador Bing", consulta, f"sin respuesta ({type(exc).__name__})")
        return None
    if not r.ok:
        anotar("Buscador Bing", consulta, f"no respondió (HTTP {r.status_code})")
        return None
    todos = imagenes_de_bing(r.text)
    pares = [p for p in todos if es_del_producto(p[2], nombre, codigo)]
    anotar("Buscador Bing", consulta, _texto_resultados(len(todos), len(pares)))
    return [u for par in pares[:10] for u in par[:2] if u and u.startswith("http")]


def _foto_de_pagina(enlace):
    """Foto principal de la página de un producto (og:image / twitter:image / JSON-LD), o None."""
    import re
    from urllib.parse import urljoin
    try:
        r = requests.get(enlace, headers={"User-Agent": NAVEGADOR, "Accept": "text/html"}, timeout=15,
                         allow_redirects=True, stream=True)
        if not r.ok or "html" not in r.headers.get("Content-Type", "").lower():
            return None
        crudo = b""
        for bloque in r.iter_content(65536):
            crudo += bloque
            if len(crudo) > 1_500_000:
                break
        texto = crudo.decode(r.encoding or "utf-8", "ignore")
    except (requests.RequestException, ValueError, OSError, AttributeError, LookupError):
        return None
    for patron in (r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image)["\'][^>]*content=["\']([^"\']+)',
                   r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:og:image|twitter:image)',
                   r'"image"\s*:\s*"(https?:[^"]+)"', r'"image"\s*:\s*\[\s*"(https?:[^"]+)"'):
        m = re.search(patron, texto, re.I)
        if m:
            return urljoin(r.url, m.group(1).replace("&amp;", "&").replace("\\/", "/"))
    return None


_catalogo_cache = {"version": None, "nombres": {}, "hora": 0}
_nombre_forzado = {}


def _nombre_en_catalogo(codigo):
    """Nombre del producto en el catálogo publicado para los equipos (cualquier fuente de precios)."""
    try:
        if time.time() - _catalogo_cache["hora"] > 600 or not _catalogo_cache["nombres"]:
            base, headers = _conexion()
            r = requests.get(f"{base}/storage/v1/object/public/{PUBLICO}/estado.json", timeout=10)
            estado = r.json() if r.ok else {}
            if estado.get("catalogo") and estado.get("version") != _catalogo_cache["version"]:
                rc = requests.get(f"{base}/storage/v1/object/public/{PUBLICO}/{estado['catalogo']}", timeout=60)
                productos = (rc.json() or {}).get("productos") or [] if rc.ok else []
                _catalogo_cache["nombres"] = {str(p[0]): str(p[1]) for p in productos if len(p) > 1}
                _catalogo_cache["version"] = estado.get("version")
            _catalogo_cache["hora"] = time.time()
        nombres = _catalogo_cache["nombres"]
        for forma in variantes_codigo(codigo):
            if forma in nombres:
                return nombres[forma].strip()
    except (requests.RequestException, ValueError, RuntimeError, TypeError):
        pass
    return ""


def _nombre_consultado(codigo):
    """Nombre del producto para buscar su foto por nombre: el escrito en la prueba, el del registro
    de consultas o el del catálogo publicado."""
    if _nombre_forzado.get(codigo):
        return _nombre_forzado[codigo]
    del_registro = _nombre_del_registro(codigo)
    return del_registro or _nombre_en_catalogo(codigo)


def _nombre_del_registro(codigo):
    try:
        base, headers = _conexion()
        r = requests.get(f"{base}/rest/v1/price_lookup_log", headers=headers, timeout=10,
                         params={"select": "product_name", "barcode": f"eq.{codigo}", "found": "eq.true",
                                 "product_name": "not.is.null", "order": "created_at.desc", "limit": 1})
        filas = r.json() if r.ok else []
        return str(filas[0]["product_name"]).strip() if filas else ""
    except (requests.RequestException, ValueError, KeyError, RuntimeError):
        return ""
FONDO_MINIMO = 0.55     # parte del borde que debe ser fondo blanco/claro (foto de catálogo)
MAX_CANDIDATAS = 40


def _abrir_rgb(datos):
    from PIL import Image
    im = Image.open(BytesIO(datos))
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        fondo = Image.new("RGB", im.size, "white")
        fondo.paste(im, mask=im.split()[-1])   # lo transparente cuenta como fondo blanco
        return fondo
    return im.convert("RGB")


def calidad_fondo(im):
    """Parte (0 a 1) del borde de la imagen que es fondo blanco o claro y parejo.
    Las fotos de catálogo (producto solo, fondo blanco) dan cerca de 1;
    las fotos tomadas en la tienda o con la mano, mucho menos."""
    chica = im.copy()
    chica.thumbnail((120, 120))
    ancho, alto = chica.size
    if ancho < 20 or alto < 20:
        return 0.0
    px = chica.load()
    banda = max(2, round(min(ancho, alto) * 0.06))
    claros = total = 0
    for y in range(alto):
        for x in range(ancho):
            if banda <= x < ancho - banda and banda <= y < alto - banda:
                continue
            r, g, b = px[x, y]
            total += 1
            if min(r, g, b) >= 222 and max(r, g, b) - min(r, g, b) <= 28:
                claros += 1
    return claros / total if total else 0.0


def _foto_catalogo(im):
    """Recorta el fondo sobrante y centra el producto en un cuadro blanco (máx. 480 px)."""
    from PIL import Image, ImageChops
    diferencia = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255)))
    caja = diferencia.convert("L").point(lambda v: 255 if v > 24 else 0).getbbox()
    if caja:
        im = im.crop(caja)
    lado = round(max(im.size) * 1.08)
    cuadro = Image.new("RGB", (lado, lado), "white")
    cuadro.paste(im, ((lado - im.width) // 2, (lado - im.height) // 2))
    cuadro.thumbnail((LADO_MAXIMO, LADO_MAXIMO))
    salida = BytesIO()
    cuadro.save(salida, format="JPEG", quality=85, optimize=True)
    return salida.getvalue()


def _candidatas(codigo, informe, estado):
    """Fotos posibles del producto, de la más probable de ser de catálogo a la menos:
    1) UPCitemdb (fotos de tiendas en línea: producto solo, fondo blanco),
    2) Open Food Facts y sus bases hermanas (fotos de usuarios, muchas en la tienda)."""
    formas = [f for f in variantes_codigo(codigo) if f.isdigit()]
    formas.sort(key=len, reverse=True)   # las bases guardan casi siempre EAN-13 / UPC-A

    def anotar(base, forma, texto):
        if informe is not None:
            informe.append((base, forma, texto))

    # 1) Tiendas en línea (Sirena y las agregadas): por CÓDIGO, con fotos de estudio y productos locales.
    tiendas = tiendas_configuradas()
    for t in tiendas:
        if t["plataforma"] == "vtex":
            urls = _vtex_imagenes(t["nombre"], t["sitio"], formas, anotar)
        else:
            urls = _shopify_imagenes(t["nombre"], t["sitio"], formas, "", anotar)
        if urls is not None:
            estado["respondio"] = True
        for u in urls or []:
            yield f"Tienda {t['nombre']}", u, True
    for tienda, u in _indice_por_codigo(formas, anotar):
        yield f"Tienda {tienda}", u, True
    for forma in formas[:2]:
        try:
            r = requests.get(UPCITEMDB, params={"upc": forma}, timeout=12,
                             headers={"User-Agent": AGENTE, "Accept": "application/json"})
        except requests.RequestException as exc:
            anotar("UPCitemdb", forma, f"sin respuesta ({type(exc).__name__})")
            continue
        if r.status_code == 429:
            anotar("UPCitemdb", forma, "límite diario alcanzado (se reintenta otro día)")
            break
        if r.status_code in (200, 400, 404):
            estado["respondio"] = True
        items = []
        if r.ok:
            try:
                items = (r.json() or {}).get("items") or []
            except ValueError:
                items = []
        fotos = [u for it in items for u in (it.get("images") or []) if str(u).startswith("http")]
        if items and items[0].get("title") and not estado.get("titulo"):
            estado["titulo"] = str(items[0]["title"])[:120]
        anotar("UPCitemdb", forma, f"{len(fotos)} foto(s)" if fotos else "no lo tiene")
        for u in fotos:
            yield "UPCitemdb", u, True
        # Las tiendas que venden el producto: la foto principal de su página (suele ser de catálogo).
        ofertas = [o for it in items for o in (it.get("offers") or []) if str(o.get("link", "")).startswith("http")]
        for oferta in ofertas[:4]:
            u = _foto_de_pagina(oferta["link"])
            tienda = oferta.get("domain") or oferta.get("merchant") or "tienda"
            if u:
                yield f"Tienda {tienda}", u, True
            else:
                anotar(f"Tienda {tienda}", forma, "sin foto en la página")
        if items:
            break
    for nombre, sitio in FUENTES:
        for forma in formas[:3]:
            try:
                r = requests.get(f"{sitio}/api/v2/product/{forma}.json",
                                 params={"fields": ",".join(("code", "product_name", "images", "selected_images") + CAMPOS_IMAGEN)},
                                 headers={"User-Agent": AGENTE}, timeout=12)
            except requests.RequestException as exc:
                anotar(nombre, forma, f"sin respuesta ({type(exc).__name__})")
                continue
            if r.status_code == 429:
                time.sleep(3)
                continue
            if r.status_code in (200, 404):
                estado["respondio"] = True
            producto = {}
            if r.ok:
                try:
                    producto = (r.json() or {}).get("product") or {}
                except ValueError:
                    producto = {}
            urls = list(dict.fromkeys(_fotos_open_facts(producto, sitio)))
            anotar(nombre, forma, f"{len(urls)} foto(s)" if urls else "no lo tiene")
            if producto.get("product_name") and not estado.get("titulo"):
                estado["titulo"] = str(producto["product_name"])[:120]
            for u in urls:
                yield nombre, u, False
            if urls:
                break
    # 2) Si por código no apareció: por el NOMBRE del producto (el de tu inventario), en las tiendas.
    nombre_propio = _nombre_consultado(codigo)
    nombre_producto = nombre_propio or estado.get("titulo") or ""
    estado["titulo"] = nombre_producto
    if nombre_propio:
        for t in tiendas:
            if t["plataforma"] == "vtex":
                urls = _vtex_por_nombre(t["nombre"], t["sitio"], nombre_propio, anotar)
            else:
                urls = _shopify_imagenes(t["nombre"], t["sitio"], formas, nombre_propio, anotar, por_nombre=True)
            for u in urls or []:
                yield f"Tienda {t['nombre']} (por nombre)", u, True
        for tienda, u in _indice_por_nombre(nombre_propio, anotar):
            yield f"Tienda {tienda} (por nombre)", u, True
    # 3) Últimos recursos (gratis, sin clave): buscadores de imágenes, por nombre y código y solo por nombre.
    consultas = [f"{nombre_producto} {codigo}".strip() if nombre_producto else codigo]
    if nombre_producto:
        consultas.append(nombre_producto)
    for n, consulta in enumerate(consultas):
        # Los buscadores traen de todo (dibujos, otros productos): solo se aceptan imágenes cuyo
        # título o página mencione el código, o se parezca al nombre del producto.
        buscadores = [("Buscador Bing", lambda c, a: _bing_imagenes(c, a, nombre_producto, codigo))]
        if n == 0:
            buscadores.append(("Buscador DuckDuckGo", lambda c, a: _duckduckgo_imagenes(c, a, nombre_producto, codigo)))
        for nombre_buscador, buscador in buscadores:
            imagenes = buscador(consulta, anotar)
            if imagenes is not None:
                estado["respondio"] = True
            for u in imagenes or []:
                yield nombre_buscador, u, False


def _carpeta_open_facts(codigo):
    """Carpeta de las fotos en Open Food Facts: 0049000005226 -> 004/900/000/5226."""
    codigo = str(codigo or "")
    if len(codigo) <= 8:
        return codigo
    codigo = codigo.zfill(13)
    return f"{codigo[:3]}/{codigo[3:6]}/{codigo[6:9]}/{codigo[9:]}"


def _fotos_open_facts(producto, sitio):
    """La foto principal y TODAS las demás fotos subidas del producto (en alguna suele haber una
    de catálogo aunque la principal sea de la tienda). Primero las de frente, luego las demás."""
    urls = []
    seleccion = (producto.get("selected_images") or {}).get("front", {}).get("display", {})
    urls += [u for u in seleccion.values() if isinstance(u, str)]
    urls += [producto.get(c) for c in CAMPOS_IMAGEN[:2] if producto.get(c)]
    imagenes = producto.get("images") or {}
    servidor = sitio.replace("://world.", "://images.")
    carpeta = _carpeta_open_facts(producto.get("code"))
    numeros = sorted((k for k in imagenes if str(k).isdigit()), key=int)
    urls += [f"{servidor}/images/products/{carpeta}/{n}.400.jpg" for n in numeros]
    return [u for u in urls if u][:8]


def buscar_en_internet(codigo, informe=None):
    """(bytes JPEG, nombre de la fuente, alguna base respondió).
    Solo acepta fotos DE CATÁLOGO (producto solo sobre fondo blanco); las fotos tomadas en la
    tienda o con la mano se descartan. Si ninguna base respondió (sin internet), el código no
    debe anotarse como "sin foto"."""
    try:
        import PIL  # noqa: F401
        con_pillow = True
    except ImportError:
        con_pillow = False
    estado = {"respondio": False}
    probadas = 0
    for fuente, direccion, de_tienda in _candidatas(codigo, informe, estado):
        if probadas >= MAX_CANDIDATAS:
            break
        if not con_pillow:
            # Sin Pillow (GitHub Actions) no se puede revisar el fondo: solo fotos de tiendas en línea.
            if not de_tienda:
                continue
            try:
                datos = _descargar_imagen(direccion)
            except requests.RequestException:
                datos = None
            if datos:
                return datos, fuente, True
            continue
        probadas += 1
        motivo = []
        datos = _descargar_imagen(direccion, motivo)
        try:
            im = _abrir_rgb(datos) if datos else None
        except (OSError, ValueError):
            im = None
            motivo.append("el archivo no es una imagen")
        if im is None:
            if informe is not None:
                from urllib.parse import urlsplit
                sitio = urlsplit(direccion).netloc or direccion[:40]
                informe.append((fuente, "", f"foto {probadas} ({sitio}): no se pudo abrir ({motivo[0] if motivo else '?'})"))
            continue
        if min(im.size) < 150:
            if informe is not None:
                informe.append((fuente, "", f"foto {probadas}: descartada, muy pequeña ({im.width}×{im.height})"))
            continue
        puntaje = calidad_fondo(im)
        if puntaje >= FONDO_MINIMO:
            if informe is not None:
                informe.append((fuente, "", f"foto {probadas}: aceptada (fondo limpio {puntaje:.0%})"))
            return _foto_catalogo(im), fuente, True
        if informe is not None:
            informe.append((fuente, "", f"foto {probadas}: descartada, no es de catálogo (fondo limpio {puntaje:.0%})"))
    return None, None, estado["respondio"]


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
        time.sleep(11)       # UPCitemdb gratis admite ~6 consultas por minuto
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
    if not fuente:   # no hay una mejor: quitar la que estaba
        _borrar(base, headers, BUCKET, [f"{CARPETA_INTERNET}/{codigo}.jpg"])
        indice["origen"].pop(codigo, None)
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


def probar(codigo, nombre=None):
    """Diagnóstico para la página: busca YA la foto de un código y explica qué pasó."""
    codigo = _codigo_valido(codigo)
    if not codigo:
        return {"error": "Escribe un código de barras numérico de 6 a 14 dígitos."}
    _nombre_forzado.clear()
    if nombre and nombre.strip():
        _nombre_forzado[codigo] = " ".join(nombre.split())[:120]
    base, headers = _conexion()
    for ruta, origen in ((f"{BUCKET}/{codigo}.png", "manual"), (f"{BUCKET}/{CARPETA_INTERNET}/{codigo}.jpg", "internet")):
        if _leer_existe(base, headers, ruta):
            return {"ya": origen, "ruta": ruta}
    informe = []
    try:
        datos, fuente, respondio = buscar_en_internet(codigo, informe)
    finally:
        nombre_usado = _nombre_consultado(codigo)
        _nombre_forzado.clear()
    resultado = {"informe": informe, "respondio": respondio, "fuente": fuente, "nombre": nombre_usado,
                 "en_catalogo": bool(_nombre_en_catalogo(codigo))}
    if datos:
        _asegurar_bucket(base, headers)
        _subir(base, headers, f"{BUCKET}/{CARPETA_INTERNET}/{codigo}.jpg", datos, "image/jpeg")
        indice = leer_indice(base, headers)
        indice["sin_foto"].pop(codigo, None)
        indice["origen"][codigo] = {"fuente": fuente, "fecha": _ahora().isoformat(timespec="seconds")}
        guardar_indice(indice, base, headers)
        resultado["ruta"] = f"{BUCKET}/{CARPETA_INTERNET}/{codigo}.jpg"
    return resultado


def revisar_guardadas(base=None, headers=None):
    """Quita las fotos de internet ya guardadas que no son de catálogo (fotos de tienda o con la
    mano) y las deja para volver a buscar. Devuelve cuántas quitó."""
    from PIL import Image  # noqa: F401  (en Streamlit siempre está)
    if base is None:
        base, headers = _conexion()
    indice = leer_indice(base, headers)
    quitadas = []
    for nombre in _listar(base, headers, BUCKET, f"{CARPETA_INTERNET}/"):
        datos = _leer(base, headers, f"{BUCKET}/{CARPETA_INTERNET}/{nombre}")
        try:
            puntaje = calidad_fondo(_abrir_rgb(datos)) if datos else 0.0
        except (OSError, ValueError):
            puntaje = 0.0
        if puntaje < FONDO_MINIMO:
            quitadas.append(nombre)
            codigo = nombre.rsplit(".", 1)[0]
            indice["origen"].pop(codigo, None)
            indice["sin_foto"].pop(codigo, None)
            if codigo not in indice["pendientes"]:
                indice["pendientes"].append(codigo)
    if quitadas:
        _borrar(base, headers, BUCKET, [f"{CARPETA_INTERNET}/{n}" for n in quitadas])
        guardar_indice(indice, base, headers)
    return len(quitadas)


def importar_desde_enlace(enlace):
    """Para la página: descarga la imagen de un enlace, la deja como foto de catálogo
    (recorte y fondo blanco parejo) y devuelve (jpeg, puntaje de fondo limpio)."""
    motivo = []
    datos = _descargar_imagen(enlace, motivo)
    if not datos:
        raise RuntimeError("No se pudo descargar la imagen: " + (motivo[0] if motivo else "enlace inválido"))
    try:
        im = _abrir_rgb(datos)
    except (OSError, ValueError):
        raise RuntimeError("El enlace no es de una imagen (copia la dirección de la imagen, no de la página).")
    return _foto_catalogo(im), calidad_fondo(im)


def evaluar_y_guardar(codigo, datos, fuente, base=None, headers=None, informe=None, etiqueta=""):
    """Si la imagen es de catálogo, la deja pareja y la guarda como foto del producto. True si se guardó."""
    try:
        im = _abrir_rgb(datos)
    except (OSError, ValueError):
        return False
    if min(im.size) < 120:
        return False
    puntaje = calidad_fondo(im)
    if informe is not None:
        informe.append((fuente, "", f"{etiqueta}{'aceptada' if puntaje >= FONDO_MINIMO else 'descartada'} (fondo limpio {puntaje:.0%})"))
    if puntaje < FONDO_MINIMO:
        return False
    if base is None:
        base, headers = _conexion()
    _asegurar_bucket(base, headers)
    _subir(base, headers, f"{BUCKET}/{CARPETA_INTERNET}/{codigo}.jpg", _foto_catalogo(im), "image/jpeg")
    indice = leer_indice(base, headers)
    indice["sin_foto"].pop(codigo, None)
    indice["origen"][codigo] = {"fuente": fuente, "fecha": _ahora().isoformat(timespec="seconds")}
    if codigo in indice["pendientes"]:
        indice["pendientes"].remove(codigo)
    guardar_indice(indice, base, headers)
    return True


def reintentar_sin_foto(base=None, headers=None):
    """Vuelve a poner en la cola los productos marcados "sin foto" (no los que quitaste tú).
    Útil al agregar tiendas o mejorar la búsqueda. Devuelve cuántos."""
    if base is None:
        base, headers = _conexion()
    indice = leer_indice(base, headers)
    codigos = [c for c, v in indice["sin_foto"].items() if not v.get("rechazada")]
    for c in codigos:
        indice["sin_foto"].pop(c, None)
        (indice.get("navegador") or {}).pop(c, None)
        if c not in indice["pendientes"]:
            indice["pendientes"].append(c)
    guardar_indice(indice, base, headers)
    return len(codigos)
