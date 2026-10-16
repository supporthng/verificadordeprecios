"""Fuentes de datos: descubrimiento LAN vía conector Windows.
No reemplaza el verificador actual ni cambia sus fuentes activas.
"""
import ipaddress
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
import streamlit as st

st.title('Fuentes de datos')
st.caption('Configura y detecta servidores sin modificar el verificador de Supabase.')

admin_password = str(st.secrets.get('ADMIN_PASSWORD', ''))
if not admin_password:
    st.error('Falta ADMIN_PASSWORD en Streamlit Secrets.')
    st.stop()
if not st.session_state.get('fuentes_admin_ok', False):
    with st.form('login_fuentes'):
        password = st.text_input('Contraseña de Administración', type='password')
        enter = st.form_submit_button('Entrar')
    if enter:
        if secrets.compare_digest(password, admin_password):
            st.session_state.fuentes_admin_ok = True
            st.rerun()
        else:
            st.error('Contraseña incorrecta')
    st.stop()

URL = str(st.secrets.get('SUPABASE_URL', '')).strip().rstrip('/')
KEY = str(st.secrets.get('SUPABASE_SERVICE_ROLE_KEY', '')).strip()
if not URL or not KEY:
    st.error('Configura SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY en Streamlit Secrets.')
    st.stop()


def supabase(method, params=None, payload=None):
    response = requests.request(method, URL + '/rest/v1/lan_discovery_requests',
        params=params, json=payload, timeout=15,
        headers={'apikey': KEY, 'Authorization': 'Bearer ' + KEY,
                 'Content-Type': 'application/json', 'Prefer': 'return=representation'})
    response.raise_for_status()
    return response.json()


# La vuelta desde el conector abre la misma pestaña y puede iniciar una nueva sesión.
# Recuperar la solicitud original mediante su identificador en la URL.
return_id = str(st.query_params.get('lan_result', '')).strip()
if return_id:
    try:
        uuid.UUID(return_id)
        st.session_state.lan_request_id = return_id
        st.session_state.lan_request_expires = datetime.now(timezone.utc) + timedelta(minutes=1)
        st.query_params.clear()
    except ValueError:
        st.query_params.clear()

st.subheader('Buscar servidores desde Windows')
st.info('La búsqueda se ejecuta en un equipo Windows dentro de tu red. '
        'Debes tener instalado y encendido el conector Windows.')
bridge_ip = st.text_input('IP del equipo Windows que ejecuta el conector',
                          value='10.0.0.190', help='No es la IP de la base de datos; es la del conector Windows.')
bridge_port = st.number_input('Puerto del conector Windows', min_value=1, max_value=65535, value=8765)

# Una sola acción: se prepara una solicitud pendiente y el botón abre Windows.
# La solicitud se crea una vez por sesión y se renueva al vencer.
def preparar_busqueda():
    ip = ipaddress.ip_address(bridge_ip.strip())
    if ip.version != 4 or not ip.is_private:
        raise ValueError('Usa una IP privada IPv4 del equipo Windows.')
    now = datetime.now(timezone.utc)
    expires = st.session_state.get('lan_request_expires')
    same_bridge = st.session_state.get('lan_bridge_address') == (str(ip), int(bridge_port))
    if (st.session_state.get('lan_request_id') and expires and now < expires and
            (same_bridge or return_id) and
            st.session_state.get('lan_request_id') and
            not st.session_state.get('lan_selection')):
        return
    request_id = str(uuid.uuid4())
    expiry = now + timedelta(minutes=30)
    supabase('POST', payload={'id': request_id,
        'expires_at': expiry.isoformat(), 'status': 'pending'})
    st.session_state.lan_request_id = request_id
    st.session_state.lan_request_expires = expiry
    st.session_state.lan_bridge_address = (str(ip), int(bridge_port))
    st.session_state.lan_bridge_url = (
        f'http://{ip}:{int(bridge_port)}/?{urlencode({"request_id": request_id})}'
    )
    st.session_state.pop('lan_selection', None)


if not st.session_state.get('lan_selection'):
    try:
        preparar_busqueda()
        # target=_self mantiene el recorrido dentro de la pestaña actual.
        import html as html_module
        url_safe = html_module.escape(st.session_state.lan_bridge_url, quote=True)
        st.markdown('<a href="' + url_safe + '" target="_self" '
                    'style="display:inline-block;background:#e44b50;color:white;'
                    'padding:12px 18px;border-radius:8px;text-decoration:none;'
                    'font-weight:600">Iniciar búsqueda en Windows</a>',
                    unsafe_allow_html=True)
        st.caption('Se abrirá el conector Windows, donde se solicita su contraseña local.')
    except (ValueError, requests.RequestException) as error:
        st.error('No se pudo preparar la búsqueda. Comprueba la IP y Supabase.')
        st.caption(type(error).__name__)

    @st.fragment(run_every='3s')
    def recibir_seleccion_automatica():
        rid = st.session_state.get('lan_request_id')
        if not rid or st.session_state.get('lan_selection'):
            return
        if datetime.now(timezone.utc) >= st.session_state.get('lan_request_expires',
                                                               datetime.now(timezone.utc)):
            st.warning('La solicitud venció. Recarga esta página para iniciar otra.')
            return
        try:
            rows = supabase('GET', params={
                'id': 'eq.' + rid,
                'select': 'status,selected_host,selected_port,selected_engine,selected_database,expires_at'})
            if rows and rows[0].get('status') == 'selected' and rows[0].get('selected_database'):
                st.session_state.lan_selection = rows[0]
                st.rerun(scope='app')
            else:
                st.info('Esperando la selección del servidor en Windows…')
        except requests.RequestException:
            st.warning('No se pudo comprobar la selección. Se reintentará automáticamente.')

    recibir_seleccion_automatica()
else:
    st.success('Servidor y base de datos recibidos desde Windows.')
    if st.button('Buscar otro servidor'):
        st.session_state.pop('lan_selection', None)
        st.session_state.pop('lan_request_id', None)
        st.rerun()

selected = st.session_state.get('lan_selection', {})
st.divider()
st.subheader('Configuración del origen de datos')
engine_options = ['SQL Server', 'MySQL / MariaDB', 'PostgreSQL', 'Firebird', 'Oracle',
                  'IBM Db2', 'SQL Anywhere', 'SQLite', 'Access', 'ODBC genérico', 'API REST']
engine = st.selectbox('Motor', engine_options,
                      index=engine_options.index(selected.get('selected_engine'))
                      if selected.get('selected_engine') in engine_options else 0)
host = st.text_input('Servidor / IP detectado', value=selected.get('selected_host') or '')
port = st.text_input('Puerto detectado', value=str(selected.get('selected_port') or ''))
database = st.text_input('Base de datos seleccionada', value=selected.get('selected_database') or '')
st.caption('La búsqueda detecta IP y puerto, pero no identifica automáticamente '
           'credenciales, nombre de base de datos ni tablas.')
st.warning('Esta pantalla prepara los parámetros; no conecta todavía a la facturación. '
           'Las credenciales y consultas SQL deben configurarse en el servidor Windows, '
           'no en Streamlit Cloud. No pegues contraseñas aquí.')
if selected:
    st.success('Servidor seleccionado desde Windows: ' + str(host) + ':' + str(port))


st.caption('La selección se recibe al regresar a esta página. '
           'Las credenciales SQL permanecen en Windows.')
