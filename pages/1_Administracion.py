
import hmac
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from shared import (
    catalog,
    parse_excel,
    publish,
    secret,
    supabase_url,
)


# ==========================================
# CONFIGURACION
# ==========================================

st.set_page_config(
    page_title="Administración de precios",
    page_icon="🔒",
    layout="wide",
)

RD_TZ = ZoneInfo("America/Santo_Domingo")

st.markdown("""
<style>
.stApp {
    background: #f5f7fc;
}
.block-container {
    max-width: 1350px;
    padding-top: 2rem;
}
h1, h2, h3 {
    color: #102b50;
}
div[data-testid="stMetric"] {
    background: white;
    border: 1px solid #dce5f2;
    border-radius: 16px;
    padding: 18px;
}
</style>
""", unsafe_allow_html=True)


# ==========================================
# AUTENTICACION
# ==========================================

st.title("🔒 Administración de precios")
st.caption("Inventario, publicación e historial de cambios")

admin_password = secret("ADMIN_PASSWORD")

if not admin_password:
    st.error("ADMIN_PASSWORD no está configurada.")
    st.stop()

if not st.session_state.get("admin_authenticated", False):

    with st.form("admin_login"):
        password = st.text_input(
            "Contraseña de administrador",
            type="password",
        )
        submit = st.form_submit_button("Ingresar")

    if submit:
        if hmac.compare_digest(
            password.encode(),
            admin_password.encode(),
        ):
            st.session_state.admin_authenticated = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta")

    st.stop()


top_left, top_right = st.columns([5, 1])

with top_left:
    st.success("Acceso administrativo")

with top_right:
    if st.button("Cerrar sesión"):
        st.session_state.admin_authenticated = False
        st.rerun()


# ==========================================
# CONEXION ADMINISTRATIVA
# ==========================================

def admin_headers(prefer=None):
    key = secret("SUPABASE_SERVICE_ROLE_KEY")

    if not key or not supabase_url():
        raise ValueError(
            "Falta la configuración administrativa "
            "de Supabase."
        )

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    if prefer:
        headers["Prefer"] = prefer

    return headers


def api_get(table, params=None):
    response = requests.get(
        f"{supabase_url()}/rest/v1/{table}",
        headers=admin_headers(),
        params=params,
        timeout=35,
    )
    response.raise_for_status()
    return response.json()


def api_post(table, payload, prefer="return=representation"):
    response = requests.post(
        f"{supabase_url()}/rest/v1/{table}",
        headers=admin_headers(prefer),
        json=payload,
        timeout=35,
    )
    response.raise_for_status()

    if prefer == "return=minimal":
        return None

    return response.json()


def read_all(table, columns, order="id.asc"):
    rows = []
    offset = 0
    page_size = 500

    while True:
        batch = api_get(
            table,
            {
                "select": columns,
                "order": order,
                "limit": page_size,
                "offset": offset,
            },
        )

        rows.extend(batch)

        if len(batch) < page_size:
            break

        offset += page_size

    return pd.DataFrame(rows)


def format_date(value):
    if not value:
        return "Sin registros"

    date = pd.to_datetime(value, utc=True)

    return date.tz_convert(RD_TZ).strftime(
        "%d/%m/%Y %I:%M %p"
    )


def money(value):
    return f"RD$ {float(value):,.2f}"


# ==========================================
# CARGAR INVENTARIO E HISTORIAL
# ==========================================

def load_dashboard():
    products = read_all(
        "products",
        "barcode,name,price,updated_at",
        "barcode.asc",
    )

    updates = read_all(
        "inventory_updates",
        "id,created_at,total_products,"
        "new_products,modified_products,"
        "unchanged_products",
        "id.desc",
    )

    return products, updates


if "dashboard_refresh" not in st.session_state:
    st.session_state.dashboard_refresh = 0


def refresh_dashboard():
    st.session_state.dashboard_refresh += 1
    catalog.clear()


st.divider()

st.subheader("📊 Panel de inventario")

if st.button(
    "🔄 Actualizar listado",
    type="primary",
):
    refresh_dashboard()
    st.rerun()


try:
    products, updates = load_dashboard()

except (requests.RequestException, ValueError):
    st.error(
        "No se pudo cargar el inventario o historial. "
        "Revisa la conexión y los permisos de Supabase."
    )
    st.stop()


# ==========================================
# INDICADORES
# ==========================================

last_product_update = None

if (
    not products.empty
    and "updated_at" in products.columns
):
    dates = pd.to_datetime(
        products["updated_at"],
        utc=True,
        errors="coerce",
    )

    if dates.notna().any():
        last_product_update = dates.max()


