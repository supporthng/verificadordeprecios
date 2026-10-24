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
MAX_POR_VUELTA = 15


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
