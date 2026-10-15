import io
import re
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Consulta de precios", page_icon="🏷️", layout="centered")
st.title("🏷️ Consulta de precios")
st.caption("Catálogo de productos · RD$")

def setting(key):
    return str(st.secrets.get(key, "")).strip()

URL = setting("SUPABASE_URL").rstrip("/")
PUBLIC_KEY = setting("SUPABASE_ANON_KEY")
SERVICE_KEY = setting("SUPABASE_SERVICE_ROLE_KEY")
ADMIN_PASSWORD = setting("ADMIN_PASSWORD")

@st.cache_data(ttl=90, show_spinner=False)
def catalog():
    if not URL or not PUBLIC_KEY:
        return pd.DataFrame(columns=["barcode", "name", "price"])
    r = requests.get(f"{URL}/rest/v1/products", params={"select": "barcode,name,price", "limit": "10000"}, headers={"apikey": PUBLIC_KEY, "Authorization": f"Bearer {PUBLIC_KEY}"}, timeout=25)
    r.raise_for_status()
    return pd.DataFrame(r.json(), columns=["barcode", "name", "price"])

def parse_excel(file):
    df = pd.read_excel(io.BytesIO(file.getvalue()), dtype={"Código Barra": str}, engine="openpyxl")
    aliases = {re.sub(r"[^a-z0-9]", "", str(c).lower().translate(str.maketrans("áéíóúüñ", "aeiouun"))): c for c in df.columns}
    def col(*names):
        return next((aliases[n] for n in names if n in aliases), None)
    nc, bc, pc = col("nombre", "descripcion", "producto"), col("codigobarra", "codigobarras", "codigo", "barcode"), col("precioventa", "precio")
    if not all([nc, bc, pc]):
        raise ValueError("El Excel necesita las columnas Nombre, Código Barra y Precio Venta")
    items = []
    for _, r in df.iterrows():
        name = str(r[nc]).strip() if pd.notna(r[nc]) else ""
        barcode = str(r[bc]).strip() if pd.notna(r[bc]) else ""
        if barcode.endswith(".0"): barcode = barcode[:-2]
        try: price = float(str(r[pc]).replace(",", ""))
        except (ValueError, TypeError): continue
        if not name or not barcode or price < 0: continue
        items.append({"barcode": barcode, "name": name, "price": round(price, 2)})
    result = pd.DataFrame(items).drop_duplicates(subset=["barcode"], keep="last") if items else pd.DataFrame(columns=["barcode", "name", "price"])
    if result.empty: raise ValueError("No se encontraron productos válidos")
    return result

try:
    df = catalog()
    st.caption(f"{len(df)} productos disponibles en línea")
    query = st.text_input("Buscar por nombre o código de barras", placeholder="Escribe o escanea un código")
    if query:
        hits = df[df["name"].astype(str).str.contains(query, case=False, regex=False, na=False) | df["barcode"].astype(str).str.contains(query, case=False, regex=False, na=False)].head(60)
        if hits.empty: st.info("Producto no encontrado")
        for _, p in hits.iterrows():
            with st.container(border=True):
                st.markdown(f"**{p['name']}**")
                st.caption(f"Código: {p['barcode']}")
                st.markdown(f"### RD$ {float(p['price']):,.2f}")
except requests.RequestException as e:
    st.error("No se pudo consultar Supabase. Verifica la configuración y la conexión.")

with st.expander("🔒 Administración · Cargar Excel"):
    if not ADMIN_PASSWORD:
        st.warning("Configura ADMIN_PASSWORD en los secretos de Streamlit antes de habilitar la administración.")
    else:
        password = st.text_input("Contraseña de administrador", type="password")
        if password == ADMIN_PASSWORD:
            st.success("Acceso administrativo")
            file = st.file_uploader("Selecciona Excel desde este dispositivo", type=["xlsx"])
            if file:
                try:
                    incoming = parse_excel(file)
                    st.write(f"{len(incoming)} productos válidos")
                    st.dataframe(incoming.head(12), hide_index=True)
                    st.warning("Publicar agrega o actualiza productos por código. No elimina automáticamente los productos ausentes del nuevo Excel.")
                    confirm = st.checkbox("Confirmo que quiero publicar estos precios")
                    if st.button("Publicar en Supabase", type="primary", disabled=not confirm):
                        if not URL or not SERVICE_KEY:
                            st.error("Configura SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY en los secretos de Streamlit.")
                        else:
                            with st.spinner("Publicando..."):
                                for start in range(0, len(incoming), 200):
                                    payload = incoming.iloc[start:start+200].to_dict("records")
                                    response = requests.post(f"{URL}/rest/v1/products?on_conflict=barcode", headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Prefer": "resolution=merge-duplicates,return=minimal", "Content-Type": "application/json"}, json=payload, timeout=35)
                                    response.raise_for_status()
                            catalog.clear()
                            st.success("Precios publicados. Actualiza la consulta para ver los cambios.")
                except (ValueError, requests.RequestException) as e:
                    st.error(f"No se pudo procesar o publicar el Excel: {e}")
        elif password:
            st.error("Contraseña incorrecta")

st.divider()
st.caption("Para consultar sin internet, utiliza la versión Android PWA publicada en GitHub Pages.")
