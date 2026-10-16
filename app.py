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
        left, center, right = st.columns([1, 1, 1])
        with center:
            st.image(str(image_path), width=145)
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
    'margin-bottom:5px">WILPOS · VERIFICADOR DE PRECIOS</div>',
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
