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
                          value='192.168.1.100', help='No es la IP de la base de datos; es la del conector Windows.')
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
