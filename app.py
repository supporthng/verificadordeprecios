import streamlit as st
from shared import catalog

st.set_page_config(page_title='Consulta de precios', page_icon='🏷️', layout='centered', initial_sidebar_state='collapsed')
st.title('🏷️ Consulta de precios')
st.caption('Catálogo de productos · RD$')
try:
    df = catalog()
except Exception:
    st.error('No se pudo consultar el catálogo. Verifica la conexión y la configuración de Supabase.')
    st.stop()

st.caption(f'{len(df):,} productos disponibles en línea')
query = st.text_input('Buscar por nombre o código de barras', placeholder='Escribe o escanea un código')
if query.strip():
    term = query.strip()
    matches = df[
        df['name'].astype(str).str.contains(term, case=False, regex=False, na=False)
        | df['barcode'].astype(str).str.contains(term, case=False, regex=False, na=False)
    ].head(60)
    if matches.empty:
        st.info('Producto no encontrado')
    for _, product in matches.iterrows():
        with st.container(border=True):
            st.markdown(f"**{product['name']}**")
            st.caption(f"Código: {product['barcode']}")
            st.markdown(f"### RD$ {float(product['price']):,.2f}")
