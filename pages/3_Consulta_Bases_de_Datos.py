"""Administración de fuentes externas. La consulta se realiza desde app.py."""
import html
import ipaddress
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

st.title('⚙️ Configuración de bases de datos externas')
st.caption('Detecta servidores, bases, tablas y columnas. La consulta de precios se realiza en el verificador principal.')

# La sesión principal controla el acceso; no pedir otra contraseña.
from auth_usuarios import current_user, allowed
_usuario_modulo = current_user()
if not _usuario_modulo or not allowed(_usuario_modulo, "configurar"):
    st.error("No tienes permiso para acceder a esta sección.")
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

# Conexiones completadas por el asistente de Fuentes de datos.
# No inventar servidores ni fijar una base de datos de prueba.
def metadata_job(kind, host, port, database='', schema='', table=''):
    rows = api('POST', 'external_metadata_jobs', data={
        'kind': kind, 'host': host, 'port': int(port), 'database': database or None,
        'schema_name': schema or None, 'table_name': table or None,
        'status': 'pending',
        'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()})
    return rows[0]['id']


def metadata_result(jid):
    rows = api('GET','external_metadata_jobs',params={
        'id':'eq.'+jid,'select':'status,result,error_message'})
    return rows[0] if rows else None


try:
    discovered = api('GET','lan_discovery_requests',params={
        'status':'eq.selected', 'selected_host':'not.is.null',
        'select':'id,selected_host,selected_port,selected_engine,selected_database,created_at',
        'order':'created_at.desc','limit':'100'})
except requests.RequestException:
    discovered=[]

# El asistente puede guardar varias solicitudes para el mismo servidor.
# Deduplicar por servidor, motor y puerto, sin fijar un origen predeterminado.
connections=[]; seen=set()
for item in discovered:
    key_tuple=(item['selected_host'],item['selected_port'],item['selected_engine'])
    if key_tuple not in seen:
        seen.add(key_tuple); connections.append(item)

with st.expander('Administrar conexiones y campos',expanded=not bool(sources)):
    if not connections:
        st.warning('No hay servidores guardados. Conéctalos primero en Fuentes de datos.')
    else:
        connection = st.selectbox('Conexión detectada en Fuentes de datos',connections,
            format_func=lambda c:f"{c['selected_engine']} — {c['selected_host']}:{c['selected_port']}")
        host=connection['selected_host']; port=int(connection['selected_port'])
        engine=connection['selected_engine']
        st.write('**Servidor:**',host,' | **Puerto:**',port,' | **Motor:**',engine)
        if engine!='SQL Server':
            st.warning('El descubrimiento automático de tablas está implementado por ahora para SQL Server.')
        else:
            key_prefix=f'{host}:{port}'
            if st.session_state.get('meta_server')!=key_prefix:
                st.session_state.meta_server=key_prefix
                for k in ('meta_databases','meta_tables','meta_columns','meta_job','meta_kind'):
                    st.session_state.pop(k,None)
            st.markdown('**Credenciales SQL Server en Windows**')
            st.caption('Por seguridad, abre esta página desde el mismo equipo Windows '
                       'que ejecuta el conector. La contraseña no pasa por Streamlit.')
            from urllib.parse import urlencode
            setup_url = (
                'http://127.0.0.1:8765/configure-sql?'
                + urlencode({'host': host, 'port': port})
            )
            st.link_button('Configurar credenciales SQL en Windows', setup_url)
            st.caption('Después de guardar las credenciales, regresa aquí '
                       'y pulsa Detectar bases de datos.')
            if st.button('Detectar bases de datos',type='primary'):
                try:
                    st.session_state.meta_job=metadata_job('databases',host,port)
                    st.session_state.meta_kind='databases'
                except requests.RequestException as exc:
                    st.error('No se pudo solicitar la detección: '+str(exc))
            @st.fragment(run_every='2s')
            def poll_metadata():
                jid=st.session_state.get('meta_job')
                if not jid:return
                try:
                    result=metadata_result(jid)
                    if result and result['status']=='done':
                        st.session_state['meta_'+st.session_state.meta_kind]=result.get('result') or []
                        st.session_state.pop('meta_job',None)
                        st.rerun(scope='app')
                    elif result and result['status']=='error':
                        st.error('Windows: '+str(result.get('error_message')))
                        st.session_state.pop('meta_job',None)
                    else: st.info('Consultando el servidor desde Windows…')
                except requests.RequestException: st.warning('Esperando respuesta de Supabase…')
            poll_metadata()
            dbs=st.session_state.get('meta_databases')
            if dbs is not None:
                if not dbs: st.warning('No se encontraron bases accesibles.')
                else:
                    suggestion=connection.get('selected_database')
                    idx=dbs.index(suggestion) if suggestion in dbs else 0
                    database=st.selectbox('Base de datos',dbs,index=idx,key='meta_db_select')
                    if st.button('Detectar tablas y vistas'):
                        st.session_state.meta_tables=None;st.session_state.meta_columns=None
                        st.session_state.meta_job=metadata_job('tables',host,port,database)
                        st.session_state.meta_kind='tables';st.rerun()
                    tables=st.session_state.get('meta_tables')
                    if tables is not None:
                        if not tables:st.warning('No se encontraron tablas o vistas accesibles.')
                        else:
                            chosen=st.selectbox('Tabla o vista',tables,
                                format_func=lambda t:t['schema']+'.'+t['table'],key='meta_table_select')
                            if st.button('Detectar columnas'):
                                st.session_state.meta_columns=None
                                st.session_state.meta_job=metadata_job('columns',host,port,database,
                                    chosen['schema'],chosen['table'])
                                st.session_state.meta_kind='columns';st.rerun()
                            cols=st.session_state.get('meta_columns')
                            if cols is not None:
                                if not cols:st.warning('La tabla no tiene columnas visibles.')
                                else:
                                    colnames=[c['name'] for c in cols]
                                    def choose_col(label,hints,key):
                                        idx=next((i for i,c in enumerate(colnames)
                                            if any(h in c.lower() for h in hints)),0)
                                        return st.selectbox(label,colnames,index=idx,key=key)
                                    code=choose_col('Columna del código',['codigo','barcode','ean','sku'],'meta_code')
                                    description=choose_col('Columna de descripción',['descrip','nombre','name'],'meta_description')
                                    price=choose_col('Columna de precio',['precio1','price','precio'],'meta_price')
                                    name=st.text_input('Nombre de esta configuración',
                                        value=f'{database} — {chosen["schema"]}.{chosen["table"]}')
                                    if st.button('Guardar configuración para consultar precios'):
                                        try:
                                            api('POST','external_price_sources',data={
                                                'name':name.strip(),'engine':engine,'host':host,'port':port,
                                                'database':database,'schema_name':chosen['schema'],
                                                'table_name':chosen['table'],'code_column':code,
                                                'description_column':description,'price_column':price,
                                                'enabled':False})
                                            st.success('Configuración guardada.');st.rerun()
                                        except requests.RequestException as exc:
                                            st.error('No se pudo guardar: '+str(exc))
    if sources:
        st.markdown('**Configuraciones guardadas**')
        for src in sources:
            left,right=st.columns([4,1])
            left.write(f"{src['name']} — {src['database']} / {src['schema_name']}.{src['table_name']}")
            if right.button('Eliminar',key='del_'+src['id']):
                try:
                    api('DELETE','external_price_sources',params={'id':'eq.'+src['id']})
                    st.rerun()
                except requests.RequestException:
                    st.error('No se pudo eliminar. Puede haber consultas asociadas.')

st.divider()
st.subheader('Fuente externa que utilizará la consulta')
if not sources:
    st.warning('Primero detecta la base, selecciona una tabla y sus columnas y guarda la configuración.')
    st.stop()

# Solo una configuración externa habilitada a la vez.
options = {str(x['id']): x for x in sources}
active_ids = [str(x['id']) for x in sources if x.get('enabled')]
selected_id = st.selectbox(
    'Configuración de productos', list(options),
    index=list(options).index(active_ids[0]) if active_ids and active_ids[0] in options else 0,
    format_func=lambda i: (
        f"{options[i]['name']} — {options[i]['database']} / "
        f"{options[i]['schema_name']}.{options[i]['table_name']}"
    ),
)
selected = options[selected_id]
st.write('**Código:**', selected['code_column'])
st.write('**Descripción:**', selected['description_column'])
st.write('**Precio:**', selected['price_column'])
if st.button('Activar esta configuración externa', type='primary'):
    try:
        # Deshabilitar primero, y habilitar la seleccionada. Si falla la segunda
        # operación, ninguna configuración queda activa: nunca usar otra por error.
        api('PATCH', 'external_price_sources',
            params={'enabled': 'eq.true'}, data={'enabled': False})
        api('PATCH', 'external_price_sources',
            params={'id': 'eq.' + selected_id}, data={'enabled': True})
        st.success('Configuración externa activada. Para utilizarla, selecciona Base externa en Fuentes de datos.')
        st.rerun()
    except requests.RequestException as exc:
        st.error('No se pudo activar la configuración externa: ' + str(exc))

if len(active_ids) == 1:
    st.info('Configuración externa activa: ' + options[active_ids[0]]['name'])
elif len(active_ids) > 1:
    st.error('Hay varias configuraciones externas habilitadas. Activa solo una antes de consultar precios.')
else:
    st.warning('Todavía no hay ninguna configuración externa activa.')
