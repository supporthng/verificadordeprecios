"""Verificador independiente de bases externas. app.py no se modifica."""
import html
import ipaddress
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

st.set_page_config(page_title='Consulta externa de precios', page_icon='🏷️', layout='centered')
st.title('🏷️ Consulta de precios — Bases externas')
st.caption('Verificador independiente. No utiliza la tabla products de Supabase.')

admin_password = str(st.secrets.get('ADMIN_PASSWORD', ''))
if not admin_password:
    st.error('Falta ADMIN_PASSWORD en Secrets.'); st.stop()
if not st.session_state.get('external_admin_ok'):
    with st.form('external_login'):
        pwd = st.text_input('Contraseña de administración', type='password')
        ok = st.form_submit_button('Entrar')
    if ok:
        if secrets.compare_digest(pwd, admin_password):
            st.session_state.external_admin_ok = True
            st.rerun()
        else: st.error('Contraseña incorrecta')
    st.stop()

url = str(st.secrets.get('SUPABASE_URL', '')).rstrip('/')
key = str(st.secrets.get('SUPABASE_SERVICE_ROLE_KEY', ''))
if not url or not key:
    st.error('Falta SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY en Secrets.'); st.stop()
headers = {'apikey': key, 'Authorization': 'Bearer ' + key,
           'Content-Type': 'application/json', 'Prefer': 'return=representation'}

def api(method, table, *, params=None, data=None):
    res = requests.request(method, url + '/rest/v1/' + table,
                           params=params, json=data, headers=headers, timeout=15)
    res.raise_for_status()
    return res.json()

try:
    sources = api('GET', 'external_price_sources', params={'select': '*', 'order': 'name.asc'})
except requests.RequestException:
    st.error('No se pudieron consultar los orígenes. Ejecuta primero el SQL de instalación.'); st.stop()

with st.expander('Administrar conexiones y campos', expanded=not bool(sources)):
    st.info('La base de prueba no está fijada. Configura cualquier servidor y tabla compatibles.')
    with st.form('new_external_source'):
        name = st.text_input('Nombre de la conexión', placeholder='Ej.: Sucursal principal')
        engine = st.selectbox('Motor', ['SQL Server'])
        st.caption('Primera versión operativa: SQL Server. Se podrán incorporar otros motores.')
        host = st.text_input('IP privada del servidor SQL', placeholder='10.0.0.150')
        port = st.number_input('Puerto SQL', min_value=1, max_value=65535, value=1433)
        database = st.text_input('Base de datos')
        schema = st.text_input('Esquema', value='dbo')
        table = st.text_input('Tabla o vista de productos')
        code = st.text_input('Columna del código')
        description = st.text_input('Columna de la descripción')
        price = st.text_input('Columna del precio')
        submit = st.form_submit_button('Guardar conexión')
    if submit:
        try:
            ip = ipaddress.ip_address(host.strip())
            if ip.version != 4 or not ip.is_private:
                raise ValueError('El servidor debe tener una IP privada IPv4')
            identifiers = [database, schema, table, code, description, price]
            if not all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', v.strip()) for v in identifiers):
                raise ValueError('Los nombres deben contener letras, números o guion bajo, y empezar por letra o guion bajo')
            if not name.strip(): raise ValueError('Indica un nombre para la conexión')
            api('POST', 'external_price_sources', data={
                'name': name.strip(), 'engine': engine, 'host': str(ip), 'port': int(port),
                'database': database.strip(), 'schema_name': schema.strip(),
                'table_name': table.strip(), 'code_column': code.strip(),
                'description_column': description.strip(), 'price_column': price.strip()})
            st.success('Conexión guardada. Debe existir una credencial protegida para este servidor en Windows.')
            st.rerun()
        except (ValueError, requests.RequestException) as exc:
            st.error('No se pudo guardar la conexión: ' + str(exc))
    if sources:
        st.markdown('**Conexiones existentes**')
        for src in sources:
            left, right = st.columns([4, 1])
            left.write(f"{src['name']} — {src['engine']} / {src['database']} / {src['schema_name']}.{src['table_name']}")
            if right.button('Eliminar', key='del_' + src['id']):
                try:
                    api('DELETE', 'external_price_sources', params={'id': 'eq.' + src['id']})
                    st.rerun()
                except requests.RequestException:
                    st.error('No se pudo eliminar. Puede haber consultas asociadas.')

active = [x for x in sources if x.get('enabled')]
if not active:
    st.info('Agrega una conexión para comenzar.'); st.stop()
selected = st.selectbox('Base de datos a consultar', active, format_func=lambda x: x['name'])

if 'external_job' not in st.session_state: st.session_state.external_job = None
if 'external_result' not in st.session_state: st.session_state.external_result = None
if 'external_message' not in st.session_state: st.session_state.external_message = ''

with st.form('external_scan', clear_on_submit=True):
    barcode = st.text_input('ESCANEA TU CÓDIGO AQUÍ', placeholder='Código del producto')
    search = st.form_submit_button('Consultar precio', type='primary', use_container_width=True)
if search:
    if barcode.strip():
        try:
            rows = api('POST', 'external_price_jobs', data={
                'configuration_id': selected['id'], 'barcode': barcode.strip(),
                'status': 'pending',
                'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()})
            st.session_state.external_job = rows[0]['id']
            st.session_state.external_result = None
            st.session_state.external_message = 'Consultando la base de datos Windows…'
            st.session_state.external_started = time.monotonic()
        except requests.RequestException:
            st.error('No se pudo enviar la consulta a Supabase.')
    else: st.warning('Escanea o escribe un código.')

@st.fragment(run_every='1s')
def status():
    jid = st.session_state.external_job
    if jid:
        try:
            rows = api('GET', 'external_price_jobs', params={
                'id': 'eq.' + jid, 'select': 'status,result,error_message'})
            if rows and rows[0]['status'] in ('done', 'error'):
                item = rows[0]
                st.session_state.external_result = item.get('result')
                st.session_state.external_message = (
                    'Producto no encontrado' if item['status'] == 'done' and not item.get('result')
                    else ('Error del conector: ' + str(item.get('error_message') or 'Error desconocido'))
                    if item['status'] == 'error' else '')
                st.session_state.external_job = None
                st.session_state.external_finished = time.monotonic()
            elif time.monotonic() - st.session_state.external_started > 25:
                st.session_state.external_job = None
                st.session_state.external_message = 'Tiempo de espera agotado. Comprueba el conector Windows.'
                st.session_state.external_finished = time.monotonic()
        except requests.RequestException:
            st.warning('Esperando respuesta del servicio…')
    elif st.session_state.get('external_finished') and time.monotonic() - st.session_state.external_finished > 10:
        st.session_state.external_result = None
        st.session_state.external_message = ''
        st.session_state.external_finished = None
    item = st.session_state.external_result
    if item:
        st.markdown('### ' + html.escape(str(item['name'])))
        st.caption('Código: ' + str(item['barcode']))
        st.metric('PRECIO DE VENTA', 'RD$ ' + format(float(item['price']), ',.2f'))
    elif st.session_state.external_message:
        st.info(st.session_state.external_message)
status()
