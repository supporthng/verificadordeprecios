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

st.markdown("""
<style>
.stApp { background: #f4f7fc; }
.block-container { max-width: 920px; padding: 1.5rem 1rem 2rem; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.main-header {
    background: linear-gradient(135deg, #0c2e59, #0759c9);
    border-radius: 20px; padding: 24px 16px;
    text-align: center; color: white; margin-bottom: 16px;
}
.main-header h1 { color: white !important; font-size: clamp(22px, 4.5vw, 38px); margin: 0; }
.main-header p { color: #e0ecff; font-size: clamp(12px, 2vw, 17px); margin: 6px 0 0; }
.scan-title { text-align: center; color: #102b50; font-size: clamp(19px, 3vw, 29px); font-weight: 800; margin: 15px 0; }
div[data-testid="stTextInput"] input {
    text-align: center !important; font-size: clamp(19px, 3vw, 29px) !important;
    min-height: 58px; border-radius: 14px; border: 2px solid #d5e1f1;
}
.product-card {
    background: white; border: 1px solid #dce5f2; border-radius: 22px;
    padding: clamp(20px, 4vw, 40px) 18px; text-align: center;
    box-shadow: 0 7px 25px rgba(20,50,90,.06);
}
.product-label, .price-label { color: #64748b; font-weight: 800; letter-spacing: 1px; font-size: 14px; }
.product-name { color: #102b50; font-size: clamp(23px, 4vw, 38px); font-weight: 850; line-height: 1.2; overflow-wrap: anywhere; margin: 12px 0; }
.product-code { color: #64748b; font-size: clamp(13px, 2vw, 19px); overflow-wrap: anywhere; margin-bottom: 20px; }
.product-price { color: #0757c3; font-size: clamp(36px, 7vw, 68px); font-weight: 900; line-height: 1.12; overflow-wrap: anywhere; margin-top: 8px; }
@media (max-width: 700px) {
    .block-container { padding: 0.75rem 0.7rem 1rem; }
    .main-header { padding: 15px 12px; margin-bottom: 8px; border-radius: 14px; }
    .product-card { border-radius: 16px; }
}
@media (orientation: landscape) and (max-height: 650px) {
    .block-container { padding-top: 0.3rem; padding-bottom: 0.3rem; }
    .main-header { padding: 10px; margin-bottom: 5px; }
    .main-header h1 { font-size: clamp(19px, 3.5vw, 30px); }
    .main-header p { margin-top: 2px; }
    .scan-title { margin: 6px 0; font-size: clamp(18px, 3vw, 25px); }
    div[data-testid="stTextInput"] input { min-height: 45px; }
    .product-card { padding: 12px 16px; }
    .product-name { margin: 5px 0; font-size: clamp(20px, 4vw, 34px); }
    .product-code { margin-bottom: 7px; }
    .product-price { margin-top: 3px; font-size: clamp(34px, 7vw, 60px); }
}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=90, show_spinner=False)
def catalog():
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise ValueError("Falta configurar SUPABASE_URL o SUPABASE_ANON_KEY.")

    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    }
    products = []
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
            headers=headers,
            timeout=25,
        )
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError("Supabase devolvió una respuesta inesperada.")
        products.extend(batch)
