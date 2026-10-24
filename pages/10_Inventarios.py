import pandas as pd
import streamlit as st
from auth_usuarios import current_user,allowed
from inventarios import api,all_inventories
from shared import normalize_header
import sucursales

user=current_user()
if not user or not allowed(user,'cargar_archivo'):
    st.error('Sin permiso de administración de inventarios.');st.stop()
st.title('📚 Inventarios independientes')
st.caption('Aquí se crean, se cargan y se identifican TODOS los inventarios. La Principal usa el inventario activo; '
           'cada sucursal elige el suyo en Administración › Sucursales. No se mezclan los catálogos.')


def _equipos():
    """Si hay equipos sin internet en uso, enviarles el inventario activo nuevo."""
    import publicar_equipos
    ok,res=publicar_equipos.actualizar_si_publicado()
    if ok:st.session_state['aviso_equipos_inv']=f"Equipos sin internet: {res['productos']:,} productos publicados."
    elif isinstance(res,str):st.session_state['aviso_equipos_inv']='⚠️ No se pudo actualizar los equipos sin internet: '+res


if 'aviso_equipos_inv' in st.session_state:st.info(st.session_state.pop('aviso_equipos_inv'))
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


def _usos():
    """{id de inventario: [quién lo usa]} — la Principal (activo) y las sucursales que lo eligieron."""
    usos={i:[] for i in names}
    for i in items:
        if i['is_active']:usos[int(i['id'])].append('🏠 '+sucursales.nombre_principal())
    try:
        for s in sucursales.listar():
            f=sucursales.fuente(s)
            if f['tipo']=='inventario' and f['inventario_id'] in usos:usos[f['inventario_id']].append('🏬 '+s['nombre'])
            elif f['tipo']=='principal':
                act=next((int(i['id']) for i in items if i['is_active']),None)
                if act is not None:usos[act].append('🏬 '+s['nombre']+' (igual que la Principal)')
    except Exception:pass   # sin sucursales instaladas
    return usos


def _cantidad(inv_id):
    try:
        import requests
        from supabase_cliente import cabeceras,clave_servidor
        r=requests.head(str(st.secrets['SUPABASE_URL']).rstrip('/')+'/rest/v1/price_inventory_items',timeout=15,
                        params={'select':'barcode','inventory_id':f'eq.{inv_id}'},
                        headers=cabeceras(clave_servidor(),{'Prefer':'count=exact','Range':'0-0'}))
        return int(r.headers.get('Content-Range','*/0').split('/')[-1])
    except Exception:return None


usos=_usos()
st.subheader('Inventarios')
st.dataframe([{'Inventario':names[i],'Productos':(lambda n:'—' if n is None else f'{n:,}')(_cantidad(i)),
               'Lo usa':', '.join(usos[i]) or '— nadie —'} for i in names],hide_index=True,use_container_width=True)
selected=st.selectbox('Inventario',list(names),format_func=lambda i:names[i])
active=next((i for i in items if i['is_active']),None)
st.info('Lo usa: '+(', '.join(usos[selected]) or 'nadie todavía (elígelo como inventario de la Principal o de una sucursal)'))
with st.expander('✏️ Cambiar el nombre'):
    nuevo=st.text_input('Nombre',value=names[selected],key=f'renombrar_{selected}',max_chars=80)
    if st.button('Guardar nombre',disabled=not nuevo.strip() or nuevo.strip()==names[selected]):
        try:
            api('PATCH','price_inventories',{'id':f'eq.{selected}'},{'name':nuevo.strip()},prefer='return=minimal')
            _equipos();st.rerun()
        except Exception as e:st.error(str(e))
if st.button('🏠 Usar este inventario en la Principal',disabled=bool(active and int(active['id'])==selected)):
    try:
        api('POST','rpc/activate_price_inventory',data={'target_id':selected})
        _equipos();st.rerun()
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
                if usos[selected]:_equipos()
            except Exception as e:st.error(str(e))
    except Exception as e:st.error('Error al leer Excel: '+str(e))
st.divider();st.subheader('Eliminar inventario')
_suc_usan=[u for u in usos[selected] if u.startswith('🏬') and '(igual que la Principal)' not in u]
if active and int(active['id'])==selected:st.warning('La Principal usa este inventario: elige otro para la Principal antes de eliminarlo.')
elif _suc_usan:st.warning('Lo usan estas sucursales: '+', '.join(_suc_usan)+'. Cámbiales la fuente en Sucursales antes de eliminarlo.')
else:
    typed=st.text_input('Para eliminar, escribe exactamente: '+names[selected])
    if st.button('Eliminar inventario y todos sus productos',disabled=typed!=names[selected]):
        try:api('DELETE','price_inventories',{'id':f'eq.{selected}'},prefer='return=minimal');st.rerun()
        except Exception as e:st.error(str(e))
