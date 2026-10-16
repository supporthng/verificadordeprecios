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
.block-container { max-width: 980px; padding: 1.25rem 1rem 2rem; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.main-header {
    background: linear-gradient(135deg, #0c2e59, #0759c9);
    border-radius: 20px; padding: 24px 18px; text-align: center;
    color: white; margin-bottom: 18px;
}
.main-header h1 { color: white !important; font-size: clamp(23px, 4vw, 38px); font-weight: 850; margin: 0; }
.main-header p { color: #dceaff; font-size: clamp(13px, 2vw, 17px); margin: 8px 0 0; }
.scan-title { text-align: center; color: #102b50; font-size: clamp(19px, 3.5vw, 30px); font-weight: 850; margin: 18px 0 12px; }
div[data-testid="stTextInput"] input {
    text-align: center !important; font-size: clamp(20px, 4vw, 30px) !important;
    font-weight: 750 !important; min-height: 62px; border-radius: 14px;
    border: 2px solid #d5e1f1; background: white; color: #102b50;
}
.product-card {
    background: white; border: 1px solid #dce5f2; border-radius: 22px;
    padding: clamp(20px, 4vw, 38px); margin: 10px 0; text-align: center;
    box-shadow: 0 7px 25px rgba(20,50,90,0.06);
}
.product-label, .price-label { color: #64748b; font-size: clamp(12px, 1.6vw, 16px); font-weight: 800; letter-spacing: 1px; }
.product-name { color: #102b50; font-size: clamp(23px, 4vw, 40px); font-weight: 850; line-height: 1.18; overflow-wrap: anywhere; margin: 12px 0; }
.product-code { color: #64748b; font-size: clamp(13px, 2vw, 19px); overflow-wrap: anywhere; margin-bottom: 22px; }
.product-price { color: #0757c3; font-size: clamp(38px, 7vw, 72px); font-weight: 900; line-height: 1.08; overflow-wrap: anywhere; margin-top: 8px; }
@media (max-width: 600px) {
    .block-container { padding: 10px 12px 18px; }
    .main-header { padding: 19px 12px; border-radius: 15px; }
    .product-card { padding: 22px 13px; border-radius: 16px; }
}
@media (orientation: landscape) and (max-height: 650px) {
    .block-container { padding-top: 6px; padding-bottom: 8px; }
    .main-header { padding: 10px 12px; margin-bottom: 6px; border-radius: 12px; }
    .main-header h1 { font-size: clamp(18px, 3vw, 26px); }
    .main-header p { font-size: 12px; margin-top: 3px; }
    .scan-title { font-size: clamp(17px, 2.8vw, 24px); margin: 6px 0; }
    div[data-testid="stTextInput"] input { min-height: 48px; font-size: 21px !important; }
    .product-card { padding: 14px 18px; margin: 4px 0; }
    .product-name { font-size: clamp(20px, 3.5vw, 35px); margin: 6px 0; }
    .product-code { margin-bottom: 9px; }
    .product-price { font-size: clamp(38px, 7vw, 66px); }
}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=90, show_spinner=False)
def catalog():
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise ValueError("Falta configurar Supabase.")
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    }
    rows = []
    offset = 0
    page_size = 500
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
            raise ValueError("Respuesta inesperada de Supabase.")
        rows.extend(batch)
        if len(batch) < page_size:
