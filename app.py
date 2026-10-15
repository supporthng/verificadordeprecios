import base64
import html
from pathlib import Path

import streamlit as st
from shared import catalog

st.set_page_config(
    page_title='Consulta de precios',
    page_icon='🏷️',
    layout='centered',
    initial_sidebar_state='collapsed',
)

st.markdown('''
<style>
:root { color-scheme: light; }
.stApp { background: linear-gradient(160deg, #f0f6ff 0%, #f7f9fd 42%, #ffffff 100%); }
.block-container { max-width: 820px; padding-top: 2.1rem; padding-bottom: 4rem; }
#MainMenu, footer { visibility: hidden; }
.hero { background: linear-gradient(120deg, #102a57, #1852a3); border-radius: 24px;
  padding: 27px 30px; color: white; box-shadow: 0 16px 35px rgba(20,62,126,.15); }
.hero-top { display:flex; align-items:center; justify-content:space-between; gap:20px; }
.hero h1 { color:white !important; font-size: clamp(1.6rem,4vw,2.3rem); margin: 4px 0 9px;
  font-weight: 800; letter-spacing: -.04em; line-height:1.1; }
.hero p { color:#dbeafe; margin:0; font-size:.95rem; }
.hero-kicker { color:#bfdbfe; font-size:.75rem; font-weight:700; letter-spacing:.12em; }
.hero img { width:140px; max-width:34vw; border-radius:13px; background:white; padding:8px; }
.status { display:inline-flex; align-items:center; gap:8px; margin:22px 0 16px; padding:9px 14px;
  background:#eaf8f1; border:1px solid #b9ead3; color:#166b49; border-radius:999px;
  font-weight:650; font-size:.86rem; }
.status-dot { width:8px; height:8px; background:#20b978; border-radius:50%; }
.section-heading { font-size:1.06rem; font-weight:750; color:#182d4e; margin:10px 0 5px; }
.section-hint { font-size:.88rem; color:#64748b; margin:0 0 14px; }
div[data-testid="stTextInput"] input { border-radius:13px; min-height:53px; background:white;
  border:1px solid #cddbf0; font-size:1.03rem; }
div[data-testid="stTextInput"] input:focus { border-color:#2563eb; box-shadow:0 0 0 2px #dbeafe; }
.product-card { background:#fff; border:1px solid #e0e8f4; border-radius:18px;
  padding:22px 24px; margin:12px 0; box-shadow:0 7px 20px rgba(30,56,96,.045); }
.product-label { color:#6b7f9d; font-size:.69rem; letter-spacing:.12em; font-weight:800; }
.product-name { color:#162b4c; font-size:1.11rem; font-weight:800; margin:8px 0; overflow-wrap:anywhere; }
.product-code { color:#718096; font-size:.83rem; margin:0 0 17px; }
.product-price { color:#0b58bd; font-size:clamp(1.55rem,4vw,2rem); font-weight:850; letter-spacing:-.04em; }
.product-price span { font-size:.8rem; font-weight:700; letter-spacing:0; color:#5b7292; margin-right:6px; }
.empty { text-align:center; padding:26px 15px; border:1px dashed #c9d9ee; border-radius:17px;
  background:#fff; color:#60718d; margin-top:15px; }
.app-note { color:#8b98aa; text-align:center; font-size:.78rem; margin-top:28px; }
@media(max-width: 600px) { .block-container { padding:1rem 1rem 3rem; }
  .hero { padding:22px 18px; border-radius:18px; } .hero img { width:110px; }
  .product-card { padding:19px; } }
</style>
''', unsafe_allow_html=True)

image_path = Path(__file__).parent / 'assets' / 'barcode.png'
barcode_src = ''
if image_path.exists():
    barcode_src = 'data:image/png;base64,' + base64.b64encode(image_path.read_bytes()).decode('ascii')

st.markdown(f'''
<div class="hero">
  <div class="hero-top">
    <div>
      <div class="hero-kicker">CONSULTA RÁPIDA</div>
      <h1>Consulta de precios</h1>
      <p>Encuentra tus productos y descubre su precio al instante.</p>
    </div>
    <img src="{barcode_src}" alt="Ilustración decorativa de un código de barras" />
  </div>
</div>
''', unsafe_allow_html=True)

try:
    df = catalog()
except Exception:
    st.error('No se pudo consultar el catálogo. Comprueba la conexión a Supabase.')
    st.stop()

st.markdown(f'<div class="status"><span class="status-dot"></span>{len(df):,} productos disponibles en línea</div>', unsafe_allow_html=True)
st.markdown('<div class="section-heading">Busca un producto</div><div class="section-hint">Introduce su nombre o escanea el código de barras.</div>', unsafe_allow_html=True)
query = st.text_input('Nombre o código de barras', placeholder='🔎  Escribe o escanea aquí...', label_visibility='collapsed')

if query.strip():
    term = query.strip()
    matches = df[
        df['name'].astype(str).str.contains(term, case=False, regex=False, na=False)
        | df['barcode'].astype(str).str.contains(term, case=False, regex=False, na=False)
    ].head(60)
    if matches.empty:
        st.markdown('<div class="empty">No encontramos productos con esa búsqueda.<br>Verifica el nombre o el código e inténtalo de nuevo.</div>', unsafe_allow_html=True)
    else:
        st.caption(f'{len(matches)} resultado(s)' + (' · se muestran los primeros 60' if len(matches) == 60 else ''))
        for _, product in matches.iterrows():
            name = html.escape(str(product['name']))
            barcode = html.escape(str(product['barcode']))
            try:
                price = f"{float(product['price']):,.2f}"
            except (ValueError, TypeError):
                price = 'No disponible'
            st.markdown(f'''<div class="product-card">
                <div class="product-label">PRODUCTO</div>
                <div class="product-name">{name}</div>
                <div class="product-code">Código: {barcode}</div>
                <div class="product-price"><span>RD$</span>{price}</div>
            </div>''', unsafe_allow_html=True)
else:
    st.markdown('<div class="empty">▥ &nbsp; Listo para consultar precios.<br>Escribe o escanea un código para comenzar.</div>', unsafe_allow_html=True)

st.markdown('<div class="app-note">Precios consultados en el catálogo en línea.</div>', unsafe_allow_html=True)
