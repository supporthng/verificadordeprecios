import requests
import pandas as pd
import streamlit as st
from supabase_cliente import cabeceras, clave_servidor, clave_publica

PAGE_SIZE = 1000


def api(method, table, params=None, data=None, admin=True, prefer=None):
    url = str(st.secrets['SUPABASE_URL']).rstrip('/')
    key = clave_servidor() if admin else clave_publica()
    headers = cabeceras(key, {'Content-Type': 'application/json'})
    if prefer:
        headers['Prefer'] = prefer
    r = requests.request(method, f'{url}/rest/v1/{table}', params=params, json=data,
                         headers=headers, timeout=50)
    if not r.ok:
        raise RuntimeError(f'Supabase {r.status_code}: {r.text[:500]}')
    return r.json() if r.content else []


def all_inventories():
    return api('GET', 'price_inventories', {'select': 'id,name,is_active', 'order': 'name.asc'})


@st.cache_data(ttl=15, show_spinner=False)
def active_inventory_id():
    """Id del inventario activo, o None. Caché corta para reflejar cambios pronto."""
    rows = api('GET', 'price_inventories',
               {'select': 'id', 'is_active': 'eq.true', 'limit': 1}, admin=False)
    return rows[0]['id'] if rows else None


def find_barcode(code, inventory_id=None):
    """Busca UN código en el inventario activo (o en inventory_id) usando la clave primaria.

    Devuelve dict {barcode, name, price} o None si no existe.
    Lanza RuntimeError si no hay inventario activo.
    """
    from shared import variantes_codigo
    formas = variantes_codigo(code)
    # Un inventario que no es el activo (el de una sucursal) solo se lee con la clave del servidor.
    privado = inventory_id is not None
    if inventory_id is None:
        inventory_id = active_inventory_id()
    if inventory_id is None:
        raise RuntimeError('No hay un inventario activo seleccionado.')
    # Una sola consulta con todas las formas equivalentes (UPC-E, UPC-A, EAN-13,
    # sin ceros iniciales). Gana la forma más parecida a la leída.
    lista = ','.join('"' + f.replace('"', '') + '"' for f in formas)
    rows = api('GET', 'price_inventory_items',
               {'select': 'barcode,name,price', 'inventory_id': f'eq.{inventory_id}',
                'barcode': f'in.({lista})', 'limit': len(formas)}, admin=privado)
    if not rows:
        return None
    rows.sort(key=lambda r: formas.index(r['barcode']) if r['barcode'] in formas else len(formas))
    return rows[0]


def active_catalog():
    """Catálogo completo del inventario activo (solo para listados, no para buscar)."""
    inventory_id = active_inventory_id()
    if inventory_id is None:
        return pd.DataFrame(columns=['barcode', 'name', 'price'])
    rows, offset = [], 0
    while True:
        # El orden estable evita filas saltadas o repetidas entre páginas.
        batch = api('GET', 'price_inventory_items',
                    {'select': 'barcode,name,price', 'inventory_id': f'eq.{inventory_id}',
                     'order': 'barcode.asc', 'limit': PAGE_SIZE, 'offset': offset}, admin=False)
        if not batch:
            break
        rows += batch
        # Avanzar según lo recibido: funciona aunque Supabase limite max-rows.
        offset += len(batch)
    return pd.DataFrame(rows, columns=['barcode', 'name', 'price'])
