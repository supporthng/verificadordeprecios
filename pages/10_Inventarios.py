"""Inventarios (Excel): aquí se crean, se cargan y se identifican TODOS los inventarios.

La Principal usa el inventario activo; cada sucursal elige el suyo en Administración › Sucursales.
"""
import os

import pandas as pd
import requests
import streamlit as st

from auth_usuarios import current_user, allowed
from inventarios import api, all_inventories
from shared import normalize_header
import sucursales

user = current_user()
if not user or not allowed(user, 'cargar_archivo'):
    st.error('Sin permiso de administración de inventarios.')
    st.stop()
st.title('📚 Inventarios')
st.caption('Aquí se crean, se cargan y se identifican todos los inventarios. La Principal usa uno; '
           'cada sucursal elige el suyo en Administración › Sucursales. Los inventarios no se mezclan.')


def _equipos():
    """Si hay equipos sin internet en uso, enviarles los precios nuevos."""
    import publicar_equipos
    ok, res = publicar_equipos.actualizar_si_publicado()
    if ok:
        st.session_state['aviso_equipos_inv'] = f"Equipos sin internet: {res['productos']:,} productos publicados."
    elif isinstance(res, str):
        st.session_state['aviso_equipos_inv'] = '⚠️ No se pudo actualizar los equipos sin internet: ' + res


if 'aviso_inventario' in st.session_state:
    st.success(st.session_state.pop('aviso_inventario'))
if 'aviso_equipos_inv' in st.session_state:
    st.info(st.session_state.pop('aviso_equipos_inv'))

try:
    items = all_inventories()
except Exception as e:
    st.error('Ejecuta INSTALAR_INVENTARIOS.sql en Supabase antes de continuar.')
    st.code(str(e))
    st.stop()
names = {int(i['id']): i['name'] for i in items}
active = next((i for i in items if i['is_active']), None)


def _usos():
    """{id de inventario: [quién lo usa]}: la Principal y las sucursales que lo eligieron."""
    usos = {i: [] for i in names}
    act = int(active['id']) if active else None
    if act is not None:
        usos[act].append('🏠 ' + sucursales.nombre_principal())
    try:
        for s in sucursales.listar():
            f = sucursales.fuente(s)
            if f['tipo'] == 'inventario' and f['inventario_id'] in usos:
                usos[f['inventario_id']].append('🏬 ' + s['nombre'])
            elif f['tipo'] == 'principal' and act is not None:
                usos[act].append('🏬 ' + s['nombre'] + ' (igual que la Principal)')
    except Exception:
        pass   # sin sucursales instaladas
    return usos


def _cantidad(inv_id):
    try:
        from supabase_cliente import cabeceras, clave_servidor
        r = requests.head(str(st.secrets['SUPABASE_URL']).rstrip('/') + '/rest/v1/price_inventory_items', timeout=15,
                          params={'select': 'barcode', 'inventory_id': f'eq.{inv_id}'},
                          headers=cabeceras(clave_servidor(), {'Prefer': 'count=exact', 'Range': '0-0'}))
        return int(r.headers.get('Content-Range', '*/0').split('/')[-1])
    except Exception:
        return None


usos = _usos()

# ====================================================================== lista
if items:
    st.dataframe([{'Inventario': names[i],
                   'Productos': (lambda n: '—' if n is None else f'{n:,}')(_cantidad(i)),
                   'Lo usa': ', '.join(usos[i]) or '— nadie —'} for i in names],
                 hide_index=True, use_container_width=True)
else:
    st.info('Todavía no hay inventarios. Carga un Excel abajo y crea el primero.')

