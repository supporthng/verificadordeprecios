"""Consulta móvil con cámara fotográfica y lector Bluetooth HID."""
import hashlib
import html
from io import BytesIO
import streamlit as st
import requests
from datetime import datetime, timedelta, timezone
import time

# Verificación previa: nunca consultar productos sin autorización geográfica.
from mobile_geofence import get_settings, validate_location
from streamlit_js_eval import get_geolocation

try:
    geo_settings = get_settings()
except Exception:
    st.error('Consulta Móvil bloqueada: no se pudo verificar la configuración geográfica.')
    st.stop()

# El enlace público nunca funciona si la restricción está desactivada.
if st.session_state.get('mobile_public_access') and not geo_settings['enabled']:
    st.error('Consulta Móvil pública no disponible: activa y configura la zona autorizada en Administración.')
    st.stop()

GEO_VALIDEZ_SEGUNDOS = 600  # la ubicación autorizada vale 10 minutos

if geo_settings['enabled']:
    if st.session_state.get('geo_ok_hasta', 0) > time.time():
        # Ubicación ya verificada: no volver a pedir el GPS (libera la cámara).
        st.session_state['mobile_geo_allowed'] = True
        st.caption('📍 ' + st.session_state.get('geo_mensaje', 'Ubicación autorizada.'))
    else:
        # Un componente distinto al anterior solicita el GPS desde el navegador.
        # No se autoriza el escáner hasta recibir coordenadas verificables.
        st.session_state['mobile_geo_allowed'] = False
        try:
            # get_geolocation usa navigator.geolocation del navegador y entrega
            # un objeto con coords.latitude, coords.longitude y coords.accuracy.
            response = get_geolocation()
        except Exception as exc:
            st.error('No se pudo iniciar la geolocalización del navegador.')
            st.caption(f'Detalle técnico: {type(exc).__name__}: {exc}')
            st.stop()
        if not response:
            st.info('📍 Verificando tu ubicación… Si el navegador lo pide, toca «Permitir».')
            st.stop()
        if isinstance(response, dict) and response.get('error'):
            st.error('El navegador no pudo obtener la ubicación: ' + str(response['error']))
            st.stop()
        coords = response.get('coords', response) if isinstance(response, dict) else {}
        if not isinstance(coords, dict):
            coords = {}
        current_location = {name: coords.get(name) for name in ('latitude', 'longitude', 'accuracy')}
        if any(value is None for value in current_location.values()):
            st.warning('El navegador no devolvió coordenadas completas. Activa la ubicación precisa y vuelve a intentarlo.')
            st.stop()
        authorized, geo_message = validate_location(current_location, geo_settings)
        if not authorized:
            st.warning(geo_message)
            st.stop()
        # Autorizada: recordarla y recargar SIN el componente GPS. Ese componente
        # vuelve a pedir la ubicación en cada recarga (bucle continuo) y esas
        # solicitudes cancelaban el aviso de permiso de la CÁMARA.
        st.session_state['geo_ok_hasta'] = time.time() + GEO_VALIDEZ_SEGUNDOS
        st.session_state['geo_mensaje'] = geo_message
        st.rerun()
else:
    st.session_state['mobile_geo_allowed'] = True

for key, default in {'movil_codigo':'','movil_ultimo':'','movil_producto':None,'movil_job':None,'movil_error':'','movil_foto':'','movil_mostrar_resultado':False,'movil_camera_version':0,'movil_resultado_desde':None}.items():
    st.session_state.setdefault(key,default)

def api(method,table,params=None,payload=None):
    url=str(st.secrets.get('SUPABASE_URL','')).rstrip('/')
    key=str(st.secrets.get('SUPABASE_SERVICE_ROLE_KEY',''))
    if not url or not key: raise RuntimeError('Faltan credenciales de Supabase.')
    r=requests.request(method,url+'/rest/v1/'+table,params=params,json=payload,
        headers={'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json','Prefer':'return=representation'},timeout=15)
    r.raise_for_status()
    return r.json()

