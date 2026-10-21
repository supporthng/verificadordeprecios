"""Catálogo de solo lectura: Supabase, Google y cada servidor externo configurado."""
from datetime import datetime, timedelta, timezone
import math
import requests
import streamlit as st
from auth_usuarios import current_user, allowed

st.title('📋 Consulta de Base de Datos')
st.caption('Consulta cualquier fuente configurada sin cambiar la fuente activa del lector.')
user = current_user()
if not user or not allowed(user, 'consultar_base'):
    st.error('No tienes permiso para acceder a esta sección.')
    st.stop()

URL = str(st.secrets.get('SUPABASE_URL', '')).strip().rstrip('/')
KEY = str(st.secrets.get('SUPABASE_SERVICE_ROLE_KEY', '')).strip()
if not URL or not KEY:
    st.error('Faltan credenciales de Supabase en Secrets.')
    st.stop()
HEADERS = {'apikey': KEY, 'Authorization': 'Bearer ' + KEY,
           'Content-Type': 'application/json', 'Prefer': 'return=representation'}

def api(method, table, params=None, data=None, extra_headers=None):
    response = requests.request(method, URL + '/rest/v1/' + table,
                                params=params, json=data,
                                headers={**HEADERS, **(extra_headers or {})}, timeout=20)
    response.raise_for_status()
    return response

def error_detail(exc):
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        try:
            payload = exc.response.json()
            return f"HTTP {exc.response.status_code}: " + str(payload.get('message') or payload.get('details') or 'Error de Supabase')
        except ValueError:
            return f'HTTP {exc.response.status_code}'
    return type(exc).__name__ + ': ' + str(exc)

try:
    sources = api('GET', 'external_price_sources', {
        'select': 'id,name,engine,database,schema_name,table_name',
        'order': 'name.asc', 'limit': '1000'}).json()
except requests.RequestException as exc:
    st.error('No se pudieron leer las fuentes externas: ' + error_detail(exc))
    st.stop()

choices = {'local': 'Supabase / Inventario activo (Excel)'}
google_cfg = None
try:
    from google_oauth_source import config as google_config, catalog as google_catalog
    google_cfg = google_config()
    if google_cfg and all(google_cfg.get(k) for k in
                          ('refresh_token_encrypted', 'kind', 'file_id',
                           'code_column', 'name_column', 'price_column')):
        choices['google'] = 'Google Drive / Sheets — ' + str(google_cfg.get('kind', 'google')).upper()
except Exception as exc:
    st.warning('No se pudo verificar la configuración Google: ' + str(exc))
for source in sources:
    source_id = str(source['id'])
    choices['external:' + source_id] = (
        f"{source.get('name') or 'Servidor externo'} — "
        f"{source.get('database') or 'BD'} "
        f"({source.get('schema_name') or 'dbo'}.{source.get('table_name') or 'tabla'})"
    )

selected = st.selectbox('Base de datos que deseas consultar', list(choices),
                        format_func=lambda value: choices[value])
search = st.text_input('Buscar por código o descripción', placeholder='Escribe el código o nombre')
page_size = st.selectbox('Productos por página', [25, 50, 100], index=0)
query_key = (selected, search.strip(), page_size)
if st.session_state.get('catalog_query_key') != query_key:
    st.session_state.catalog_query_key = query_key
    st.session_state.catalog_page = 1
    st.session_state.pop('catalog_job', None)
    st.session_state.pop('catalog_result', None)
page = st.session_state.get('catalog_page', 1)

def show_table(data, external=False):
    products = data.get('products') or []
    total = data.get('total')
    st.write(f'**{total:,} productos**' if isinstance(total, int) else '**Listado de productos**')
    if products:
        st.dataframe([{'Código': p.get('barcode'), 'Descripción': p.get('name'),
                       'Precio': p.get('price')} for p in products],
                     hide_index=True, use_container_width=True)
    else:
        st.info('No se encontraron productos.')
    max_page = max(1, math.ceil(total / page_size)) if isinstance(total, int) else None
    left, middle, right = st.columns([1, 2, 1])
    with left:
        if st.button('← Anterior', disabled=page <= 1, key='prev_' + ('ext' if external else 'std')):
            st.session_state.catalog_page = page - 1
            st.rerun(scope='app') if external else st.rerun()
    with middle:
        st.write(f'Página {page}' + (f' de {max_page}' if max_page else ''))
    with right:
        disabled = page >= max_page if max_page else len(products) < page_size
        if st.button('Siguiente →', disabled=disabled, key='next_' + ('ext' if external else 'std')):
            st.session_state.catalog_page = page + 1
            st.rerun(scope='app') if external else st.rerun()

