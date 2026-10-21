import pandas as pd
import streamlit as st
from auth_usuarios import current_user,allowed
from inventarios import api,all_inventories
from shared import normalize_header

user=current_user()
if not user or not allowed(user,'cargar_archivo'):
    st.error('Sin permiso de administración de inventarios.');st.stop()
st.title('📚 Inventarios independientes')
st.caption('Cada archivo Excel se carga en un inventario seleccionado. No se mezclan los catálogos.')
try: items=all_inventories()
except Exception as e:
    st.error('Ejecuta INSTALAR_INVENTARIOS.sql en Supabase antes de continuar.');st.code(str(e));st.stop()
with st.form('crear_inventario'):
    name=st.text_input('Nombre del nuevo inventario')
    if st.form_submit_button('Crear inventario'):
        try:
            if not name.strip():raise ValueError('Introduce un nombre.')
            api('POST','price_inventories',data={'name':name.strip()},prefer='return=minimal');st.rerun()
        except Exception as e:st.error(str(e))
if not items:st.info('Crea un inventario para empezar.');st.stop()
names={int(i['id']):i['name'] for i in items}
selected=st.selectbox('Inventario de destino',list(names),format_func=lambda i:names[i])
active=next((i for i in items if i['is_active']),None)
st.info('Activo en Consulta de Precios: '+(active['name'] if active else 'Ninguno'))
if st.button('Activar inventario seleccionado',disabled=bool(active and int(active['id'])==selected)):
    try:api('POST','rpc/activate_price_inventory',data={'target_id':selected});st.rerun()
    except Exception as e:st.error(str(e))
st.subheader('Importar Excel')
file=st.file_uploader('Selecciona archivo .xlsx',type='xlsx')
if file:
    try:
        raw=pd.read_excel(file,header=None,dtype=str,engine='openpyxl')
        keys=('codigobarra','codigobarras','barcode')
        row=next((i for i,r in raw.head(40).iterrows() if any(normalize_header(x) in keys for x in r)),None)
        if row is None:raise ValueError('No se encontró encabezado CODIGO BARRA.')
        file.seek(0)
        df=pd.read_excel(file,header=row,dtype=str,engine='openpyxl')
        cols=list(df.columns)
        def idx(options):return next((i for i,x in enumerate(cols) if normalize_header(x) in options),0)
        bc=st.selectbox('Código de barras',cols,index=idx(keys))
        nc=st.selectbox('Descripción',cols,index=idx(('nombredelproducto','nombre','descripcion','producto')))
        pc=st.selectbox('Precio',cols,index=idx(('precio','precioventa')))
        if len({bc,nc,pc})!=3:raise ValueError('Selecciona tres columnas distintas.')
        data=df[[bc,nc,pc]].copy();data.columns=['barcode','name','price']
        data=data.dropna(subset=['barcode','name','price'])
        data['barcode']=data['barcode'].str.strip().str.replace(r'\.0$','',regex=True)
        data['name']=data['name'].str.strip()
        data['price']=pd.to_numeric(data['price'].str.replace(',','',regex=False),errors='coerce')
        data=data[data.barcode.str.len().gt(0)&~data.barcode.str.upper().isin(['N/D','NAN','NONE'])&data.name.str.len().gt(0)&data.price.notna()&(data.price>=0)]
        data=data.drop_duplicates('barcode',keep='last')
        st.write(f'Productos válidos: **{len(data):,}**');st.dataframe(data.head(30))
        replace=st.checkbox('Reemplazar todos los productos de ESTE inventario (en lugar de actualizar)')
        confirm=st.checkbox('Confirmo la publicación en '+names[selected])
        if st.button('Publicar Excel',disabled=not confirm or data.empty,type='primary'):
            try:
                rows=data.to_dict('records')
                if replace:api('POST','rpc/replace_price_inventory',data={'target_id':selected,'new_items':rows})
                else:
                    for n in range(0,len(rows),200):
                        api('POST','price_inventory_items',{'on_conflict':'inventory_id,barcode'},[dict(r,inventory_id=selected) for r in rows[n:n+200]],prefer='resolution=merge-duplicates,return=minimal')
                st.success('Inventario publicado. Los otros inventarios no fueron modificados.')
            except Exception as e:st.error(str(e))
    except Exception as e:st.error('Error al leer Excel: '+str(e))
st.divider();st.subheader('Eliminar inventario')
if active and int(active['id'])==selected:st.warning('Activa otro inventario antes de eliminar este.')
else:
    typed=st.text_input('Para eliminar, escribe exactamente: '+names[selected])
    if st.button('Eliminar inventario y todos sus productos',disabled=typed!=names[selected]):
        try:api('DELETE','price_inventories',{'id':f'eq.{selected}'},prefer='return=minimal');st.rerun()
        except Exception as e:st.error(str(e))
