import hmac
import html
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from shared import parse_excel, publish, secret

st.set_page_config(page_title="Administración de precios", page_icon="🔒", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""<style>
.stApp{background:#f5f7fc}.block-container{max-width:1300px;padding:22px 22px 50px}h1,h2,h3{color:#102b50;overflow-wrap:anywhere}
div[data-testid="stMetric"]{background:white;border:1px solid #dce5f2;border-radius:15px;padding:16px;min-width:0}div[data-testid="stMetricValue"]{font-size:clamp(18px,2.4vw,30px);overflow-wrap:anywhere}
.stButton button,.stDownloadButton button{min-height:45px;border-radius:11px}div[data-testid="stDataFrame"]{max-width:100%}
.inventory-card{background:white;border:1px solid #dce5f2;border-radius:14px;padding:14px 16px;margin:9px 0;box-shadow:0 3px 12px #14325a0a}
.inventory-name{font-weight:800;font-size:16px;color:#102b50;overflow-wrap:anywhere}.inventory-code{color:#64748b;font-size:13px;margin:6px 0;overflow-wrap:anywhere}.inventory-price{font-weight:850;font-size:23px;color:#0757c3}
@media(max-width:768px){.block-container{padding:13px 12px 35px}h1{font-size:25px!important}h2,h3{font-size:20px!important}div[data-testid="stMetric"]{padding:11px}div[data-testid="stMetricLabel"]{font-size:12px}.stButton button,.stDownloadButton button{width:100%;min-height:48px}div[data-testid="stTextInput"] input{min-height:48px;font-size:16px}}
@media(max-width:480px){.block-container{padding-left:10px;padding-right:10px}.inventory-price{font-size:21px}}
</style>""", unsafe_allow_html=True)

st.title("🔒 Administración de precios")
st.caption("Inventario, publicación e historial de cambios")

password_secret = secret("ADMIN_PASSWORD")
if not password_secret:
    st.error("ADMIN_PASSWORD no está configurada en Streamlit Secrets.")
    st.stop()

if not st.session_state.get("admin_authenticated", False):
    with st.form("admin_login"):
        password = st.text_input("Contraseña de administrador", type="password")
        submitted = st.form_submit_button("Ingresar", use_container_width=True)
    if submitted:
        if hmac.compare_digest(password, password_secret):
            st.session_state.admin_authenticated = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta")
    st.stop()

st.success("Acceso administrativo")
if st.button("Cerrar sesión"):
    st.session_state.admin_authenticated = False
    st.rerun()

URL = str(secret("SUPABASE_URL") or "").strip().rstrip("/")
SERVICE_KEY = str(secret("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
if not URL or not SERVICE_KEY:
    st.error("Configura SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY en Secrets.")
    st.stop()

TZ = ZoneInfo("America/Santo_Domingo")

def headers(prefer=None):
    h = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    return h

def get_all(table, select, order):
    result = []
    offset = 0
    while True:
        response = requests.get(f"{URL}/rest/v1/{table}", headers=headers(), params={"select":select,"order":order,"limit":500,"offset":offset}, timeout=30)
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError("Respuesta inesperada de Supabase")
        result.extend(batch)
        if len(batch) < 500:
            return result
        offset += 500

def post(table, data, prefer="return=representation"):
    response = requests.post(f"{URL}/rest/v1/{table}", headers=headers(prefer), json=data, timeout=35)
    response.raise_for_status()
    return response.json() if prefer != "return=minimal" else None

def fmt_date(value):
    if value is None or pd.isna(value) or str(value).strip() == "":
        return "Sin registros"
    date = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(date):
        return "Sin registros"
    return date.tz_convert(TZ).strftime("%d/%m/%Y %I:%M %p")

def decimal_price(value):
    try:
        number = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Precio inválido en el Excel")
    if not number.is_finite() or number < 0:
        raise ValueError("Precio inválido en el Excel")
    return number

def normalize_incoming(frame):
    required = {"barcode", "name", "price"}
    if not required.issubset(frame.columns):
        raise ValueError("El lector de Excel debe devolver barcode, name y price")
    df = frame[["barcode", "name", "price"]].copy()
    df["barcode"] = df["barcode"].astype(str).str.strip()
    df["name"] = df["name"].astype(str).str.strip()
    if df.empty or (df["barcode"] == "").any() or (df["name"] == "").any():
        raise ValueError("El archivo no contiene productos válidos")
    if df["barcode"].duplicated().any():
        raise ValueError("Hay códigos de barras duplicados en el Excel")
    df["price"] = df["price"].apply(decimal_price)
    return df

def compare(incoming, existing):
    current = {str(row["barcode"]).strip(): row for row in existing}
    details = []
    for row in incoming.to_dict("records"):
        code = row["barcode"]
        old = current.get(code)
        old_price = decimal_price(old["price"]) if old is not None else None
        old_name = str(old["name"]).strip() if old is not None else None
        kind = "NEW" if old is None else ("MODIFIED" if old_price != row["price"] or old_name != row["name"] else "UNCHANGED")
        details.append({"barcode":code,"product_name":row["name"],"change_type":kind,"old_price":float(old_price) if old_price is not None else None,"new_price":float(row["price"]),"old_name":old_name,"new_name":row["name"]})
    return details

def counts(details):
    return {"total_products":len(details),"new_products":sum(x["change_type"] == "NEW" for x in details),"modified_products":sum(x["change_type"] == "MODIFIED" for x in details),"unchanged_products":sum(x["change_type"] == "UNCHANGED" for x in details)}

st.divider()
st.subheader("📊 Resumen del inventario")
if st.button("🔄 Actualizar listado", type="primary", use_container_width=True):
    st.rerun()

try:
    products = get_all("products", "barcode,name,price,updated_at", "barcode.asc")
    updates = get_all("inventory_updates", "id,created_at,total_products,new_products,modified_products,unchanged_products", "id.desc")
except (requests.RequestException, ValueError):
    st.error("No se pudo consultar Supabase. Comprueba la conexión y los permisos.")
    st.stop()

last_publication = updates[0]["created_at"] if updates else None
last_product = max((p["updated_at"] for p in products if p.get("updated_at")), default=None)
a,b,c = st.columns(3)
a.metric("Productos publicados", f"{len(products):,}")
b.metric("Última publicación registrada", fmt_date(last_publication))
c.metric("Última fecha en productos", fmt_date(last_product))
st.caption("La fecha en productos depende del campo updated_at; el historial comienza con las publicaciones hechas desde esta nueva página.")

st.divider()
st.subheader("📦 Productos cargados")
search = st.text_input("Buscar producto", placeholder="Nombre o código de barras")
filtered = [p for p in products if search.casefold().strip() in (str(p.get("name", "")) + " " + str(p.get("barcode", ""))).casefold()]
st.write(f"Mostrando **{len(filtered):,}** de **{len(products):,}** productos")

view = st.radio("Presentación", ["Tarjetas (ideal para móvil)", "Tabla completa"], horizontal=True)
if view.startswith("Tarjetas"):
    page_size = 20
    total_pages = max(1, (len(filtered) + page_size - 1) // page_size)
    page = st.number_input("Página", min_value=1, max_value=total_pages, value=1, step=1)
    for product in filtered[(page-1)*page_size:page*page_size]:
        name = html.escape(str(product.get("name", "")))
        code = html.escape(str(product.get("barcode", "")))
        price = float(product.get("price") or 0)
        st.markdown(f'<div class="inventory-card"><div class="inventory-name">{name}</div><div class="inventory-code">Código: {code}</div><div class="inventory-price">RD$ {price:,.2f}</div></div>', unsafe_allow_html=True)
else:
    display = pd.DataFrame(filtered, columns=["barcode","name","price","updated_at"]).rename(columns={"barcode":"Código","name":"Producto","price":"Precio RD$","updated_at":"Actualizado"})
    if not display.empty:
        display["Precio RD$"] = pd.to_numeric(display["Precio RD$"], errors="coerce")
        display["Actualizado"] = display["Actualizado"].apply(fmt_date)
    st.dataframe(display, use_container_width=True, hide_index=True)

st.download_button("⬇️ Descargar inventario CSV", pd.DataFrame(products, columns=["barcode","name","price","updated_at"]).to_csv(index=False).encode("utf-8-sig"), file_name="inventario_publicado.csv", mime="text/csv", use_container_width=True)

st.divider()
st.subheader("📅 Historial de publicaciones")
if not updates:
    st.info("Todavía no hay publicaciones en el historial. Los productos existentes se conservan.")
else:
    latest = updates[0]
    x,y,z = st.columns(3)
    x.metric("Nuevos", latest["new_products"])
    y.metric("Modificados", latest["modified_products"])
    z.metric("Sin cambios", latest["unchanged_products"])
    with st.expander("Ver publicaciones anteriores", expanded=False):
        st.dataframe(pd.DataFrame([{"Publicación":u["id"],"Fecha":fmt_date(u["created_at"]),"Procesados":u["total_products"],"Nuevos":u["new_products"],"Modificados":u["modified_products"],"Sin cambios":u["unchanged_products"]} for u in updates]), hide_index=True, use_container_width=True)
    chosen = st.selectbox("Detalle de publicación", [u["id"] for u in updates], format_func=lambda ident: f"Publicación #{ident} — {fmt_date(next(u['created_at'] for u in updates if u['id'] == ident))}")
    try:
        detail = get_all("inventory_update_details", "id,update_id,barcode,product_name,change_type,old_price,new_price,old_name,new_name", "id.asc")
        detail = [d for d in detail if d["update_id"] == chosen]
        if detail:
            detail_df = pd.DataFrame(detail).drop(columns=["id","update_id"])
            st.dataframe(detail_df, hide_index=True, use_container_width=True)
        else:
            st.info("Esta publicación no tiene detalles registrados.")
    except requests.RequestException:
        st.warning("No se pudieron consultar los detalles del historial.")

st.divider()
st.subheader("📤 Publicar precios desde Excel")
file = st.file_uploader("Selecciona un archivo Excel", type=["xlsx"])
if file is not None:
    try:
        incoming = normalize_incoming(parse_excel(file))
        changes = compare(incoming, products)
        summary = counts(changes)
        st.success(f"{len(incoming):,} productos válidos en el Excel")
        m1,m2,m3 = st.columns(3)
        m1.metric("Nuevos", summary["new_products"])
        m2.metric("Modificados", summary["modified_products"])
        m3.metric("Sin cambios", summary["unchanged_products"])
        changed = [d for d in changes if d["change_type"] != "UNCHANGED"]
        with st.expander("Ver cambios antes de publicar", expanded=bool(changed)):
            if changed:
                st.dataframe(pd.DataFrame(changed), hide_index=True, use_container_width=True)
            else:
                st.info("No hay cambios respecto al inventario actual.")
        st.warning("Publicar agrega o actualiza por código de barras. No elimina productos que falten en el Excel.")
        confirmed = st.checkbox("Confirmo que quiero publicar estos precios")
        if st.button("Publicar y guardar historial", type="primary", disabled=not confirmed, use_container_width=True):
            try:
                with st.spinner("Publicando productos y guardando historial..."):
                    latest = get_all("products", "barcode,name,price", "barcode.asc")
                    final_changes = compare(incoming, latest)
                    final_summary = counts(final_changes)
                    # Se conserva la función original para mantener el proceso de publicación existente.
                    publish(incoming.assign(price=incoming["price"].astype(float)))
                    record = post("inventory_updates", final_summary)
                    if not isinstance(record, list) or not record:
                        raise ValueError("No se pudo registrar la publicación")
                    update_id = record[0]["id"]
                    for i in range(0, len(final_changes), 200):
                        post("inventory_update_details", [{"update_id":update_id, **d} for d in final_changes[i:i+200]], "return=minimal")
                st.success("Publicación terminada. Los productos y el historial están registrados.")
                st.rerun()
            except (requests.RequestException, ValueError, Exception):
                st.error("La operación no terminó por completo. Algunos precios podrían haberse publicado sin guardar todo el historial. Revisa Supabase antes de reintentar.")
    except (ValueError, KeyError, InvalidOperation, requests.RequestException) as exc:
        st.error(f"No se pudo preparar el Excel: {exc}")
