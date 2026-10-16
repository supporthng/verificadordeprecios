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
.stApp { background: #f4f7fc; }
.block-container { width: 100%; max-width: 1000px; padding: 24px 18px 36px; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.wait-heading { background: linear-gradient(135deg,#0c2e59,#0759c9); border-radius:22px; padding:28px 16px; text-align:center; color:white; }
.wait-heading h1 { margin:0; color:white !important; font-size:clamp(23px,4vw,40px); font-weight:850; line-height:1.15; }
.wait-heading p { color:#e3eeff; margin:9px 0 0; font-size:clamp(13px,2vw,18px); }
.scan-prompt { text-align:center; font-size:clamp(20px,3vw,30px); font-weight:850; color:#102b50; margin:18px 0 12px; }
[data-testid="stTextInput"] { max-width:650px; margin:0 auto; }
[data-testid="stTextInput"] input { text-align:center !important; font-size:clamp(20px,3vw,30px) !important; font-weight:750; min-height:60px; border-radius:14px; border:2px solid #d5e1f1; background:white; color:#102b50; }
.product-card { background:white; border:1px solid #dce5f2; border-radius:24px; box-shadow:0 7px 25px rgba(20,50,90,.08); padding:clamp(22px,5vw,44px); margin:15px auto; text-align:center; width:100%; }
.product-label,.price-label { color:#64748b; font-size:clamp(13px,1.8vw,17px); font-weight:800; letter-spacing:1.5px; }
.product-name { color:#102b50; font-size:clamp(25px,4vw,43px); font-weight:850; line-height:1.18; overflow-wrap:anywhere; margin:15px 0; }
.product-code { color:#64748b; font-size:clamp(14px,2vw,20px); overflow-wrap:anywhere; margin:0 0 28px; }
.product-price { color:#0757c3; font-size:clamp(42px,7vw,82px); font-weight:900; line-height:1.12; overflow-wrap:anywhere; margin-top:12px; }
.not-found { background:white; border-radius:20px; padding:30px 16px; text-align:center; color:#a32222; font-size:clamp(24px,4vw,40px); font-weight:850; }
/* Solo lectores y móviles realmente horizontales con poca altura. No afecta escritorio. */
@media (orientation:landscape) and (max-height:600px) and (max-width:950px) {
 .block-container { padding:8px 12px 12px; max-width:100%; }
 .wait-heading { padding:12px 14px; border-radius:12px; }
 .wait-heading h1 { font-size:clamp(20px,3vw,30px); }
 .wait-heading p { font-size:12px; margin-top:3px; }
 .scan-prompt { font-size:clamp(18px,2.6vw,26px); margin:6px 0; }
 [data-testid="stTextInput"] input { min-height:44px; font-size:21px !important; }
 .product-card { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:12px; align-items:center; min-height:65vh; padding:12px 16px; border-radius:14px; margin:4px auto; }
 .product-info { min-width:0; padding-right:12px; border-right:1px solid #e5ebf4; }
 .product-name { font-size:clamp(21px,3vw,34px); margin:9px 0; }
 .product-code { font-size:clamp(12px,1.6vw,16px); margin-bottom:0; }
 .product-price { font-size:clamp(37px,6vw,72px); }
}
@media (max-width:600px) and (orientation:portrait) {
 .block-container { padding:14px 12px 24px; }
 .wait-heading { padding:22px 12px; border-radius:17px; }
 .product-card { padding:25px 14px; border-radius:18px; }
 .product-code { margin-bottom:22px; }
 .product-price { font-size:clamp(42px,10vw,68px); }
}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=90, show_spinner=False)
def catalog():
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise ValueError("Falta configurar Supabase en Streamlit Secrets.")
    headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"}
    rows = []
    offset = 0
    while True:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/products",
            params={"select":"barcode,name,price", "order":"barcode.asc", "limit":500, "offset":offset},
            headers=headers, timeout=25,
        )
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError("Supabase devolvió una respuesta inesperada.")
        rows.extend(batch)
        if len(batch) < 500:
            break
        offset += 500
    return pd.DataFrame(rows, columns=["barcode","name","price"])

for key, value in {"search_input":"", "current_product":None, "result_time":None, "not_found":False}.items():
    if key not in st.session_state:
        st.session_state[key] = value

def buscar_producto():
    code = str(st.session_state.search_input).strip()
    if not code:
        return
    df = catalog()
    match = df[df["barcode"].astype(str).str.strip().eq(code)].head(1)
    st.session_state.current_product = None if match.empty else match.iloc[0].to_dict()
    st.session_state.not_found = match.empty
    st.session_state.result_time = time.monotonic()

@st.fragment(run_every=0.5)
def verificador():
    started = st.session_state.result_time
    if started is not None and time.monotonic() - started >= 10:
