import html
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Consulta de precios", page_icon="🏷️", layout="centered", initial_sidebar_state="collapsed")

URL = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
KEY = str(st.secrets.get("SUPABASE_ANON_KEY", "")).strip()

st.markdown("""<style>
.stApp{background:#f4f7fc}.block-container{max-width:900px;padding:clamp(12px,3vw,30px) clamp(12px,3vw,25px) 35px}
#MainMenu,footer{visibility:hidden}header[data-testid="stHeader"]{background:transparent}
.main-header{background:linear-gradient(135deg,#0c2e59,#0759c9);border-radius:23px;padding:30px 16px;text-align:center;color:white;margin:8px 0 24px;box-shadow:0 8px 25px #0a326e26}
.main-header h1{color:white!important;font-size:clamp(24px,5vw,43px);font-weight:850;margin:0}.main-header p{color:#dceaff;font-size:clamp(14px,2.5vw,18px);margin:10px 0 0}
.scan-title{text-align:center;color:#102b50;font-size:clamp(23px,4vw,35px);font-weight:850;margin:24px 0 16px}
div[data-testid="stTextInput"] input{text-align:center!important;font-size:clamp(20px,5vw,30px)!important;font-weight:750!important;letter-spacing:1px;min-height:68px;border-radius:16px;border:2px solid #d5e1f1;background:white;color:#102b50}
.product-card{background:white;border:1px solid #dce5f2;border-radius:24px;padding:clamp(28px,6vw,44px) clamp(14px,4vw,28px);margin:clamp(10px,3vw,22px) 0;text-align:center;box-shadow:0 7px 25px #14325a0f}
.product-label,.price-label{color:#64748b;font-size:clamp(14px,2.5vw,17px);font-weight:800;letter-spacing:1.5px}.product-label{margin-bottom:20px}.price-label{margin-bottom:14px}
.product-name{color:#102b50;font-size:clamp(25px,5vw,40px);font-weight:850;line-height:1.25;overflow-wrap:anywhere;margin-bottom:18px}
.product-code{color:#64748b;font-size:clamp(16px,3vw,22px);overflow-wrap:anywhere;margin-bottom:32px}
.product-price{color:#0757c3;font-size:clamp(39px,9vw,70px);font-weight:900;line-height:1.1;overflow-wrap:anywhere}
@media(max-width:600px){.block-container{padding:12px 12px 30px}.main-header{padding:23px 12px;border-radius:18px;margin-bottom:18px}.product-card{border-radius:18px}div[data-testid="stTextInput"] input{min-height:62px}}
</style>""", unsafe_allow_html=True)

@st.cache_data(ttl=60, show_spinner=False)
def catalog():
    if not URL or not KEY:
        raise ValueError("Falta configurar Supabase")
    headers = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    rows = []
    offset = 0
    while True:
        r = requests.get(f"{URL}/rest/v1/products", headers=headers, params={"select":"barcode,name,price", "order":"barcode.asc", "limit":500, "offset":offset}, timeout=25)
        r.raise_for_status()
        batch = r.json()
        if not isinstance(batch, list):
            raise ValueError("Respuesta inesperada")
        rows.extend(batch)
        if len(batch) < 500:
            break
        offset += 500
    return pd.DataFrame(rows, columns=["barcode","name","price"])

for key, default in {"search_input":"", "current_product":None, "result_time":None, "not_found":False}.items():
    if key not in st.session_state:
        st.session_state[key] = default

def buscar_producto():
    code = st.session_state.search_input.strip()
    if not code:
        return
    df = catalog()
    matches = df[df["barcode"].astype(str).str.strip() == code].head(1)
    st.session_state.current_product = None if matches.empty else matches.iloc[0].to_dict()
    st.session_state.not_found = matches.empty
    st.session_state.result_time = time.monotonic()

@st.fragment(run_every=0.5)
def verificador():
    started = st.session_state.result_time
    if started is not None and time.monotonic() - started >= 10:
        st.session_state.current_product = None
        st.session_state.not_found = False
        st.session_state.result_time = None
        st.session_state.search_input = ""

    product = st.session_state.current_product
    if product is not None:
        name = html.escape(str(product["name"]))
        code = html.escape(str(product["barcode"]))
        price = float(product["price"])
        st.markdown(f'<div class="product-card"><div class="product-label">PRODUCTO</div><div class="product-name">{name}</div><div class="product-code">Código: {code}</div><div class="price-label">PRECIO DE VENTA</div><div class="product-price">RD$ {price:,.2f}</div></div>', unsafe_allow_html=True)
    elif st.session_state.not_found:
        st.warning("Producto no encontrado")
    else:
        st.markdown('<div class="main-header"><h1>🏷️ CONSULTA DE PRECIOS</h1><p>Consulta rápida de productos y precios</p></div>', unsafe_allow_html=True)
        image = Path("assets/barcode.png")
        if image.is_file():
            a,b,c = st.columns([1.4,1,1.4])
            with b:
                st.image(str(image), use_container_width=True)
        st.markdown('<div class="scan-title">ESCANEA TU CÓDIGO AQUÍ</div>', unsafe_allow_html=True)
        st.text_input("Código de barras", key="search_input", on_change=buscar_producto, label_visibility="collapsed")

try:
    verificador()
except (requests.RequestException, ValueError, TypeError):
    st.error("No se pudo consultar Supabase. Verifica la conexión.")
