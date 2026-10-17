import html
from datetime import datetime, timedelta, timezone
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

SUPABASE_SERVICE_ROLE_KEY = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()

def admin_api(method, table, params=None, payload=None):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Falta SUPABASE_SERVICE_ROLE_KEY en Secrets.")
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": "Bearer " + SUPABASE_SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    response = requests.request(
        method, f"{SUPABASE_URL}/rest/v1/{table}",
        params=params, json=payload, headers=headers, timeout=12,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=4, show_spinner=False)
def active_source():
    settings = admin_api("GET", "price_source_settings",
                         params={"id": "eq.1", "select": "source_type"})
    if not settings:
        raise RuntimeError("Falta configurar el origen de datos.")
    mode = settings[0]["source_type"]
    if mode == "local":
        return mode, None
    if mode != "external":
        raise RuntimeError("Origen de datos desconocido.")
    sources = admin_api("GET", "external_price_sources",
                        params={"enabled": "eq.true", "select": "id,name", "limit": "2"})
    if len(sources) != 1:
        raise RuntimeError(
            "La fuente externa requiere exactamente una configuración habilitada. "
            "Configúrala en Fuentes de datos."
        )
    return mode, sources[0]["id"]


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
    ("external_job", None),
    ("external_started", None),
    ("consult_error", None),
    ("source_snapshot", None),
):
    if key not in st.session_state:
        st.session_state[key] = default


def buscar_producto():
    query = st.session_state.search_input.strip()
    if not query:
        return
    st.session_state.current_product = None
    st.session_state.not_found = False
    st.session_state.consult_error = None
    st.session_state.external_job = None
    st.session_state.result_time = None
    try:
        mode, source_id = active_source()
        if mode == "local":
            df = catalog()
            hits = df[df["barcode"].astype(str).str.strip() == query].head(1)
            if hits.empty:
                st.session_state.not_found = True
            else:
                st.session_state.current_product = hits.iloc[0].to_dict()
            st.session_state.result_time = time.monotonic()
        else:
            rows = admin_api("POST", "external_price_jobs", payload={
                "configuration_id": source_id,
                "barcode": query,
                "status": "pending",
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
            })
            if not rows or not rows[0].get("id"):
                raise RuntimeError("No se pudo registrar la consulta externa")
            st.session_state.external_job = rows[0]["id"]
            st.session_state.external_started = time.monotonic()
    except Exception:
        st.session_state.consult_error = (
            "No se pudo consultar la fuente seleccionada. "
            "Revisa la configuración y el conector Windows."
        )
        st.session_state.result_time = time.monotonic()


def check_external_result():
    jid = st.session_state.external_job
    if not jid:
        return
    if time.monotonic() - st.session_state.external_started > 25:
        st.session_state.external_job = None
        st.session_state.consult_error = (
            "La base externa no respondió a tiempo. No se consultó la base local."
        )
        st.session_state.result_time = time.monotonic()
        return
    try:
        rows = admin_api("GET", "external_price_jobs",
                         params={"id": "eq." + jid, "select": "status,result,error_message"})
        if not rows:
            raise RuntimeError("La solicitud externa no existe.")
        job = rows[0]
        if job["status"] == "done":
            result = job.get("result")
            if result:
                st.session_state.current_product = {
                    "barcode": result.get("barcode", st.session_state.search_input),
                    "name": result.get("name", ""),
                    "price": result.get("price", 0),
                }
            else:
                st.session_state.not_found = True
            st.session_state.external_job = None
            st.session_state.result_time = time.monotonic()
        elif job["status"] == "error":
            st.session_state.external_job = None
            st.session_state.consult_error = (
                "No se pudo consultar SQL Server. Revisa el conector y la conexión externa."
            )
            st.session_state.result_time = time.monotonic()
    except (requests.RequestException, RuntimeError):
        st.session_state.external_job = None
        st.session_state.consult_error = "No se pudo obtener la respuesta de la base externa."
        st.session_state.result_time = time.monotonic()


@st.fragment(run_every=0.5)
def verificador():
    # Evitar mostrar resultados de una fuente distinta si el administrador la cambia.
    try:
        mode, source_id = active_source()
        snapshot = (mode, source_id)
        if st.session_state.source_snapshot != snapshot:
            st.session_state.source_snapshot = snapshot
            st.session_state.current_product = None
            st.session_state.not_found = False
            st.session_state.external_job = None
            st.session_state.result_time = None
            st.session_state.consult_error = None
    except Exception:
        st.error("No se pudo leer la fuente activa. Revisa Configuración.")
        return

    if mode == "external":
        check_external_result()
    started = st.session_state.result_time

    if started is not None and time.monotonic() - started >= 10:
        st.session_state.current_product = None
        st.session_state.not_found = False
        st.session_state.consult_error = None
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

    elif st.session_state.consult_error:
        st.error(st.session_state.consult_error)
    elif st.session_state.external_job:
        st.info("Consultando la base de datos externa desde Windows…")
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
except Exception:
    st.error("No se pudo iniciar la consulta de precios. Revisa la conexión y la fuente seleccionada.")