last_publication = (
    updates.iloc[0].to_dict()
    if not updates.empty
    else None
)

c1, c2, c3 = st.columns(3)

with c1:
    st.metric(
        "Productos cargados",
        f"{len(products):,}",
    )

with c2:
    st.metric(
        "Última modificación registrada",
        format_date(last_product_update),
    )

with c3:
    st.metric(
        "Última publicación con historial",
        format_date(
            last_publication["created_at"]
            if last_publication
            else None
        ),
    )

st.caption(
    "La fecha de modificación proviene de products.updated_at. "
    "El historial de publicaciones comienza con esta versión "
    "de Administración."
)


# ==========================================
# LISTADO DE PRODUCTOS
# ==========================================

st.divider()
st.subheader("📦 Productos publicados")

filter_text = st.text_input(
    "Buscar en el inventario",
    placeholder="Nombre o código de barras",
)

visible = products.copy()

if filter_text.strip() and not visible.empty:
    term = filter_text.strip()

    visible = visible[
        visible["name"].astype(str).str.contains(
            term,
            case=False,
            regex=False,
            na=False,
        )
        |
        visible["barcode"].astype(str).str.contains(
            term,
            case=False,
            regex=False,
            na=False,
        )
    ]

st.write(f"Mostrando {len(visible):,} productos")

if not visible.empty:
    display = visible.rename(
        columns={
            "barcode": "Código de barras",
            "name": "Producto",
            "price": "Precio RD$",
            "updated_at": "Actualizado",
        }
    ).copy()

    display["Precio RD$"] = pd.to_numeric(
        display["Precio RD$"],
        errors="coerce",
    )

    display["Actualizado"] = display[
        "Actualizado"
    ].apply(format_date)

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Precio RD$": st.column_config.NumberColumn(
                "Precio RD$",
                format="%.2f",
            )
        },
    )

    st.download_button(
        "⬇️ Descargar inventario CSV",
        data=visible.to_csv(index=False).encode(
            "utf-8-sig"
        ),
        file_name="inventario_publicado.csv",
        mime="text/csv",
    )


# ==========================================
# HISTORIAL DE PUBLICACIONES
# ==========================================

st.divider()
st.subheader("📅 Historial de actualizaciones")

if updates.empty:
    st.info(
        "Todavía no hay publicaciones registradas "
        "en el historial. La próxima publicación "
        "desde este panel aparecerá aquí."
    )

