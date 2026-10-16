import html
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Consulta de precios", page_icon="🏷️", layout="wide", initial_sidebar_state="collapsed")

SUPABASE_URL = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
SUPABASE_ANON_KEY = str(st.secrets.get("SUPABASE_ANON_KEY", "")).strip()

st.markdown("""
<style>
* { box-sizing: border-box; }
.stApp { background: #f4f7fc; }
.block-container { width: 100%; max-width: 1100px; padding: 12px 16px 20px; }
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stSidebarNav"], [data-testid="stStatusWidget"] { display: none !important; }
header[data-testid="stHeader"] { height: 0; background: transparent; }
[data-testid="stAppViewContainer"] { overflow-x: hidden; }
.wait-heading { background: linear-gradient(110deg,#0b2f5c,#075ac9); color:white; border-radius:15px; padding:16px; text-align:center; }
.wait-heading h1 { color:white !important; margin:0; font-size:clamp(22px,4.5vw,36px); line-height:1.12; font-weight:850; }
.wait-heading p { margin:6px 0 0; font-size:clamp(12px,2vw,17px); color:#e5efff; }
.scan-prompt { color:#102b50; font-size:clamp(20px,3.5vw,30px); font-weight:850; margin:12px 0 8px; text-align:center; }
[data-testid="stTextInput"] { max-width:650px; margin:0 auto; }
[data-testid="stTextInput"] input { min-height:52px; text-align:center !important; font-size:23px !important; font-weight:750; border:2px solid #d5e1f1; border-radius:12px; background:white; color:#102b50; }
[data-testid="stImage"] { max-width:140px; margin:8px auto; }
.product-card { width:100%; background:white; border:1px solid #dce5f2; border-radius:20px; box-shadow:0 7px 25px rgba(20,50,90,.08); padding:clamp(16px,3vh,30px) 20px; margin:12px auto; text-align:center; }
.product-label, .price-label { color:#64748b; font-size:clamp(12px,2vw,17px); font-weight:800; letter-spacing:1px; }
.product-name { color:#102b50; font-size:clamp(23px,4.5vw,43px); font-weight:850; line-height:1.12; overflow-wrap:anywhere; margin:12px 0; }
.product-code { color:#64748b; font-size:clamp(13px,2vw,18px); overflow-wrap:anywhere; margin:0 0 16px; }
.product-price { color:#0757c3; font-size:clamp(42px,9vw,90px); font-weight:900; line-height:1.05; overflow-wrap:anywhere; margin-top:8px; }
.not-found { background:white; border-radius:16px; padding:25px 15px; text-align:center; color:#9b1c1c; font-size:clamp(23px,5vw,42px); font-weight:800; }

/* LECTOR HORIZONTAL: dos zonas y altura reducida */
@media (orientation: landscape) and (max-height: 650px) {
  .block-container { max-width:none; padding:5px 12px 8px; }
  .wait-heading { padding:8px 12px; border-radius:10px; }
  .wait-heading h1 { font-size:clamp(20px,3.8vw,29px); }
  .wait-heading p { font-size:12px; margin-top:2px; }
  [data-testid="stImage"] { max-width:85px; margin:2px auto; }
  .scan-prompt { font-size:clamp(18px,3.1vw,26px); margin:4px 0; }
  [data-testid="stTextInput"] input { min-height:42px; font-size:20px !important; }
  .product-card { display:grid; grid-template-columns: minmax(0,1fr) minmax(0,0.95fr); align-items:center; gap:10px; min-height:min(88dvh, 360px); padding:12px 18px; margin:4px auto; }
  .product-info { min-width:0; border-right:1px solid #e5ebf4; padding-right:12px; }
  .product-name { font-size:clamp(20px,3.6vw,35px); margin:8px 0; }
  .product-code { font-size:clamp(12px,1.9vw,17px); margin-bottom:0; }
  .price-info { min-width:0; }
  .product-price { font-size:clamp(35px,7vw,78px); margin-top:6px; }
  .not-found { padding:15px; }
}
/* PANTALLA VERTICAL: tarjeta en una columna */
@media (orientation: portrait) {
  .block-container { max-width:680px; padding:16px 12px; }
  .product-card { display:block; padding:24px 14px; }
  .product-name { font-size:clamp(24px,6vw,40px); }
  .product-price { font-size:clamp(42px,11vw,80px); }
}
@media (max-width:380px) {
  .wait-heading h1 { font-size:20px; }
  .scan-prompt { font-size:18px; }
  .product-price { font-size:40px; }
}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=90, show_spinner=False)
def catalog():
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise ValueError("Falta configurar Supabase.")
    headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"}
    products = []
    offset = 0
    page_size = 500
    while True:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/products",
            params={"select": "barcode,name,price", "order": "barcode.asc", "limit": page_size, "offset": offset},
            headers=headers, timeout=25,
        )
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError("Respuesta inesperada de Supabase.")
        products.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return pd.DataFrame(products, columns=["barcode", "name", "price"])

for key, default in {"search_input": "", "current_product": None, "result_time": None, "not_found": False}.items():
    if key not in st.session_state:
        st.session_state[key] = default
