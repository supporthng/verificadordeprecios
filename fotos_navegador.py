"""Fotos de productos con un navegador real (lo ejecuta GitHub Actions cada 30 minutos).

Para los productos que la búsqueda normal no pudo resolver (las tiendas bloquean la descarga o
solo muestran la foto con JavaScript), se abre un navegador Chrome invisible:
  1. Busca el producto en Bing Imágenes por su nombre y código.
  2. Descarga las fotos desde el propio navegador (pasa los bloqueos de las tiendas).
  3. Si aun así no puede, toma una CAPTURA de cada miniatura (recorte de la pantalla).
Cada imagen pasa el mismo control: solo se guarda si es de catálogo (producto solo, fondo blanco),
recortada y centrada sobre blanco. Cada producto se intenta una vez cada 30 días.

Necesita Playwright (pip install playwright && python -m playwright install --with-deps chromium).
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import fotos_productos as fp

DIAS_ENTRE_INTENTOS = 30
MAX_POR_VUELTA = 10


def _toca(marca):
    if not marca:
        return True
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(marca) > timedelta(days=DIAS_ENTRE_INTENTOS)
    except ValueError:
        return True


def buscar_uno(pagina, contexto, codigo, consulta, base, headers, informe=None, nombre_filtro=None):
    """Busca y guarda la foto de un código con el navegador. Devuelve la fuente o None."""
    pagina.goto(f"{fp.BING}?q={quote_plus(consulta)}&form=HDRSC2&first=1", wait_until="domcontentloaded",
                timeout=30000)
    try:
        pagina.wait_for_selector("a.iusc", timeout=8000)
    except Exception:
        if informe is not None:
            informe.append(("Navegador · Bing", consulta, "sin resultados"))
        return None
    todos = fp.imagenes_de_bing(pagina.content())
    indices = list(range(len(todos)))
    if nombre_filtro:   # búsqueda solo por nombre: el título de la imagen debe parecerse al producto
        indices = [i for i, p in enumerate(todos) if fp.parecido(nombre_filtro, p[2]) >= fp.PARECIDO_MINIMO]
    pares = [todos[i] for i in indices]
    if informe is not None:
        informe.append(("Navegador · Bing", consulta, f"{len(pares)} imagen(es)"))
    # 1) Descargar desde el navegador (con sus cookies y como si viniera de la página).
    for n, (original, miniatura, _titulo) in enumerate(pares[:8], start=1):
        for direccion in (original, miniatura):
            if not direccion or not direccion.startswith("http"):
                continue
            try:
                r = contexto.request.get(direccion, timeout=15000, headers={"Referer": pagina.url})
                datos = r.body() if r.ok else None
            except Exception:
                datos = None
            if datos and fp.evaluar_y_guardar(codigo, datos, "Navegador (Bing)", base, headers, informe,
                                              f"imagen {n}: "):
                return "Navegador (Bing)"
    # 2) Captura de las miniaturas en pantalla (recorte). Por nombre, solo si alguna se pareció.
    if not pares:
        return None
    miniaturas = pagina.locator("a.iusc img")
    for n in [i for i in indices[:8] if i < miniaturas.count()]:
        try:
            datos = miniaturas.nth(n).screenshot(timeout=5000)
        except Exception:
            continue
        if fp.evaluar_y_guardar(codigo, datos, "Navegador (captura)", base, headers, informe, f"captura {n + 1}: "):
            return "Navegador (captura)"
    return None


def procesar(maximo=MAX_POR_VUELTA, registro=print):
    """Productos consultados que siguen sin foto: buscarlos con el navegador."""
    from playwright.sync_api import sync_playwright
    base, headers = fp._conexion()
    indice = fp.leer_indice(base, headers)
    guardadas = fp.fotos_guardadas(base, headers)
    intentos = indice.get("navegador") or {}
    cola = [c for c, v in indice["sin_foto"].items()
            if not v.get("rechazada") and c not in guardadas and _toca(intentos.get(c))]
    cola += [c for c in indice["pendientes"] if c not in cola and c not in guardadas and _toca(intentos.get(c))]
    if not cola:
        return {"intentados": 0, "halladas": 0}
    halladas, marcas = 0, {}
    with sync_playwright() as p:
        try:
            navegador = p.chromium.launch(channel="chrome", headless=True)   # el Chrome de GitHub Actions
        except Exception:
            navegador = p.chromium.launch(headless=True)
        contexto = navegador.new_context(user_agent=fp.NAVEGADOR, locale="es-ES",
                                         viewport={"width": 1366, "height": 900}, device_scale_factor=2)
        pagina = contexto.new_page()
        for codigo in cola[:maximo]:
            nombre = fp._nombre_consultado(codigo)
            consulta = f"{nombre} {codigo}".strip() if nombre else codigo
            fuente = None
            # Primero nombre + código; si no aparece, solo por el nombre (de tu inventario).
            for texto, filtro in ((consulta, None), (nombre, nombre)):
                if not texto or fuente:
                    continue
                try:
                    fuente = buscar_uno(pagina, contexto, codigo, texto, base, headers, nombre_filtro=filtro)
                except Exception as exc:
                    registro(f"⚠️ {codigo}: {exc}")
            marcas[codigo] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if fuente:
                halladas += 1
                registro(f"📷 {codigo}: foto con el navegador ({fuente})")
        navegador.close()
    indice = fp.leer_indice(base, headers)      # releer: evaluar_y_guardar ya lo actualizó
    indice.setdefault("navegador", {}).update(marcas)
    fp.guardar_indice(indice, base, headers)
    return {"intentados": len(marcas), "halladas": halladas}


# ---------------------------------------------------------------- índice de tiendas sin catálogo público
# Algunas tiendas (p. ej. Merkapp) no tienen un catálogo que se pueda consultar, pero sus páginas de
# categorías muestran todos los productos al ir bajando. El navegador las recorre una vez por semana
# y arma un índice {código, nombre, foto}; después cualquier búsqueda usa ese índice al instante.
TIENDAS_INDEXADAS = (
    {"nombre": "Merkapp", "inicio": "https://www.merkapp.com/", "producto": "/products/", "categoria": "/collections/"},
)
DIAS_ENTRE_INDICES = 7
MAX_CATEGORIAS = 80
MAX_BAJADAS = 60

_EXTRAER = r"""(patron) => {
  const vistos = new Map();
  for (const a of document.querySelectorAll('a[href*="' + patron + '"]')) {
    const tarjeta = a.closest('li, article, [class*="card"], [class*="product"]') || a.parentElement;
    const img = a.querySelector('img') || (tarjeta && tarjeta.querySelector('img'));
    const src = img ? (img.currentSrc || img.src || img.getAttribute('data-src') || '') : '';
    let texto = (a.innerText || a.getAttribute('title') || (img && img.alt) || '').trim().split('\n')[0];
    if (!texto && tarjeta) texto = (tarjeta.innerText || '').trim().split('\n')[0];
    const actual = vistos.get(a.href) || {};
    vistos.set(a.href, {href: a.href, texto: actual.texto || texto, img: actual.img || src});
  }
  return Array.from(vistos.values());
}"""


def _codigo_de_foto(direccion):
    import re
    m = re.search(r"/(\d{8,14})_\d+\.(?:jpe?g|png|webp)", direccion or "", re.I)
    return m.group(1) if m else ""


def _nombre_de_enlace(href, patron):
    slug = href.split(patron, 1)[-1].split("?", 1)[0].strip("/")
    return slug.replace("-", " ")


def indexar_tienda(pagina, tienda, registro=print, hechas=(), hasta=None):
    """Recorre las categorías de una tienda con el navegador. Devuelve (productos, categorías hechas,
    terminó). Si se acaba el tiempo (hasta), sigue en la próxima vuelta desde donde quedó."""
    import time
    pagina.goto(tienda["inicio"], wait_until="domcontentloaded", timeout=45000)
    pagina.wait_for_timeout(2500)
    categorias = pagina.evaluate("""(patron) => Array.from(new Set(Array.from(document.querySelectorAll('a[href*="' + patron + '"]'))
        .map(a => a.href.split('#')[0].split('?')[0])))""", tienda["categoria"])
    productos, hechas, termino = {}, list(hechas), True
    for direccion in categorias[:MAX_CATEGORIAS]:
        if direccion in hechas:
            continue
        if hasta and time.time() > hasta:
            termino = False
            break
        try:
            pagina.goto(direccion, wait_until="domcontentloaded", timeout=45000)
            pagina.wait_for_timeout(2000)
            antes, quietas = -1, 0
            for _ in range(MAX_BAJADAS):
                pagina.mouse.wheel(0, 20000)
                pagina.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                pagina.wait_for_timeout(1200)
                cuenta = pagina.locator(f'a[href*="{tienda["producto"]}"]').count()
                quietas = quietas + 1 if cuenta == antes else 0
                antes = cuenta
                if quietas >= 3:
                    break
            for p in pagina.evaluate(_EXTRAER, tienda["producto"]):
                if not p.get("img") or "image_not_available" in p["img"]:
                    continue
                nombre = p.get("texto") or _nombre_de_enlace(p["href"], tienda["producto"])
                productos[p["href"]] = [_codigo_de_foto(p["img"]), nombre, p["img"]]
            hechas.append(direccion)
        except Exception as exc:
            registro(f"⚠️ {tienda['nombre']}: {direccion}: {exc}")
    return list(productos.values()), hechas, termino


def actualizar_indices(registro=print, forzar=False, minutos=8):
    """Arma (una vez por semana) el índice de las tiendas sin catálogo público, en tandas de unos
    minutos por vuelta para no pasar el tiempo de GitHub Actions."""
    import json
    import time
    hasta = time.time() + minutos * 60
    from playwright.sync_api import sync_playwright
    base, headers = fp._conexion()
    indices = fp.leer_indices_tiendas(base, headers)
    pendientes = [t for t in TIENDAS_INDEXADAS
                  if forzar or (indices.get(t["nombre"]) or {}).get("en_curso")
                  or _toca_dias((indices.get(t["nombre"]) or {}).get("fecha"), DIAS_ENTRE_INDICES)]
    if not pendientes:
        return {}
    resumen = {}
    with sync_playwright() as p:
        try:
            navegador = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            navegador = p.chromium.launch(headless=True)
        pagina = navegador.new_page(user_agent=fp.NAVEGADOR, locale="es-ES", viewport={"width": 1366, "height": 900})
        for tienda in pendientes:
            previo = indices.get(tienda["nombre"]) or {}
            curso = previo.get("en_curso") or {}
            productos, hechas, termino = indexar_tienda(pagina, tienda, registro, curso.get("hechas", ()), hasta)
            juntos = {p[2]: p for p in (curso.get("productos") or []) + productos}
            lista = list(juntos.values())
            if termino:
                indices[tienda["nombre"]] = {"fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                             "productos": lista or previo.get("productos") or []}
            else:   # sigue en la próxima vuelta; mientras, se usa el índice anterior
                indices[tienda["nombre"]] = {**previo, "en_curso": {"hechas": hechas, "productos": lista}}
            resumen[tienda["nombre"]] = len(lista)
            registro(f"🏪 {tienda['nombre']}: {len(lista)} productos en el índice"
                     + ("" if termino else " (continúa en la próxima vuelta)"))
        navegador.close()
    fp._subir(base, headers, fp.ARCHIVO_INDICES, json.dumps(indices, ensure_ascii=False).encode("utf-8"),
              "application/json")
    return resumen


def _toca_dias(marca, dias):
    if not marca:
        return True
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(marca) > timedelta(days=dias)
    except ValueError:
        return True
