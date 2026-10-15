
import html
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st


# ==========================================
# CONFIGURACION GENERAL
# ==========================================

st.set_page_config(
    page_title="Consulta de precios",
    page_icon="🏷️",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# ==========================================
# CONFIGURACION SUPABASE
# ==========================================

SUPABASE_URL = str(
    st.secrets.get("SUPABASE_URL", "")
).strip().rstrip("/")

SUPABASE_ANON_KEY = str(
    st.secrets.get("SUPABASE_ANON_KEY", "")
).strip()


# ==========================================
# ESTILOS
# ==========================================

st.markdown(
    """
<style>

.stApp {
    background: #f4f7fc;
}

.block-container {
    max-width: 950px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}

/* Ocultar elementos visuales de Streamlit */
#MainMenu {
    visibility: hidden;
}

footer {
    visibility: hidden;
}

header[data-testid="stHeader"] {
    background: transparent;
}

/* ENCABEZADO DE ESPERA */

.main-header {
    background: linear-gradient(
        135deg,
        #0c2e59,
        #0759c9
    );
    border-radius: 25px;
    padding: 32px 20px;
    text-align: center;
    color: white;
    margin-bottom: 25px;
    box-shadow:
        0 8px 25px rgba(10,50,110,0.15);
}

.main-header h1 {
    color: white !important;
    font-size: clamp(28px, 5vw, 43px);
    font-weight: 850;
    margin: 0;
}

.main-header p {
    color: #dceaff;
    font-size: 18px;
    margin-top: 12px;
    margin-bottom: 0;
}

/* MENSAJE DE ESCANEO */

.scan-title {
    text-align: center;
    color: #102b50;
    font-size: clamp(25px, 4vw, 35px);
    font-weight: 850;
    margin: 25px 0 20px;
}

/* CAMPO DE ESCANEO */

div[data-testid="stTextInput"] input {
    text-align: center !important;
    font-size: 30px !important;
    font-weight: 750 !important;
    letter-spacing: 2px;
    min-height: 70px;
    border-radius: 16px;
    border: 2px solid #d5e1f1;
    background: white;
    color: #102b50;
}

/* TARJETA DEL RESULTADO */

.product-card {
    background: white;
    border: 1px solid #dce5f2;
    border-radius: 24px;
    padding: 42px 24px;
    margin: 22px 0;
    text-align: center;
    box-shadow:
        0 7px 25px rgba(20,50,90,0.06);
}

.product-label {
    color: #64748b;
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 2px;
    margin-bottom: 20px;
}

.product-name {
    color: #102b50;
    font-size: clamp(27px, 4.5vw, 40px);
    font-weight: 850;
    line-height: 1.3;
    overflow-wrap: anywhere;
    margin-bottom: 20px;
}

.product-code {
    color: #64748b;
    font-size: clamp(18px, 3vw, 22px);
    overflow-wrap: anywhere;
    margin-bottom: 36px;
}

.price-label {
    color: #64748b;
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 1.5px;
    margin-bottom: 14px;
}

.product-price {
    color: #0757c3;
    font-size: clamp(42px, 8vw, 70px);
    font-weight: 900;
    line-height: 1.15;
    overflow-wrap: anywhere;
}

/* ADAPTACION MOVIL */

@media (max-width: 600px) {

    .block-container {
        padding-left: 13px;
        padding-right: 13px;
    }

    .product-card {
        padding: 34px 14px;
        border-radius: 20px;
    }

    .main-header {
        padding: 25px 14px;
    }
}

</style>
    """,
    unsafe_allow_html=True,
)


# ==========================================
# CONSULTAR CATALOGO DE SUPABASE
# ==========================================

@st.cache_data(ttl=90, show_spinner=False)
def catalog():

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise ValueError(
            "Falta configurar Supabase."
        )

    products = []
    page_size = 500
    offset = 0

    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": (
            f"Bearer {SUPABASE_ANON_KEY}"
        ),
    }

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
            raise ValueError(
                "Respuesta inesperada de Supabase."
            )

        products.extend(batch)

        if len(batch) < page_size:
            break

        offset += page_size

    return pd.DataFrame(
        products,
        columns=[
            "barcode",
            "name",
            "price",
        ],
    )


# ==========================================
# ESTADO DE LA APLICACION
# ==========================================

if "search_input" not in st.session_state:
    st.session_state.search_input = ""

if "current_product" not in st.session_state:
    st.session_state.current_product = None

if "result_time" not in st.session_state:
    st.session_state.result_time = None

if "not_found" not in st.session_state:
    st.session_state.not_found = False


# ==========================================
# BUSQUEDA POR CODIGO EXACTO
# ==========================================

def buscar_producto():

    query = st.session_state.search_input.strip()

    if not query:
        return

    df = catalog()

    hits = df[
        df["barcode"].astype(str).str.strip() == query
    ].head(1)

    if hits.empty:
        st.session_state.current_product = None
        st.session_state.not_found = True
    else:
        st.session_state.current_product = (
            hits.iloc[0].to_dict()
        )
        st.session_state.not_found = False

    st.session_state.result_time = time.monotonic()


# ==========================================
# PANTALLAS CON TEMPORIZADOR
# ==========================================

@st.fragment(run_every=0.5)
def verificador():

    # Reiniciar después de 10 segundos
    if st.session_state.result_time is not None:

        elapsed = (
            time.monotonic()
            - st.session_state.result_time
        )

        if elapsed >= 10:

            st.session_state.current_product = None
            st.session_state.not_found = False
            st.session_state.result_time = None
            st.session_state.search_input = ""

    product = st.session_state.current_product

    # ======================================
    # PANTALLA DE RESULTADO
    # ======================================

    if product is not None:

        nombre = html.escape(str(product["name"]))
        codigo = html.escape(str(product["barcode"]))
        precio = float(product["price"])

        st.markdown(
            f'<div class="product-card">'
            f'<div class="product-label">PRODUCTO</div>'
            f'<div class="product-name">{nombre}</div>'
            f'<div class="product-code">Código: {codigo}</div>'
            f'<div class="price-label">PRECIO DE VENTA</div>'
            f'<div class="product-price">'
            f'RD$ {precio:,.2f}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ======================================
    # PRODUCTO NO ENCONTRADO
    # ======================================

    elif st.session_state.not_found:

        st.warning(
            "Producto no encontrado"
        )

    # ======================================
    # PANTALLA DE ESPERA
    # ======================================

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

            left, center, right = st.columns(
                [1.6, 1, 1.6]
            )

            with center:
                st.image(
                    str(barcode_image),
                    use_container_width=True,
                )

        st.markdown(
            '<div class="scan-title">'
            'ESCANEA TU CÓDIGO AQUÍ'
            '</div>',
            unsafe_allow_html=True,
        )

        st.text_input(
            "Código de barras",
            placeholder="",
            key="search_input",
            on_change=buscar_producto,
            label_visibility="collapsed",
        )


# ==========================================
# INICIAR VERIFICADOR
# ==========================================

try:
    verificador()

except (requests.RequestException, ValueError):

    st.error(
        "No se pudo consultar Supabase. "
        "Verifica la conexión."
    )