def consultar(code):
    if not st.session_state.get('mobile_geo_allowed', False):
        st.error('Consulta bloqueada: ubicación no autorizada.')
        return
    code=str(code).strip()
    if not code:return
    st.session_state.movil_mostrar_resultado=True
    st.session_state.movil_ultimo=code
    st.session_state.movil_producto=None
    st.session_state.movil_job=None
    st.session_state.movil_error=''
    st.session_state.movil_resultado_desde=None
    try:
        settings=api('GET','price_source_settings',{'id':'eq.1','select':'source_type'})
        if not settings: raise RuntimeError('Configura primero la fuente de datos.')
        mode=settings[0]['source_type']
        if mode=='local':
            # Consulta directa por clave primaria: no descarga el inventario completo.
            from inventarios import find_barcode
            st.session_state.movil_producto=find_barcode(code)
            st.session_state.movil_resultado_desde=time.monotonic()
            return
        elif mode=='google':
            from google_oauth_source import config,catalog
            cfg=config()
            if not cfg or not cfg.get('file_id'): raise RuntimeError('Configura Google desde Administración.')
            df=catalog(cfg['kind'],cfg['file_id'],cfg['sheet_name'] or '',cfg['code_column'],cfg['name_column'],cfg['price_column'])
            rows=df.to_dict('records')
        elif mode=='external':
            sources=api('GET','external_price_sources',{'enabled':'eq.true','select':'id','limit':'2'})
            if len(sources)!=1: raise RuntimeError('Debe existir exactamente una fuente externa habilitada.')
            jobs=api('POST','external_price_jobs',payload={'configuration_id':sources[0]['id'],'barcode':code,'status':'pending','expires_at':(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()})
            if not jobs or not jobs[0].get('id'): raise RuntimeError('No se pudo registrar la consulta.')
            st.session_state.movil_job={'id':jobs[0]['id'],'started':time.monotonic()}
            return
        else: raise RuntimeError('Fuente desconocida.')
        from shared import variantes_codigo
        formas=variantes_codigo(code)
        coincidencias=[r for r in rows if str(r.get('barcode','')).strip() in formas]
        coincidencias.sort(key=lambda r: formas.index(str(r.get('barcode','')).strip()))
        st.session_state.movil_producto=coincidencias[0] if coincidencias else None
        st.session_state.movil_resultado_desde=time.monotonic()
    except Exception as exc:
        st.session_state.movil_error='No se pudo consultar la fuente seleccionada: '+str(exc)

st.markdown("""<style>
/* El resultado utiliza siempre colores claros, incluso con tema oscuro. */
.mobile-result {background:#f3f8ff;color:#092851;border-radius:18px;padding:20px 15px;margin:14px 0 22px;box-sizing:border-box}
.mobile-result .product-label {font-size:14px;font-weight:800;letter-spacing:.07em;color:#436186}
.mobile-result .product-name {font-size:clamp(27px,7vw,48px);font-weight:900;line-height:1.15;overflow-wrap:anywhere;margin:10px 0}
.mobile-result .product-code {font-size:clamp(16px,4.5vw,20px);color:#34507a;margin-bottom:18px;overflow-wrap:anywhere}
.mobile-result .price-panel {background:linear-gradient(110deg,#0b60df,#0649bc);border-radius:15px;padding:20px 14px;color:white;text-align:center}
.mobile-result .price-label {font-size:15px;font-weight:800;letter-spacing:.04em;color:white}
.mobile-result .price-value {font-size:clamp(38px,10vw,70px);font-weight:900;line-height:1.2;color:white;overflow-wrap:anywhere}
.mobile-result .missing {font-size:clamp(24px,7vw,42px);font-weight:900;color:#b91c1c;text-align:center;padding:24px 4px}
/* Estado sin producto: reproduce la pantalla de espera del verificador principal. */
.mobile-not-found {background:#f3f8ff;color:#102b50;border-radius:18px;padding:20px 12px 28px;text-align:center;margin:14px 0 22px}
.mobile-not-found .barcode-card {background:#fff1f2;border-radius:16px;padding:18px 14px;max-width:440px;margin:0 auto 24px}
.mobile-not-found .barcode-bars {height:118px;width:100%;background:repeating-linear-gradient(90deg,#b91c1c 0px,#b91c1c 3px,transparent 3px,transparent 6px,#b91c1c 6px,#b91c1c 8px,transparent 8px,transparent 12px);}
.mobile-not-found .barcode-caption {font-size:13px;color:#102b50;margin-top:10px}
.mobile-not-found .scan-title {font-size:clamp(24px,6vw,40px);font-weight:900;color:#b91c1c;line-height:1.15;margin:10px auto}
.mobile-not-found .scan-hint {font-size:clamp(14px,3.7vw,19px);color:#7b8ba5;margin-top:10px}
@media(max-width:650px){.mobile-result{padding:15px 10px}.mobile-result .price-panel{padding:20px 8px}}
</style>""",unsafe_allow_html=True)

def reiniciar():
    st.session_state.movil_mostrar_resultado=False
    st.session_state.movil_ultimo=''
    st.session_state.movil_producto=None
    st.session_state.movil_job=None
    st.session_state.movil_error=''
    st.session_state.movil_foto=''
    st.session_state.movil_resultado_desde=None
    st.session_state.movil_camera_version+=1

if not st.session_state.movil_mostrar_resultado:
    st.title('📱 Consulta Móvil')
    tab1,tab2=st.tabs(['📷 Cámara','⌨️ Bluetooth / Manual'])
    def leer_foto(archivo):
        """Lee el código de barras de una foto (cámara del navegador o del teléfono)."""
        data=archivo.getvalue(); digest=hashlib.sha256(data).hexdigest()
        if digest==st.session_state.movil_foto:
            return
        st.session_state.movil_foto=digest
        try:
            import zxingcpp
            from PIL import Image,ImageOps
            img=ImageOps.exif_transpose(Image.open(BytesIO(data))).convert('RGB')
            img.thumbnail((2000,2000))  # fotos de 12 MP: más rápido y lee igual
            found=zxingcpp.read_barcodes(img)
            if found:
                consultar(found[0].text)
                st.rerun()
            else: st.warning('No se reconoció el código. Acerca la cámara, enfoca bien y repite la foto.')
        except ImportError: st.error('Falta instalar zxing-cpp (requirements.txt).')
        except Exception: st.error('No se pudo procesar la fotografía.')

    with tab1:
        # Lectura EN VIVO: al detectar el código consulta sola, sin tomar foto.
        from lector_camara import mostrar_lector
        clave_camara=f"camara_codigo_{st.session_state.movil_camera_version}"
        mostrar_lector(clave_camara, lambda: consultar(st.session_state.get(clave_camara,'')))
        # Alternativa: foto con la cámara del teléfono (no depende del permiso del navegador).
        st.markdown('**¿No se activa la cámara?** Toma una foto con la cámara del teléfono:')
        archivo=st.file_uploader('📸 Tomar foto con la cámara del teléfono',type=['jpg','jpeg','png'],
                                 key=f"movil_archivo_{st.session_state.movil_camera_version}",
                                 help='En iPhone/Android elige «Tomar foto» o «Cámara».')
        if archivo:
            leer_foto(archivo)
    with tab2:
        st.caption('Lector Bluetooth HID con sufijo Enter, o entrada manual.')
        # Cuadro nuevo y vacío en cada ciclo (la versión cambia al volver a escanear),
        # para que una lectura no se pegue detrás de la anterior.
        clave_codigo=f"movil_codigo_{st.session_state.movil_camera_version}"
        def _consultar_cuadro():
            consultar(st.session_state.get(clave_codigo,''))
        st.text_input('Código de barras',key=clave_codigo,placeholder='Escanea o escribe el código',on_change=_consultar_cuadro)
        # Si Enter ya consultó, el botón no repite la consulta.
        if st.button('Consultar',use_container_width=True) and not st.session_state.movil_mostrar_resultado:
            _consultar_cuadro()
            st.rerun()

@st.fragment(run_every='1s')
def resultado():
    job=st.session_state.movil_job
    if job:
        if time.monotonic()-job['started']>25:
            st.session_state.movil_job=None
            st.session_state.movil_error='La fuente externa no respondió en 25 segundos.'
        else:
            try:
                rows=api('GET','external_price_jobs',{'id':'eq.'+str(job['id']),'select':'status,result,error_message'})
                if not rows: raise RuntimeError('Solicitud no encontrada.')
                item=rows[0]
                if item['status']=='done':
                    st.session_state.movil_producto=item.get('result')
                    st.session_state.movil_job=None
                    st.session_state.movil_resultado_desde=time.monotonic()
                elif item['status']=='error':
                    st.session_state.movil_error='Error de consulta en la base externa.'
                    st.session_state.movil_job=None
                else:
                    st.info('Consultando base externa…')
                    return
            except Exception:
                st.session_state.movil_error='No se pudo obtener la respuesta del conector.'
                st.session_state.movil_job=None
    if not st.session_state.movil_mostrar_resultado:
        return
    # El plazo comienza cuando termina la consulta, no cuando se toma la foto.
    inicio=st.session_state.movil_resultado_desde
    if inicio is not None and time.monotonic()-inicio >= 5:
        reiniciar()
        st.rerun()
    if st.session_state.movil_error:
        st.error(st.session_state.movil_error)
    elif st.session_state.movil_ultimo:
        product=st.session_state.movil_producto
        if product:
            name=html.escape(str(product.get('name') or 'Sin descripción'))
            # Siempre el código que se escaneó/escribió (lo que el cliente consultó).
            barcode=html.escape(str(st.session_state.movil_ultimo or product.get('barcode') or ''))
            try: price=f"RD$ {float(product.get('price')):,.2f}"
            except (ValueError,TypeError): price=html.escape(str(product.get('price') or 'No disponible'))
            st.markdown('<div class="mobile-result"><div class="product-label">PRODUCTO</div>'
                        f'<div class="product-name">{name}</div><div class="product-code">Código consultado: <strong>{barcode}</strong></div>'
                        '<div class="price-panel"><div class="price-label">PRECIO DE VENTA</div>'
                        f'<div class="price-value">{price}</div></div></div>',unsafe_allow_html=True)
        elif not st.session_state.movil_job:
            barcode=html.escape(st.session_state.movil_ultimo)
            st.markdown(
                '<div class="mobile-not-found">'
                '<div class="barcode-card"><div class="barcode-bars"></div>'
                '<div class="barcode-caption">PRECIO &nbsp;•&nbsp; RD$</div></div>'
                '<div class="scan-title">PRODUCTO NO ENCONTRADO</div>'
                f'<div class="scan-hint">Código consultado: <strong>{barcode}</strong></div>'
                '</div>', unsafe_allow_html=True)
resultado()
if st.session_state.movil_mostrar_resultado:
    if st.button('📷 Escanear otro producto',type='primary',use_container_width=True):
        reiniciar()
        st.rerun()