# ====================================================================== cargar un Excel
st.subheader('📥 Cargar un Excel')
file = st.file_uploader('Archivo .xlsx', type='xlsx')
if file:
    try:
        raw = pd.read_excel(file, header=None, dtype=str, engine='openpyxl')
        keys = ('codigobarra', 'codigobarras', 'barcode')
        row = next((i for i, r in raw.head(40).iterrows() if any(normalize_header(x) in keys for x in r)), None)
        if row is None:
            raise ValueError('No se encontró el encabezado CODIGO BARRA.')
        file.seek(0)
        df = pd.read_excel(file, header=row, dtype=str, engine='openpyxl')
        cols = list(df.columns)

        def idx(options):
            return next((i for i, x in enumerate(cols) if normalize_header(x) in options), 0)

        c1, c2, c3 = st.columns(3)
        bc = c1.selectbox('Código de barras', cols, index=idx(keys))
        nc = c2.selectbox('Descripción', cols, index=idx(('nombredelproducto', 'nombre', 'descripcion', 'producto')))
        pc = c3.selectbox('Precio', cols, index=idx(('precio', 'precioventa')))
        if len({bc, nc, pc}) != 3:
            raise ValueError('Selecciona tres columnas distintas.')
        data = df[[bc, nc, pc]].copy()
        data.columns = ['barcode', 'name', 'price']
        data = data.dropna(subset=['barcode', 'name', 'price'])
        data['barcode'] = data['barcode'].str.strip().str.replace(r'\.0$', '', regex=True)
        data['name'] = data['name'].str.strip()
        data['price'] = pd.to_numeric(data['price'].str.replace(',', '', regex=False), errors='coerce')
        data = data[data.barcode.str.len().gt(0) & ~data.barcode.str.upper().isin(['N/D', 'NAN', 'NONE'])
                    & data.name.str.len().gt(0) & data.price.notna() & (data.price >= 0)]
        data = data.drop_duplicates('barcode', keep='last')
        st.write(f'Productos válidos: **{len(data):,}**')
        st.dataframe(data.head(30), hide_index=True, use_container_width=True)

        st.markdown('**¿En qué inventario se guardan?**')
        destinos = {'existente': 'Actualizar un inventario existente', 'nuevo': 'Crear un inventario nuevo'}
        destino = st.radio('Destino', list(destinos), format_func=destinos.get, horizontal=True,
                           index=0 if names else 1, label_visibility='collapsed')
        objetivo, nombre_nuevo, reemplazar = None, '', False
        if destino == 'existente':
            if not names:
                st.warning('Todavía no hay inventarios: elige «Crear un inventario nuevo».')
            else:
                objetivo = st.selectbox(
                    'Inventario', list(names),
                    format_func=lambda i: names[i] + (f"  · lo usa: {', '.join(usos[i])}" if usos[i] else ''))
                modos = {False: 'Actualizar: agrega los nuevos y cambia los precios; conserva los demás productos',
                         True: 'Reemplazar todo: el inventario queda exactamente como este Excel'}
                reemplazar = st.radio('Cómo', list(modos), format_func=modos.get)
        else:
            sugerido = os.path.splitext(file.name)[0].replace('_', ' ').strip()[:80]
            nombre_nuevo = st.text_input('Nombre del inventario nuevo', value=sugerido, max_chars=80,
                                         help='Por ejemplo, el nombre de la sucursal que lo usará.').strip()
            if nombre_nuevo.lower() in (n.lower() for n in names.values()):
                st.warning('Ya existe un inventario con ese nombre: elige otro o actualiza el existente.')
                nombre_nuevo = ''
        destino_texto = names.get(objetivo) if destino == 'existente' else nombre_nuevo
        confirm = st.checkbox(f'Confirmo la carga en «{destino_texto}»' if destino_texto else 'Confirmo la carga',
                              disabled=not destino_texto)
        if st.button('Publicar Excel', disabled=not (confirm and destino_texto) or data.empty, type='primary'):
            try:
                rows = data.to_dict('records')
                with st.spinner('Guardando productos…'):
                    if destino == 'nuevo':
                        creado = api('POST', 'price_inventories', data={'name': nombre_nuevo},
                                     prefer='return=representation')
                        objetivo = int(creado[0]['id'])
                        reemplazar = True
                    if reemplazar:
                        api('POST', 'rpc/replace_price_inventory', data={'target_id': objetivo, 'new_items': rows})
                    else:
                        for n in range(0, len(rows), 200):
                            api('POST', 'price_inventory_items', {'on_conflict': 'inventory_id,barcode'},
                                [dict(r, inventory_id=objetivo) for r in rows[n:n + 200]],
                                prefer='resolution=merge-duplicates,return=minimal')
                    if usos.get(objetivo):
                        _equipos()
                st.session_state['aviso_inventario'] = (
                    f'«{destino_texto}»: {len(rows):,} productos ' + ('cargados en el inventario nuevo.'
                                                                      if destino == 'nuevo' else 'guardados.')
                    + ('' if usos.get(objetivo) else ' Para usarlo, elígelo en la Principal (abajo) o en una sucursal '
                                                       '(Administración › Sucursales).'))
                st.rerun()
            except Exception as e:
                st.error(str(e))
    except Exception as e:
        st.error('Error al leer el Excel: ' + str(e))

if not items:
    st.stop()

# ====================================================================== administrar
st.divider()
st.subheader('⚙️ Administrar un inventario')
selected = st.selectbox('Inventario', list(names), format_func=lambda i: names[i], key='administrar')
st.info('Lo usa: ' + (', '.join(usos[selected]) or 'nadie todavía (elígelo para la Principal o para una sucursal)'))
if st.button('🏠 Usar este inventario en la Principal', disabled=bool(active and int(active['id']) == selected)):
    try:
        api('POST', 'rpc/activate_price_inventory', data={'target_id': selected})
        _equipos()
        st.rerun()
    except Exception as e:
        st.error(str(e))
with st.expander('✏️ Cambiar el nombre'):
    nuevo = st.text_input('Nombre', value=names[selected], key=f'renombrar_{selected}', max_chars=80)
    if st.button('Guardar nombre', disabled=not nuevo.strip() or nuevo.strip() == names[selected]):
        try:
            api('PATCH', 'price_inventories', {'id': f'eq.{selected}'}, {'name': nuevo.strip()}, prefer='return=minimal')
            _equipos()
            st.rerun()
        except Exception as e:
            st.error(str(e))
with st.expander('🗑️ Eliminar inventario'):
    _suc_usan = [u for u in usos[selected] if u.startswith('🏬') and '(igual que la Principal)' not in u]
    if active and int(active['id']) == selected:
        st.warning('La Principal usa este inventario: elige otro para la Principal antes de eliminarlo.')
    elif _suc_usan:
        st.warning('Lo usan estas sucursales: ' + ', '.join(_suc_usan)
                   + '. Cámbiales la fuente en Sucursales antes de eliminarlo.')
    else:
        typed = st.text_input('Para eliminar, escribe exactamente: ' + names[selected])
        if st.button('Eliminar inventario y todos sus productos', disabled=typed != names[selected]):
            try:
                api('DELETE', 'price_inventories', {'id': f'eq.{selected}'}, prefer='return=minimal')
                st.rerun()
            except Exception as e:
                st.error(str(e))
