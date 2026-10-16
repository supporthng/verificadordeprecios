"""Página informativa para administrar el tipo de origen sin exponer contraseñas.
La sincronización se configura y ejecuta en el servidor local.
"""
import streamlit as st

st.set_page_config(page_title='Fuentes de datos',page_icon='🗄️',layout='centered')
st.title('Fuentes de datos')
st.info('La consulta de precios actual continúa utilizando Supabase. Esta pantalla documenta las opciones de integración; no cambia conexiones por sí sola.')

sources = ['Supabase (actual)', 'SQL Server', 'MySQL / MariaDB', 'PostgreSQL',
           'Firebird', 'SQLite', 'Microsoft Access', 'API REST']
selected = st.selectbox('Tipo de fuente', sources)
mode = st.radio('Modalidad', ['Sincronización hacia Supabase', 'Consulta directa por puente local (pendiente)'])

if selected == 'Supabase (actual)':
    st.success('Conexión existente: el verificador utiliza los Secrets de Streamlit.')
else:
    st.write('**Origen seleccionado:**',selected)
    if mode.startswith('Sincronización'):
        st.success('Disponible mediante el conector local incluido en el paquete.')
        st.write('Instala el conector en el servidor del sistema de facturación, define una consulta SELECT que devuelva barcode, name y price y configura sus variables de entorno.')
    else:
        st.warning('La conexión directa requiere desplegar un puente privado autenticado; no está implementada en este paquete. No abras puertos de la base de datos a Internet.')

st.subheader('Seguridad')
st.write('Utiliza una cuenta de solo lectura para la facturación. Guarda las contraseñas únicamente en el servidor local, nunca en esta página ni en GitHub.')
st.caption('El conector solo agrega o actualiza productos en Supabase; no elimina registros.')
