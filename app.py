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
            headers=headers,
            timeout=25,
        )
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError("Supabase devolvió un formato inesperado.")
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
    code = str(st.session_state.search_input).strip()
    if not code:
        return
    df = catalog()
    found = df.loc[df["barcode"].astype(str).str.strip() == code].head(1)
    st.session_state.current_product = None if found.empty else found.iloc[0].to_dict()
    st.session_state.not_found = found.empty
    st.session_state.result_time = time.monotonic()


def mostrar_espera():
    st.markdown(
        '<div class="main-header"><h1>🏷️ CONSULTA DE PRECIOS</h1>'
        '<p>Consulta rápida de productos y precios</p></div>',
        unsafe_allow_html=True,
    )
    image_path = Path("assets/barcode.png")
    if image_path.is_file():
        left, middle, right = st.columns([2, 1, 2])
        with middle:
            st.image(str(image_path), use_container_width=True)
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


def mostrar_resultado(product):
    name = html.escape(str(product["name"]))
    code = html.escape(str(product["barcode"]))
    price = float(product["price"])
    st.markdown(
        '<div class="product-card">'
        '<div class="product-label">PRODUCTO</div>'
        f'<div class="product-name">{name}</div>'
        f'<div class="product-code">Código: {code}</div>'
        '<div class="price-label">PRECIO DE VENTA</div>'
        f'<div class="product-price">RD$ {price:,.2f}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


# Este encabezado se dibuja fuera del fragmento para que siempre
# exista contenido visible, incluso si falla la sección dinámica.
st.markdown(
    '<div style="text-align:center;color:#64748b;font-size:12px;'
    'margin-bottom:5px">VERIFICADOR DE PRECIOS</div>',
    unsafe_allow_html=True,
)


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
        mostrar_resultado(product)
    elif st.session_state.not_found:
        st.warning("Producto no encontrado")
    else:
        mostrar_espera()


try:
    verificador()
except Exception as exc:
    st.error("No se pudo iniciar la consulta de precios.")
    st.exception(exc)
