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
.block-container {
    max-width: 950px;
    padding: 1rem 1rem 2rem;
}
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.main-header {
    background: linear-gradient(135deg, #0c2e59, #0759c9);
    border-radius: 20px;
    padding: clamp(12px, 3vw, 28px);
    text-align: center;
    color: white;
    margin-bottom: 12px;
}
.main-header h1 {
    color: white !important;
    font-size: clamp(20px, 4vw, 38px);
    margin: 0;
}
.main-header p {
    color: #dceaff;
    font-size: clamp(12px, 2vw, 17px);
    margin: 6px 0 0;
}
.scan-title {
    color: #102b50;
    text-align: center;
    font-weight: 850;
    font-size: clamp(18px, 3.5vw, 32px);
    margin: 10px 0;
}
div[data-testid="stTextInput"] input {
    text-align: center !important;
    font-size: clamp(18px, 3vw, 28px) !important;
    min-height: 56px;
    border-radius: 14px;
    border: 2px solid #d5e1f1;
    background: white;
}
.product-card {
    background: white;
    border: 1px solid #dce5f2;
    border-radius: 20px;
    padding: clamp(16px, 4vw, 36px);
    text-align: center;
    margin: 10px auto;
    box-shadow: 0 7px 25px rgba(20,50,90,.07);
}
.product-label, .price-label {
    color: #64748b;
    font-weight: 800;
    letter-spacing: 1px;
    font-size: clamp(12px, 2vw, 17px);
}
.product-name {
    color: #102b50;
    font-size: clamp(22px, 4.5vw, 40px);
    font-weight: 850;
    overflow-wrap: anywhere;
    line-height: 1.2;
    margin: 12px 0;
}
.product-code {
    color: #64748b;
    font-size: clamp(14px, 2vw, 21px);
    overflow-wrap: anywhere;
    margin-bottom: 22px;
}
.product-price {
    color: #0757c3;
    font-size: clamp(40px, 8vw, 76px);
    font-weight: 900;
    line-height: 1.1;
    overflow-wrap: anywhere;
    margin-top: 8px;
}
@media (max-width: 600px) {
    .block-container { padding: .6rem .6rem 1rem; }
    .main-header { padding: 13px 10px; margin-bottom: 8px; }
    .main-header h1 { font-size: clamp(19px, 5.5vw, 27px); }
    .scan-title { margin: 6px 0; font-size: clamp(17px, 5vw, 24px); }
    div[data-testid="stTextInput"] input { min-height: 48px; }
    .product-card { padding: 18px 12px; }
}
@media (orientation: landscape) and (max-height: 650px) {
    .block-container { padding-top: .25rem; padding-bottom: .4rem; }
    .main-header { padding: 8px 12px; margin-bottom: 5px; }
    .main-header h1 { font-size: clamp(18px, 3vw, 27px); }
    .main-header p { margin-top: 2px; font-size: 12px; }
    .scan-title { margin: 4px 0; font-size: clamp(17px, 3vw, 24px); }
    div[data-testid="stTextInput"] input { min-height: 44px; }
    .product-card { padding: 12px; margin: 4px auto; }
    .product-name { margin: 6px 0; }
    .product-code { margin-bottom: 8px; }
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


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
    query = st.session_state.search_input.strip()
    if not query:
        return

    df = catalog()
    hits = df[df["barcode"].astype(str).str.strip() == query].head(1)

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

    if product is not None:
        name = html.escape(str(product["name"]))
        barcode = html.escape(str(product["barcode"]))
        price = float(product["price"])

        st.markdown(
            '<div class="product-card">'
            '<div class="product-label">PRODUCTO</div>'
            f'<div class="product-name">{name}</div>'
            f'<div class="product-code">Código: {barcode}</div>'
            '<div class="price-label">PRECIO DE VENTA</div>'
            f'<div class="product-price">RD$ {price:,.2f}</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    elif st.session_state.not_found:
        st.warning("Producto no encontrado")

    else:
        st.markdown(
            '<div class="main-header">'
            '<h1>🏷️ CONSULTA DE PRECIOS</h1>'
            '<p>Consulta rápida de productos y precios</p>'
            '</div>',
            unsafe_allow_html=True,
        )

        barcode_image = Path("assets/barcode.png")
        if barcode_image.is_file():
            left, center, right = st.columns([2, 1, 2])
            with center:
                st.image(str(barcode_image), use_container_width=True)

        st.markdown(
            '<div class="scan-title">ESCANEA TU CÓDIGO AQUÍ</div>',
            unsafe_allow_html=True,
        )

        st.text_input(
            "Código de barras",
            key="search_input",
            on_change=buscar_producto,
            label_visibility="collapsed",
        )


try:
    verificador()
except Exception as exc:
    st.error("No se pudo iniciar la consulta de precios.")
    st.exception(exc)
