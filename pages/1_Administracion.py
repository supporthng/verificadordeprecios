import hmac
import requests
import streamlit as st
from shared import parse_excel, publish, secret

st.set_page_config(page_title='Administración de precios', page_icon='🔒', layout='centered')
st.title('🔒 Administración de precios')
st.caption('Carga y publicación de inventario')

admin_password = secret('ADMIN_PASSWORD')
if not admin_password:
    st.error('ADMIN_PASSWORD no está configurada en Streamlit Secrets.')
    st.stop()

if not st.session_state.get('admin_authenticated', False):
    with st.form('admin_login'):
        password = st.text_input('Contraseña de administrador', type='password')
        submit = st.form_submit_button('Ingresar')
    if submit:
        if hmac.compare_digest(password, admin_password):
            st.session_state['admin_authenticated'] = True
            st.rerun()
        else:
            st.error('Contraseña incorrecta')
    st.stop()

st.success('Acceso administrativo')
if st.button('Cerrar sesión'):
    st.session_state['admin_authenticated'] = False
    st.rerun()

file = st.file_uploader('Selecciona Excel desde este dispositivo', type=['xlsx'])
if file:
    try:
        incoming = parse_excel(file)
    except (ValueError, Exception):
        st.error('No se pudo leer el Excel. Comprueba sus columnas y valores.')
        st.stop()
    st.write(f'{len(incoming):,} productos válidos')
    st.dataframe(incoming.head(12), hide_index=True)
    st.warning('Publicar agrega o actualiza por código de barras. No elimina productos ausentes del Excel.')
    confirmed = st.checkbox('Confirmo que quiero publicar estos precios')
    if st.button('Publicar en Supabase', type='primary', disabled=not confirmed):
        try:
            with st.spinner('Publicando productos...'):
                publish(incoming)
            st.success('Precios publicados. Recarga la consulta para ver los cambios.')
        except (requests.RequestException, ValueError):
            st.error('La publicación no se completó. Verifica Supabase antes de reintentar.')
