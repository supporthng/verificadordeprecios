"""Seleccionar fuente utilizada por la consulta tradicional y móvil."""
import requests
import streamlit as st
from auth_usuarios import current_user, allowed

user = current_user()
if not user or not allowed(user, 'fuentes'):
    st.error('No tienes permiso para seleccionar fuentes de datos.')
    st.stop()

st.title('🎯 Selección de Fuentes de Datos')
st.caption('Elige la fuente que utilizará Consulta de Precios. No elimina ni mezcla inventarios.')
url = str(st.secrets.get('SUPABASE_URL', '')).strip().rstrip('/')
key = str(st.secrets.get('SUPABASE_SERVICE_ROLE_KEY', '')).strip()
if not url or not key:
    st.error('Falta configurar Supabase en Streamlit Secrets.')
    st.stop()
headers = {'apikey': key, 'Authorization': 'Bearer ' + key,
           'Content-Type': 'application/json', 'Prefer': 'return=representation'}

def api(method, table, params=None, data=None):
    response = requests.request(method, url + '/rest/v1/' + table,
                                params=params, json=data, headers=headers, timeout=20)
    response.raise_for_status()
    return response.json() if response.content else []

try:
    settings = api('GET', 'price_source_settings', {'id': 'eq.1', 'select': 'source_type'})
    current = settings[0]['source_type'] if settings else None
    if current not in ('local', 'google', 'external'):
        st.error('No se encontró una fuente válida en price_source_settings.')
        st.stop()
    sources = api('GET', 'external_price_sources',
                  {'select': 'id,name,enabled', 'order': 'name.asc'})
    from inventarios import all_inventories
    inventories = all_inventories()
except Exception as exc:
    st.error('No se pudo leer la configuración de fuentes de datos.')
    st.code(str(exc))
    st.stop()

labels = {'local': 'Supabase — Inventarios independientes',
          'external': 'Base de datos externa — conector Windows',
          'google': 'Google Drive / Google Sheets'}
st.info('Fuente actual: ' + labels[current])
selected = st.radio('Fuente que utilizará Consulta de Precios', list(labels),
                    index=list(labels).index(current), format_func=lambda value: labels[value])
if selected == 'local':
    active = next((item for item in inventories if item.get('is_active')), None)
    if active:
        st.success('Inventario activo: ' + active['name'])
        st.caption('Para cambiarlo, utiliza Inventarios independientes.')
    else:
        st.warning('No hay un inventario activo. Ve a Inventarios independientes, carga los productos y activa el catálogo.')
elif selected == 'external':
    enabled = [item for item in sources if item.get('enabled')]
    if len(enabled) == 1:
        st.success('Configuración externa activa: ' + enabled[0]['name'])
    else:
        st.warning('Debes activar exactamente una configuración en Configurar Consulta.')
else:
    st.info('Verifica que el archivo y las columnas estén configurados en la conexión de Google.')

ready = (selected != 'local' or any(item.get('is_active') for item in inventories))
ready = ready and (selected != 'external' or sum(bool(item.get('enabled')) for item in sources) == 1)
if st.button('Guardar fuente seleccionada', type='primary', disabled=not ready):
    try:
        api('PATCH', 'price_source_settings', {'id': 'eq.1'}, {'source_type': selected})
        verify = api('GET', 'price_source_settings', {'id': 'eq.1', 'select': 'source_type'})
        if not verify or verify[0]['source_type'] != selected:
            raise RuntimeError('La fuente seleccionada no quedó guardada.')
        st.success('Fuente seleccionada y guardada correctamente.')
        st.rerun()
    except Exception as exc:
        st.error('No se pudo guardar la fuente seleccionada.')
        st.code(str(exc))
