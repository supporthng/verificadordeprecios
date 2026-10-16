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


st.subheader('Buscar servidores desde Windows')
st.info('La búsqueda se ejecuta en un equipo Windows dentro de tu red. '
        'Debes tener instalado y encendido el conector Windows.')
bridge_ip = st.text_input('IP del equipo Windows que ejecuta el conector',
                          value='10.0.0.190', help='No es la IP de la base de datos; es la del conector Windows.')
bridge_port = st.number_input('Puerto del conector Windows', min_value=1, max_value=65535, value=8765)

if st.button('1. Iniciar búsqueda en Windows', type='primary'):
    try:
        ip = ipaddress.ip_address(bridge_ip.strip())
        if not ip.is_private:
            st.error('Usa la IP privada del equipo Windows.')
        else:
            request_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            supabase('POST', payload={'id': request_id,
                'expires_at': (now + timedelta(minutes=10)).isoformat(), 'status': 'pending'})
            st.session_state.lan_request_id = request_id
            st.session_state.lan_bridge_url = f'http://{ip}:{bridge_port}/?{urlencode({"request_id": request_id})}'
            st.session_state.pop('lan_selection', None)
    except (ValueError, requests.RequestException) as error:
        st.error('No se pudo iniciar la búsqueda. Verifica la IP y que ejecutaste supabase_bridge.sql.')
        st.caption(type(error).__name__)

if st.session_state.get('lan_request_id'):
    st.markdown('**2. Abre el explorador en Windows (o Android conectado al mismo Wi-Fi).**')
    st.link_button('Abrir búsqueda en Windows', st.session_state.lan_bridge_url)
    st.caption('Inicia sesión en el conector, busca en tu red y selecciona un servidor.')
    if st.button('3. Recibir selección desde Windows'):
        try:
            rows = supabase('GET', params={'id': 'eq.' + st.session_state.lan_request_id,
                                         'select': 'status,selected_host,selected_port,selected_engine,expires_at'})
            if not rows:
                st.warning('No se encontró la solicitud. Vuelve a iniciar la búsqueda.')
            elif datetime.fromisoformat(rows[0]['expires_at'].replace('Z', '+00:00')) < datetime.now(timezone.utc):
                st.warning('La búsqueda venció. Inicia otra (duración: 10 minutos).')
            elif rows[0]['status'] == 'selected':
                st.session_state.lan_selection = rows[0]
                st.success('Selección recibida correctamente.')
            else:
                st.info('Todavía no se ha seleccionado un servidor en Windows.')
        except requests.RequestException as error:
            st.error('No se pudo recuperar la selección desde Supabase.')
            st.caption(type(error).__name__)

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
database = st.text_input('Nombre de la base de datos (introducir manualmente)')
st.caption('La búsqueda detecta IP y puerto, pero no identifica automáticamente '
           'credenciales, nombre de base de datos ni tablas.')
st.warning('Esta pantalla prepara los parámetros; no conecta todavía a la facturación. '
           'Las credenciales y consultas SQL deben configurarse en el servidor Windows, '
           'no en Streamlit Cloud. No pegues contraseñas aquí.')
if selected:
    st.success('Servidor seleccionado desde Windows: ' + str(host) + ':' + str(port))


st.divider()
st.subheader('Buscar bases de datos de SQL Server')
st.caption('La consulta se hace en el conector Windows; las credenciales SQL nunca se introducen aquí.')
if engine != 'SQL Server':
    st.info('La búsqueda de bases de datos está disponible inicialmente para SQL Server.')
else:
    if st.button('4. Buscar bases de datos', type='primary'):
        try:
            ip = ipaddress.ip_address(host.strip())
            number = int(port)
            if ip.version != 4 or not ip.is_private or not 1 <= number <= 65535:
                raise ValueError('Servidor o puerto inválido')
            rid = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            response = requests.post(
                URL + '/rest/v1/lan_db_requests',
                json={'id': rid, 'host': str(ip), 'port': number, 'engine': 'SQL Server',
                      'status': 'pending', 'expires_at': (now + timedelta(minutes=10)).isoformat()},
                headers={'apikey': KEY, 'Authorization': 'Bearer ' + KEY,
                         'Content-Type': 'application/json', 'Prefer': 'return=representation'},
                timeout=15,
            )
            response.raise_for_status()
            st.session_state.sql_db_request_id = rid
            st.session_state.sql_db_link = (
                f'http://{bridge_ip.strip()}:{int(bridge_port)}/databases?'
                + urlencode({'db_request_id': rid})
            )
            st.session_state.pop('sql_db_names', None)
        except (ValueError, requests.RequestException) as exc:
            st.error('No se pudo crear la solicitud de bases de datos.')
            st.caption(type(exc).__name__)

    if st.session_state.get('sql_db_request_id'):
        st.link_button('5. Abrir consulta en Windows', st.session_state.sql_db_link)
        st.caption('Inicia sesión en el conector si hace falta y pulsa Consultar bases de datos.')
        if st.button('6. Recibir bases de datos'):
            try:
                response = requests.get(
                    URL + '/rest/v1/lan_db_requests',
                    params={'id': 'eq.' + st.session_state.sql_db_request_id,
                            'select': 'status,database_names,expires_at'},
                    headers={'apikey': KEY, 'Authorization': 'Bearer ' + KEY}, timeout=15,
                )
                response.raise_for_status()
                rows = response.json()
                if not rows:
                    st.warning('No se encontró la solicitud.')
                elif rows[0]['status'] == 'done':
                    st.session_state.sql_db_names = rows[0].get('database_names') or []
                    st.success('Bases de datos recibidas.')
                else:
                    st.info('Pendiente: completa la consulta desde Windows primero.')
            except requests.RequestException:
                st.error('No se pudo recibir la respuesta desde Supabase.')

    names = st.session_state.get('sql_db_names')
    if names is not None:
        if names:
            st.selectbox('Base de datos disponible', names, key='sql_database_selected')
            st.info('La base seleccionada aún no está conectada al verificador de precios.')
        else:
            st.warning('El usuario SQL no tiene bases de datos visibles o accesibles.')
