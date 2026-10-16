import html
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title='Consulta de precios', page_icon='🏷️', layout='centered', initial_sidebar_state='collapsed')

SUPABASE_URL = str(st.secrets.get('SUPABASE_URL', '')).strip().rstrip('/')
SUPABASE_ANON_KEY = str(st.secrets.get('SUPABASE_ANON_KEY', '')).strip()

CSS = '''
<style>
.stApp {background:#f4f7fc;}
.block-container {max-width:960px;padding:1rem 1rem 2rem;}
#MainMenu, footer {visibility:hidden;}
header[data-testid="stHeader"] {background:transparent;}
.main-header {background:linear-gradient(135deg,#0c2e59,#0759c9);border-radius:20px;padding:clamp(14px,3vh,30px) 14px;text-align:center;color:white;margin-bottom:14px;}
.main-header h1 {color:white!important;font-size:clamp(22px,4vw,40px);margin:0;font-weight:850;}
.main-header p {color:#dceaff;font-size:clamp(12px,2vw,17px);margin:7px 0 0;}
.scan-title {text-align:center;color:#102b50;font-size:clamp(20px,3.5vw,34px);font-weight:850;margin:12px 0;}
div[data-testid="stTextInput"] input {text-align:center!important;font-size:clamp(19px,3vw,30px)!important;font-weight:750;min-height:58px;border-radius:14px;border:2px solid #d5e1f1;}
.product-card {background:white;border:1px solid #dce5f2;border-radius:22px;padding:clamp(20px,4vw,42px) 18px;text-align:center;margin:12px 0;box-shadow:0 7px 25px rgba(20,50,90,.07);}
.product-label,.price-label {color:#64748b;font-size:clamp(12px,2vw,17px);font-weight:800;letter-spacing:1.5px;}
.product-name {color:#102b50;font-size:clamp(24px,4.5vw,40px);font-weight:850;line-height:1.25;overflow-wrap:anywhere;margin:14px 0;}
.product-code {color:#64748b;font-size:clamp(15px,2.3vw,21px);overflow-wrap:anywhere;margin-bottom:24px;}
.product-price {color:#0757c3;font-size:clamp(40px,8vw,76px);font-weight:900;line-height:1.15;overflow-wrap:anywhere;margin-top:9px;}
@media (orientation:landscape) and (max-height:650px) {
.block-container {padding-top:.35rem;padding-bottom:.5rem;}
.main-header {padding:10px 12px;margin-bottom:7px;}
.main-header h1 {font-size:clamp(19px,3vw,29px);}
.main-header p {font-size:12px;margin-top:2px;}
.scan-title {font-size:clamp(17px,2.5vw,25px);margin:5px 0;}
div[data-testid="stTextInput"] input {min-height:46px;font-size:22px!important;}
.product-card {padding:12px 18px;margin:3px 0;}
.product-name {font-size:clamp(20px,4vw,34px);margin:6px 0;}
.product-code {margin-bottom:8px;}
.product-price {font-size:clamp(36px,7vw,65px);margin-top:3px;}
}
@media (max-width:600px) {.block-container {padding-left:10px;padding-right:10px;}.product-card {border-radius:16px;}}
</style>
'''
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_data(ttl=90, show_spinner=False)
def catalog():
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise ValueError('Faltan SUPABASE_URL o SUPABASE_ANON_KEY en Streamlit Secrets.')
    headers = {'apikey': SUPABASE_ANON_KEY, 'Authorization': f'Bearer {SUPABASE_ANON_KEY}'}
    products = []
    page_size = 500
    offset = 0
    while True:
        response = requests.get(
            f'{SUPABASE_URL}/rest/v1/products',
            params={'select': 'barcode,name,price', 'order': 'barcode.asc', 'limit': page_size, 'offset': offset},
            headers=headers,
            timeout=25,
        )
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError('Respuesta inesperada de Supabase.')
        products.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return pd.DataFrame(products, columns=['barcode', 'name', 'price'])


for key, default in (
    ('search_input', ''),
    ('current_product', None),
    ('result_time', None),
    ('not_found', False),
):
    if key not in st.session_state:
        st.session_state[key] = default


def buscar_producto():
    barcode = st.session_state.search_input.strip()
    if not barcode:
        return
    data = catalog()
    matches = data[data['barcode'].astype(str).str.strip() == barcode].head(1)
    st.session_state.current_product = None if matches.empty else matches.iloc[0].to_dict()
    st.session_state.not_found = matches.empty
    st.session_state.result_time = time.monotonic()


@st.fragment(run_every=0.5)
def verificador():
