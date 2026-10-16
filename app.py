import html
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Consulta de precios",
    page_icon="🏷️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

SUPABASE_URL = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
SUPABASE_ANON_KEY = str(st.secrets.get("SUPABASE_ANON_KEY", "")).strip()

CSS = """
<style>
.stApp { background: #f4f7fc; }
.block-container { max-width: 950px; padding: 1rem 1rem 2rem; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.main-header {
    background: linear-gradient(135deg, #0c2e59, #0759c9);
    border-radius: 20px;
    padding: 22px 16px;
    color: white;
    text-align: center;
    margin-bottom: 15px;
}
.main-header h1 { color: white !important; margin: 0; font-size: clamp(23px, 4vw, 40px); }
.main-header p { color: #dceaff; margin: 7px 0 0; font-size: clamp(13px, 2vw, 17px); }
.scan-title { text-align: center; font-size: clamp(20px, 3vw, 32px);
    color: #102b50; font-weight: 850; margin: 12px 0; }
div[data-testid="stTextInput"] input {
    text-align: center !important; font-size: clamp(20px, 3vw, 30px) !important;
    font-weight: 750; min-height: 60px; border: 2px solid #d5e1f1;
    border-radius: 14px; background: white; color: #102b50;
}
.product-card { background: white; border: 1px solid #dce5f2;
    border-radius: 22px; padding: 28px 20px; text-align: center;
    box-shadow: 0 7px 25px rgba(20, 50, 90, .07); }
.product-label, .price-label { color: #64748b; font-weight: 800;
    font-size: clamp(12px, 1.7vw, 17px); letter-spacing: 1px; }
.product-name { color: #102b50; font-weight: 850; line-height: 1.2;
    font-size: clamp(23px, 4.5vw, 41px); overflow-wrap: anywhere;
    margin: 12px 0; }
.product-code { color: #64748b; font-size: clamp(14px, 2vw, 21px);
    margin-bottom: 20px; overflow-wrap: anywhere; }
.product-price { color: #0757c3; font-weight: 900;
    font-size: clamp(42px, 8vw, 77px); line-height: 1.1;
    overflow-wrap: anywhere; margin-top: 8px; }
@media (orientation: landscape) and (max-height: 650px) {
    .block-container { padding-top: .3rem; padding-bottom: .5rem; }
    .main-header { padding: 9px 12px; margin-bottom: 6px; border-radius: 12px; }
    .main-header h1 { font-size: clamp(19px, 3vw, 28px); }
    .main-header p { font-size: 12px; margin-top: 2px; }
    .scan-title { font-size: clamp(18px, 2.7vw, 26px); margin: 5px 0; }
    div[data-testid="stTextInput"] input { min-height: 46px; font-size: 22px !important; }
    .product-card { padding: 12px 15px; border-radius: 13px; }
    .product-name { font-size: clamp(20px, 3.7vw, 34px); margin: 6px 0; }
    .product-code { margin-bottom: 7px; }
    .product-price { font-size: clamp(38px, 7vw, 66px); margin-top: 3px; }
}
@media (max-width: 600px) {
    .block-container { padding-left: 10px; padding-right: 10px; }
    .product-card { padding: 22px 12px; }
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_data(ttl=90, show_spinner=False)
def catalog():
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise ValueError("Falta configurar SUPABASE_URL o SUPABASE_ANON_KEY en Secrets.")

    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    }
    rows = []
    page_size = 500
    offset = 0
    while True:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/products",
            params={
                "select": "barcode,name,price",
                "order": "barcode.asc",
                "limit": page_size,
                "offset": offset,
            },
