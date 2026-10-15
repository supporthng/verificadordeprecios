import io
import math
import re
import unicodedata
import pandas as pd
import requests
import streamlit as st


def secret(name):
    return str(st.secrets.get(name, '')).strip()


def supabase_url():
    return secret('SUPABASE_URL').rstrip('/')


@st.cache_data(ttl=90, show_spinner=False)
def catalog():
    url, key = supabase_url(), secret('SUPABASE_ANON_KEY')
    if not url or not key:
        raise ValueError('Falta la configuración pública de Supabase.')
    headers = {'apikey': key, 'Authorization': f'Bearer {key}'}
    rows, offset, size = [], 0, 500
    while True:
        response = requests.get(f'{url}/rest/v1/products', params={
            'select': 'barcode,name,price', 'order': 'barcode.asc',
            'limit': size, 'offset': offset}, headers=headers, timeout=30)
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError('Respuesta inesperada del catálogo.')
        rows.extend(batch)
        if len(batch) < size:
            break
        offset += size
    return pd.DataFrame(rows, columns=['barcode', 'name', 'price'])


def normalize_header(value):
    value = unicodedata.normalize('NFKD', str(value))
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', value.lower())


def parse_excel(file):
    df = pd.read_excel(io.BytesIO(file.getvalue()), dtype=str, engine='openpyxl')
    names = {normalize_header(c): c for c in df.columns}
    def column(*options):
        return next((names[o] for o in options if o in names), None)
    nc = column('nombre', 'descripcion', 'producto')
    bc = column('codigobarra', 'codigobarras', 'codigo', 'barcode')
    pc = column('precioventa', 'precio')
    if any(c is None for c in (nc, bc, pc)):
        raise ValueError('El Excel requiere Nombre, Código Barra y Precio Venta.')
    products = []
    for _, row in df.iterrows():
        name = str(row[nc]).strip() if pd.notna(row[nc]) else ''
        barcode = str(row[bc]).strip() if pd.notna(row[bc]) else ''
        if barcode.endswith('.0'):
            barcode = barcode[:-2]
        raw_price = str(row[pc]).strip() if pd.notna(row[pc]) else ''
        try:
            price = float(raw_price.replace(',', ''))
        except ValueError:
            continue
        if not name or not barcode or not math.isfinite(price) or price < 0:
            continue
        products.append({'barcode': barcode, 'name': name, 'price': round(price, 2)})
    if not products:
        raise ValueError('No se encontraron productos válidos.')
    return pd.DataFrame(products).drop_duplicates('barcode', keep='last')


def publish(products):
    url, key = supabase_url(), secret('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        raise ValueError('Falta la configuración administrativa de Supabase.')
    headers = {'apikey': key, 'Authorization': f'Bearer {key}',
               'Content-Type': 'application/json',
               'Prefer': 'resolution=merge-duplicates,return=minimal'}
    for start in range(0, len(products), 200):
        payload = products.iloc[start:start+200].to_dict('records')
        response = requests.post(f'{url}/rest/v1/products',
            params={'on_conflict': 'barcode'}, headers=headers, json=payload, timeout=35)
        response.raise_for_status()
    catalog.clear()
