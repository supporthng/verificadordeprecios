"""Registro de consultas de precios (tabla price_lookup_log de Supabase).

registrar() guarda cada consulta EN SEGUNDO PLANO: el cliente ve el precio sin
esperar, y si el registro falla (sin tabla, sin red) la consulta no se afecta.
"""
import threading
from datetime import datetime, timedelta, timezone

import requests

from supabase_cliente import cabeceras, clave_servidor, url

TABLA = "price_lookup_log"


def _num(valor):
    try:
        return round(float(valor), 2)
    except (TypeError, ValueError):
        return None


def registrar(codigo, encontrado, producto=None, fuente=None, canal=None, sucursal=None):
    """Anota una consulta. Nunca lanza errores ni demora la respuesta."""
    try:
        base, clave = url(), clave_servidor()
        codigo = str(codigo or "").strip()[:64]
        if not base or not clave or not codigo:
            return
        producto = producto if isinstance(producto, dict) else {}
        fila = {
            "barcode": codigo,
            "found": bool(encontrado),
            "product_name": (str(producto.get("name") or "")[:200] or None) if encontrado else None,
            "price": _num(producto.get("price")) if encontrado else None,
            "source": (str(fuente)[:20] if fuente else None),
            "channel": (str(canal)[:20] if canal else None),
        }
        if sucursal:   # solo con sucursales (MIGRACION_006): antes la columna no existe
            fila["sucursal"] = str(sucursal)[:30]
        destino = f"{base}/rest/v1/{TABLA}"
        encabezados = cabeceras(clave, {"Content-Type": "application/json", "Prefer": "return=minimal"})

        def _enviar():
            try:
                requests.post(destino, json=fila, headers=encabezados, timeout=6)
            except requests.RequestException:
                pass

        threading.Thread(target=_enviar, name="registro-consulta", daemon=True).start()
        if encontrado:
            # Primera consulta de un producto sin foto: buscarla en internet, en segundo plano.
            import fotos_productos
            fotos_productos.asegurar_en_segundo_plano(codigo)
    except Exception:
        pass


def leer(desde, hasta=None, limite=50000, sucursal=None):
    """Filas del registro entre dos fechas (UTC), más recientes primero.
    sucursal: código de una sucursal para ver solo sus consultas (None = todas)."""
    base, clave = url(), clave_servidor()
    columnas = "created_at,barcode,found,product_name,price,source,channel"
    params = {"select": columnas + ",sucursal", "created_at": f"gte.{desde.isoformat()}", "order": "created_at.desc"}
    if sucursal:
        params["sucursal"] = f"eq.{sucursal}"
    if hasta is not None:
        params["and"] = f"(created_at.lt.{hasta.isoformat()})"
    filas, inicio, bloque = [], 0, 1000
    while inicio < limite:
        r = requests.get(f"{base}/rest/v1/{TABLA}", params={**params, "offset": inicio, "limit": bloque},
                         headers=cabeceras(clave), timeout=30)
        if not r.ok and "sucursal" in r.text and not sucursal and "sucursal" in params["select"]:
            params["select"] = columnas          # todavía sin MIGRACION_006
            continue
        if not r.ok:
            raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
        lote = r.json()
        filas += lote
        if len(lote) < bloque:
            break
        inicio += len(lote)
    return filas


def borrar_anteriores(dias):
    """Elimina los registros con más de `dias` días. Devuelve cuántos borró (si Supabase lo informa)."""
    base, clave = url(), clave_servidor()
    limite = datetime.now(timezone.utc) - timedelta(days=int(dias))
    r = requests.delete(f"{base}/rest/v1/{TABLA}", params={"created_at": f"lt.{limite.isoformat()}"},
                        headers=cabeceras(clave, {"Prefer": "count=exact,return=minimal"}), timeout=60)
    if not r.ok:
        raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
    rango = r.headers.get("Content-Range", "")
    total = rango.rsplit("/", 1)[-1] if "/" in rango else ""
    return int(total) if total.isdigit() else None
