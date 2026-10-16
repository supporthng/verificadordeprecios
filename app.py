import html
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title='Consulta de precios', page_icon='🏷️', layout='centered', initial_sidebar_state='collapsed')

st.markdown('''<style>
.stApp {background:#f4f7fc;}
.block-container {max-width:950px; padding:1.2rem 1rem 2rem;}
#MainMenu,footer {visibility:hidden;}
header[data-testid="stHeader"] {background:transparent;}
.hero {background:linear-gradient(120deg,#0c2e59,#0759c9);color:white;text-align:center;border-radius:18px;padding:20px 12px;}
.hero h1 {color:white;margin:0;font-size:clamp(23px,4vw,38px);}
.hero p {margin:6px 0 0;color:#dceaff;}
.scan {text-align:center;color:#102b50;font-size:clamp(19px,3vw,30px);font-weight:800;margin:16px 0 10px;}
.product {background:white;border:1px solid #dce5f2;border-radius:20px;padding:clamp(14px,4vh,35px) 14px;text-align:center;}
.name {font-size:clamp(22px,4.5vw,40px);font-weight:850;color:#102b50;overflow-wrap:anywhere;line-height:1.15;margin:12px 0;}
.code {color:#64748b;font-size:clamp(13px,2vw,19px);overflow-wrap:anywhere;}
.price {color:#0757c3;font-size:clamp(38px,8vw,75px);font-weight:900;line-height:1.1;overflow-wrap:anywhere;margin-top:8px;}
.label {color:#64748b;font-size:13px;font-weight:800;letter-spacing:1px;}
div[data-testid="stTextInput"] input {text-align:center;font-size:26px;min-height:58px;border-radius:14px;}
@media (orientation:landscape) and (max-height:650px) {
.block-container {padding:.3rem .7rem .7rem;}
.hero {padding:8px;}
.hero h1 {font-size:clamp(18px,4vh,26px);}
.hero p {font-size:12px;margin:2px 0 0;}
.scan {margin:6px 0;font-size:19px;}
.product {padding:12px;}
.name {font-size:clamp(19px,5vh,32px);margin:6px 0;}
.price {font-size:clamp(35px,10vh,68px);}
}
</style>''', unsafe_allow_html=True)

@st.cache_data(ttl=90, show_spinner=False)
def catalog():
    url = str(st.secrets.get('SUPABASE_URL', '')).strip().rstrip('/')
    key = str(st.secrets.get('SUPABASE_ANON_KEY', '')).strip()
    if not url or not key:
        raise ValueError('Faltan SUPABASE_URL o SUPABASE_ANON_KEY en Streamlit Secrets.')
    headers = {'apikey': key, 'Authorization': f'Bearer {key}'}
    rows = []
    offset = 0
    while True:
        response = requests.get(
            f'{url}/rest/v1/products',
            params={'select':'barcode,name,price','order':'barcode.asc','limit':500,'offset':offset},
            headers=headers, timeout=25,
        )
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError('Respuesta de Supabase no válida.')
        rows.extend(batch)
        if len(batch) < 500:
            break
        offset += 500
    return pd.DataFrame(rows, columns=['barcode','name','price'])

for key, value in {'scan_code':'','product':None,'started':None,'missing':False}.items():
    if key not in st.session_state:
        st.session_state[key] = value

def scan():
    code = str(st.session_state.scan_code).strip()
    if not code:
        return
    df = catalog()
    found = df.loc[df['barcode'].astype(str).str.strip() == code]
    st.session_state.product = None if found.empty else found.iloc[0].to_dict()
    st.session_state.missing = found.empty
    st.session_state.started = time.monotonic()

# El encabezado de diagnóstico se mantiene fuera del fragmento para evitar una pantalla totalmente vacía.
if not hasattr(st, 'fragment'):
    st.error('Esta versión de Streamlit no admite st.fragment. Actualiza Streamlit en requirements.txt.')
    st.stop()

@st.fragment(run_every=0.5)
def pantalla():
    started = st.session_state.started
    if started is not None and time.monotonic() - started >= 10:
        st.session_state.product = None
        st.session_state.missing = False
        st.session_state.started = None
        st.session_state.scan_code = ''

    product = st.session_state.product
    if product is not None:
        name = html.escape(str(product['name']))
        code = html.escape(str(product['barcode']))
        try:
            price = float(product['price'])
