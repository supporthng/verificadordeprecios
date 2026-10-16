import html
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Consulta de precios", page_icon="🏷️", layout="centered", initial_sidebar_state="collapsed")

SUPABASE_URL = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
SUPABASE_ANON_KEY = str(st.secrets.get("SUPABASE_ANON_KEY", "")).strip()

st.markdown("""
<style>
.stApp { background: #f3f7fd; }
.block-container { max-width: 980px; padding: 1.25rem 1rem 2rem; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebarNav"] { display: none; }
.main-header { background: linear-gradient(120deg,#0b315f,#075ac8); border-radius: 18px; padding: 20px 12px; text-align: center; color: white; }
.main-header h1 { color: white; font-size: clamp(23px,4vw,38px); margin: 0; font-weight: 850; }
.main-header p { color: #dbeafe; margin: 6px 0 0; font-size: clamp(13px,2vw,17px); }
.scan-title { text-align:center; color:#102b50; font-weight:850; font-size:clamp(20px,3vw,29px); margin: 18px 0 12px; }
div[data-testid="stTextInput"] input { text-align:center; font-size:clamp(22px,4vw,30px); font-weight:750; min-height:60px; border:2px solid #d5e1f1; border-radius:14px; }
.product-card { background:#fff; border:1px solid #dce5f2; border-radius:22px; padding:clamp(18px,4vh,36px) 20px; text-align:center; box-shadow:0 7px 25px rgba(20,50,90,.07); }
.product-label,.price-label { color:#64748b; font-weight:800; letter-spacing:1.5px; font-size:clamp(12px,1.8vw,16px); }
.product-name { color:#102b50; font-size:clamp(24px,4.8vw,40px); font-weight:850; line-height:1.2; overflow-wrap:anywhere; margin:12px 0; }
.product-code { color:#64748b; font-size:clamp(15px,2vw,20px); overflow-wrap:anywhere; margin-bottom:20px; }
.product-price { color:#0757c3; font-size:clamp(38px,8vw,76px); font-weight:900; line-height:1.1; overflow-wrap:anywhere; margin-top:8px; }
@media (max-width: 600px) { .block-container { padding:.7rem .7rem 1.2rem; } .main-header { padding:16px 10px; } .product-card { padding:22px 12px; } }
@media (orientation: landscape) and (max-height: 650px) {
 .block-container { padding:.3rem .7rem .6rem; }
 .main-header { padding:9px 12px; border-radius:12px; }
 .main-header h1 { font-size:clamp(19px,4vh,28px); }
 .main-header p { font-size:12px; margin-top:2px; }
 .scan-title { margin:6px 0; font-size:clamp(16px,4vh,24px); }
 div[data-testid="stTextInput"] input { min-height:45px; font-size:22px; }
 .product-card { padding:12px 18px; border-radius:14px; }
 .product-name { font-size:clamp(20px,5vh,32px); margin:6px 0; }
 .product-code { margin-bottom:8px; font-size:14px; }
 .product-price { font-size:clamp(34px,11vh,70px); margin-top:4px; }
 .product-label,.price-label { font-size:12px; }
}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=90, show_spinner=False)
def catalog():
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise ValueError("Falta configurar Supabase en Streamlit Secrets.")
    headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"}
    rows = []
    page_size = 500
    offset = 0
    while True:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/products",
            params={"select": "barcode,name,price", "order": "barcode.asc", "limit": page_size, "offset": offset},
            headers=headers,
            timeout=25,
        )
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError("Respuesta inesperada de Supabase.")
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return pd.DataFrame(rows, columns=["barcode", "name", "price"])

for key, default in {
    "search_input": "",
    "current_product": None,
    "result_time": None,
    "not_found": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

def buscar_producto():
    query = st.session_state.search_input.strip()
    if not query:
        return
    df = catalog()
    hits = df[df["barcode"].astype(str).str.strip() == query].head(1)
    st.session_state.current_product = None if hits.empty else hits.iloc[0].to_dict()
    st.session_state.not_found = hits.empty
    st.session_state.result_time = time.monotonic()

@st.fragment(run_every=0.5)
def verificador():
    started = st.session_state.result_time
    if started is not None and time.monotonic() - started >= 10:
        st.session_state.current_product = None