else:
    history = updates.copy()

    history["created_at"] = history[
        "created_at"
    ].apply(format_date)

    history = history.rename(
        columns={
            "id": "Publicación",
            "created_at": "Fecha",
            "total_products": "Procesados",
            "new_products": "Nuevos",
            "modified_products": "Modificados",
            "unchanged_products": "Sin cambios",
        }
    )

    st.dataframe(
        history,
        use_container_width=True,
        hide_index=True,
    )

    options = updates["id"].tolist()

    selected_id = st.selectbox(
        "Selecciona una publicación para ver el detalle",
        options,
        format_func=lambda value: (
            f"Publicación #{value}"
        ),
    )

    try:
        detail_rows = api_get(
            "inventory_update_details",
            {
                "select": (
                    "barcode,product_name,change_type,"
                    "old_price,new_price,old_name,new_name"
                ),
                "update_id": f"eq.{selected_id}",
                "order": "id.asc",
            },
        )

        if detail_rows:
            details = pd.DataFrame(detail_rows)

            details = details.rename(
                columns={
                    "barcode": "Código",
                    "product_name": "Producto",
                    "change_type": "Tipo",
                    "old_price": "Precio anterior",
                    "new_price": "Precio nuevo",
                    "old_name": "Nombre anterior",
                    "new_name": "Nombre nuevo",
                }
            )

            st.dataframe(
                details,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info(
                "No hay detalles guardados "
                "para esta publicación."
            )

    except requests.RequestException:
        st.warning(
            "No fue posible cargar los detalles."
        )


# ==========================================
# COMPARAR EXCEL CON INVENTARIO
# ==========================================

def compare_inventory(incoming, existing):

    current = {}

    for _, row in existing.iterrows():
        current[str(row["barcode"]).strip()] = {
            "name": str(row["name"]).strip(),
            "price": Decimal(str(row["price"])),
        }

    details = []

    for _, row in incoming.iterrows():

        barcode = str(row["barcode"]).strip()
        new_name = str(row["name"]).strip()
        new_price = Decimal(str(row["price"]))

        old = current.get(barcode)

        if old is None:
            change_type = "NEW"
            old_price = None
            old_name = None

        else:
            old_price = old["price"]
            old_name = old["name"]

            if (
                old_price != new_price
                or old_name != new_name
            ):
                change_type = "MODIFIED"
            else:
                change_type = "UNCHANGED"

        details.append({
            "barcode": barcode,
            "product_name": new_name,
            "change_type": change_type,
            "old_price": (
                float(old_price)
                if old_price is not None
                else None
            ),
            "new_price": float(new_price),
            "old_name": old_name,
            "new_name": new_name,
        })

    return details


# ==========================================
# CARGAR Y PUBLICAR EXCEL
# ==========================================

st.divider()
st.subheader("📤 Actualizar precios desde Excel")

file = st.file_uploader(
    "Selecciona Excel desde este dispositivo",
    type=["xlsx"],
)

if file is not None:

    try:
        incoming = parse_excel(file)

        st.success(
            f"{len(incoming):,} productos válidos "
            "en el archivo Excel."
        )

        st.dataframe(
            incoming.head(15),
            use_container_width=True,
            hide_index=True,
        )

        # Consultar inventario nuevamente para
        # comparar contra el estado actual.
        current_products = read_all(
            "products",
            "barcode,name,price",
            "barcode.asc",
        )

        comparison = compare_inventory(
            incoming,
            current_products,
        )

        new_count = sum(
            x["change_type"] == "NEW"
            for x in comparison
        )

        modified_count = sum(
            x["change_type"] == "MODIFIED"
            for x in comparison
        )

        unchanged_count = sum(
            x["change_type"] == "UNCHANGED"
            for x in comparison
        )

        st.markdown("### Vista previa de cambios")

        a, b, c = st.columns(3)

        a.metric("Nuevos", new_count)
        b.metric("Modificados", modified_count)
        c.metric("Sin cambios", unchanged_count)

        changed = [
            item for item in comparison
            if item["change_type"] != "UNCHANGED"
        ]

        if changed:
            st.dataframe(
                pd.DataFrame(changed).rename(
                    columns={
                        "barcode": "Código",
                        "product_name": "Producto",
                        "change_type": "Cambio",
                        "old_price": "Precio anterior",
                        "new_price": "Precio nuevo",
                        "old_name": "Nombre anterior",
                        "new_name": "Nombre nuevo",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info(
                "Todos los productos del Excel "
                "coinciden con el inventario publicado."
            )

        st.warning(
            "La publicación agrega o actualiza "
            "productos por código de barras. "
            "No elimina los productos ausentes "
            "del Excel."
        )

        confirmed = st.checkbox(
            "Confirmo que quiero publicar "
            "estos precios",
        )

        if st.button(
            "Publicar y registrar actualización",
            type="primary",
            disabled=not confirmed,
        ):

            try:
                with st.spinner(
                    "Publicando inventario..."
                ):

                    # Comparar nuevamente justo antes
                    # de publicar.
                    latest_products = read_all(
                        "products",
                        "barcode,name,price",
                        "barcode.asc",
                    )

                    final_details = compare_inventory(
                        incoming,
                        latest_products,
                    )

                    totals = {
                        "total_products": len(final_details),
                        "new_products": sum(
                            x["change_type"] == "NEW"
                            for x in final_details
                        ),
                        "modified_products": sum(
                            x["change_type"] == "MODIFIED"
                            for x in final_details
                        ),
                        "unchanged_products": sum(
                            x["change_type"] == "UNCHANGED"
                            for x in final_details
                        ),
                    }

                    # Publicar primero los precios.
                    publish(incoming)

                    # Registrar la publicación.
                    saved = api_post(
                        "inventory_updates",
                        totals,
                    )

                    if not saved:
                        raise ValueError(
                            "No se creó el registro "
                            "de actualización."
                        )

                    update_id = saved[0]["id"]

                    # Guardar detalle en lotes.
                    for start in range(
                        0,
                        len(final_details),
                        200,
                    ):
                        batch = final_details[
                            start:start + 200
                        ]

                        api_post(
                            "inventory_update_details",
                            [
                                {
                                    "update_id": update_id,
                                    **item,
                                }
                                for item in batch
                            ],
                            prefer="return=minimal",
                        )

                    refresh_dashboard()

                st.success(
                    "Precios publicados e historial "
                    "registrado correctamente."
                )

                st.rerun()

            except (
                requests.RequestException,
                ValueError,
            ):
                st.error(
                    "No se completó toda la operación. "
                    "Es posible que los precios se hayan "
                    "publicado sin terminar el historial. "
                    "Revisa Supabase antes de reintentar."
                )

    except (
        requests.RequestException,
        ValueError,
    ):
        st.error(
            "No se pudo procesar el Excel "
            "o consultar el inventario."
        )

    except Exception:
        st.error(
            "Ocurrió un error inesperado "
            "al preparar la actualización."
        )
