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

st.markdown('\n<style>\n.stApp { background: #f4f7fc; }\n.block-container {\n    max-width: 1000px;\n    padding: 1.2rem 1rem 2rem;\n}\n#MainMenu, footer { visibility: hidden; }\nheader[data-testid="stHeader"] { background: transparent; }\n.main-header {\n    background: linear-gradient(135deg, #0c2e59, #0759c9);\n    color: white;\n    border-radius: 18px;\n    padding: clamp(14px, 3vh, 30px) 16px;\n    text-align: center;\n    margin-bottom: 14px;\n}\n.main-header h1 {\n    color: white !important;\n    margin: 0;\n    font-size: clamp(22px, 4vw, 39px);\n}\n.main-header p { color: #e2efff; margin: 5px 0 0; font-size: clamp(12px, 2vw, 17px); }\n.scan-title {\n    text-align: center;\n    font-weight: 850;\n    color: #102b50;\n    font-size: clamp(19px, 3.5vw, 32px);\n    margin: 12px 0;\n}\ndiv[data-testid="stTextInput"] input {\n    text-align: center !important;\n    font-size: clamp(19px, 3vw, 29px) !important;\n    min-height: 58px;\n    font-weight: 750;\n    border: 2px solid #cbd9ed;\n    border-radius: 14px;\n}\n.product-card {\n    background: white;\n    border: 1px solid #dce5f2;\n    border-radius: 20px;\n    padding: clamp(18px, 4vw, 40px);\n    margin: 12px auto;\n    text-align: center;\n    box-shadow: 0 6px 22px rgba(20, 50, 90, .08);\n}\n.product-label, .price-label {\n    color: #64748b;\n    font-weight: 800;\n    letter-spacing: 1.3px;\n    font-size: clamp(12px, 1.8vw, 17px);\n}\n.product-name {\n    color: #102b50;\n    font-size: clamp(23px, 4.5vw, 40px);\n    font-weight: 850;\n    overflow-wrap: anywhere;\n    line-height: 1.2;\n    margin: 12px 0;\n}\n.product-code {\n    color: #64748b;\n    font-size: clamp(14px, 2vw, 21px);\n    overflow-wrap: anywhere;\n    margin-bottom: 20px;\n}\n.product-price {\n    color: #0757c3;\n    font-size: clamp(40px, 8vw, 76px);\n    font-weight: 900;\n    line-height: 1.15;\n    overflow-wrap: anywhere;\n    margin-top: 10px;\n}\n@media (orientation: landscape) and (max-height: 650px) {\n    .block-container { padding-top: .4rem; padding-bottom: .5rem; }\n    .main-header { padding: 10px 12px; margin-bottom: 7px; }\n    .main-header h1 { font-size: clamp(18px, 3vw, 28px); }\n    .main-header p { font-size: 12px; margin-top: 2px; }\n    .scan-title { font-size: clamp(17px, 2.5vw, 25px); margin: 6px 0; }\n    div[data-testid="stTextInput"] input { min-height: 46px; font-size: 22px !important; }\n    .product-card { padding: 12px 20px; margin: 3px auto; }\n    .product-name { font-size: clamp(20px, 4vw, 34px); margin: 6px 0; }\n    .product-code { margin-bottom: 8px; }\n    .product-price { font-size: clamp(36px, 7vw, 65px); margin-top: 3px; }\n}\n@media (max-width: 600px) {\n    .block-container { padding-left: 10px; padding-right: 10px; }\n    .product-card { border-radius: 15px; }\n}\n</style>\n', unsafe_allow_html=True)


@st.cache_data(ttl=90, show_spinner=False)
def catalog():
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise ValueError("Falta configurar Supabase en Streamlit Secrets.")

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


for key, default in (
    ("search_input", ""),
    ("current_product", None),
    ("result_time", None),
    ("not_found", False),
):
    if key not in st.session_state:
        st.session_state[key] = default


def buscar_producto():
    code = st.session_state.search_input.strip()
    if not code:
        return

    df = catalog()
    hits = df[df["barcode"].astype(str).str.strip() == code].head(1)

    if hits.empty:
        st.session_state.current_product = None
        st.session_state.not_found = True
    else:
        st.session_state.current_product = hits.iloc[0].to_dict()
        st.session_state.not_found = False

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