if selected == 'google':
    try:
        cfg = google_cfg
        df = google_catalog(cfg['kind'], cfg['file_id'], cfg.get('sheet_name') or '',
                            cfg['code_column'], cfg['name_column'], cfg['price_column'])
        term = search.strip().casefold()
        if term:
            mask = (df['barcode'].astype(str).str.casefold().str.contains(term, regex=False) |
                    df['name'].astype(str).str.casefold().str.contains(term, regex=False))
            df = df.loc[mask]
        total = len(df)
        products = df.iloc[(page - 1) * page_size:page * page_size].to_dict('records')
        show_table({'products': products, 'total': total})
        st.caption('Datos de Google actualizados según la caché configurada (30 segundos en la versión reciente).')
    except Exception as exc:
        st.error('No se pudo leer el catálogo Google: ' + str(exc))
    st.stop()

if selected == 'local':
    filt = {}
    if search.strip():
        safe = ''.join(c for c in search.strip() if c.isalnum() or c in ' -').strip()
        if safe:
            filt['or'] = f'(barcode.ilike.*{safe}*,name.ilike.*{safe}*)'
    try:
        # Mismo origen que el verificador: el inventario activo, no la tabla antigua 'products'.
        from inventarios import active_inventory_id
        inventory_id = active_inventory_id()
        if inventory_id is None:
            st.info('No hay un inventario activo. Actívalo en Inventarios independientes.')
            st.stop()
        filt['inventory_id'] = f'eq.{inventory_id}'
        r = api('GET', 'price_inventory_items', {**filt, 'select': 'barcode,name,price',
                'order': 'barcode.asc', 'limit': str(page_size),
                'offset': str((page - 1) * page_size)},
                extra_headers={'Prefer': 'count=exact'})
        content_range = r.headers.get('Content-Range', '')
        count = content_range.rsplit('/', 1)[-1]
        total = int(count) if '/' in content_range and count.isdigit() else None
        show_table({'products': r.json(), 'total': total})
    except (requests.RequestException, RuntimeError) as exc:
        st.error('No se pudo consultar Supabase: ' + error_detail(exc))
    st.stop()

# Cada conexión externa tiene su propio ID de configuración; no se limita a una sola.
source_id = selected.removeprefix('external:')
job_key = (source_id, page, search.strip(), page_size)
if st.session_state.get('catalog_job_page') != job_key:
    st.session_state.pop('catalog_job', None)
    st.session_state.catalog_job_page = job_key
if not st.session_state.get('catalog_job'):
    try:
        created = api('POST', 'external_catalog_jobs', data={
            'configuration_id': source_id, 'page_number': page,
            'page_size': page_size, 'search_term': search.strip(),
            'status': 'pending',
            'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()
        }).json()
        st.session_state.catalog_job = created[0]['id']
    except (requests.RequestException, IndexError, KeyError) as exc:
        st.error('No se pudo iniciar el listado externo: ' + error_detail(exc))
        st.stop()

@st.fragment(run_every='2s')
def show_external_result():
    try:
        jobs = api('GET', 'external_catalog_jobs', {
            'id': 'eq.' + str(st.session_state.catalog_job),
            'select': 'status,result,error_message'}).json()
    except requests.RequestException:
        st.warning('Esperando respuesta de Supabase…')
        return
    if not jobs:
        st.error('No se encontró la solicitud de listado.')
    elif jobs[0]['status'] == 'done':
        show_table(jobs[0].get('result') or {'products': [], 'total': 0}, external=True)
    elif jobs[0]['status'] == 'error':
        st.error('Error del conector: ' + str(jobs[0].get('error_message') or 'desconocido'))
    else:
        st.info('Buscando productos en el servidor seleccionado…')

show_external_result()
