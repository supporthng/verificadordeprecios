"""Configuración de ubicación del establecimiento mediante GPS del navegador."""
import math
import re
import streamlit as st
from mobile_geofence import get_settings, save_settings
from streamlit_geolocation import streamlit_geolocation
import pandas as pd
import requests
from urllib.parse import unquote

from auth_usuarios import require_admin
require_admin()

st.title('📍 Ubicación autorizada · Consulta Móvil')
st.caption('Configura el centro del establecimiento y la distancia máxima autorizada.')
try:
    cfg = get_settings()
except Exception:
    st.error('No se pudo leer la configuración geográfica de Supabase.')
    st.stop()

for key, value in [('geo_form_lat',float(cfg['latitude'])),
                   ('geo_form_lon',float(cfg['longitude'])),
                   ('geo_form_enabled',bool(cfg['enabled'])),
                   ('geo_form_radius',int(cfg['radius_m'])),
                   ('geo_attempt',0),('geo_detecting',False)]:
    st.session_state.setdefault(key,value)

# Aplicar cambios pendientes antes de crear los widgets con esas claves.
# Streamlit impide modificar una clave después de instanciar su widget.
geo_pending = st.session_state.pop('geo_pending_coordinates', None)
if geo_pending is not None:
    st.session_state['geo_form_lat'], st.session_state['geo_form_lon'] = geo_pending

st.info('Pulsa Detectar mi ubicación desde el dispositivo que está en el establecimiento. El navegador debe solicitar permiso para compartir tu ubicación.')
if st.button('📍 Detectar mi ubicación', use_container_width=True):
    st.session_state.geo_attempt += 1
    st.session_state.geo_detecting = True
    st.session_state.geo_detect_error = None

# El componente debe permanecer montado después del clic. La clave cambia en
# cada intento para forzar un montaje nuevo y una nueva solicitud al navegador.
if st.session_state.geo_detecting:
    st.caption('Solicitando ubicación al navegador… Acepta el permiso cuando aparezca.')
    try:
        location = streamlit_geolocation(key=f'geo_permission_{st.session_state.geo_attempt}')
    except Exception as exc:
        st.session_state.geo_detecting = False
        st.error('No se pudo iniciar la solicitud de ubicación del navegador.')
        location = None
    if isinstance(location,dict) and location.get('latitude') is not None and location.get('longitude') is not None:
        try:
            lat, lon = float(location['latitude']),float(location['longitude'])
            accuracy = float(location.get('accuracy') or 0)
            if not all(map(math.isfinite,(lat,lon,accuracy))) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError('Coordenadas inválidas')
            st.session_state.geo_pending_coordinates = (lat, lon)
            st.session_state.geo_accuracy = accuracy
            st.session_state.geo_detecting = False
            st.session_state.geo_location_applied = True
            st.rerun()
        except (ValueError,TypeError):
            st.error('El navegador devolvió coordenadas inválidas.')
    elif isinstance(location,dict) and location.get('error'):
        st.error('El navegador no pudo obtener la ubicación: '+str(location['error']))
        st.session_state.geo_detecting = False
    else:
        st.warning('Si no aparece el permiso, revisa los ajustes de ubicación del navegador y vuelve a pulsar Detectar mi ubicación.')
        st.caption('En iPhone: Ajustes → Privacidad y seguridad → Localización → Safari (o Chrome), permitir ubicación precisa. En Safari también revisa aA → Configuración del sitio web → Ubicación → Preguntar. Abre el enlace directamente en Safari/Chrome, no en el navegador interno de otra aplicación.')

if st.session_state.get('geo_location_applied'):
    st.success('Coordenadas detectadas. Pulsa Guardar ubicación para aplicarlas.')
    if st.session_state.get('geo_accuracy',0)>50:
        st.warning('Precisión GPS baja. Intenta nuevamente cerca de una ventana o al aire libre.')

st.toggle('Exigir ubicación para Consulta Móvil',key='geo_form_enabled')
st.number_input('Distancia máxima permitida (metros)', min_value=10, max_value=10000,
                step=10, key='geo_form_radius', help='Radio alrededor del establecimiento para Consulta Móvil.')
st.number_input('Latitud',min_value=-90.0,max_value=90.0,step=0.000001,format='%.7f',key='geo_form_lat')
st.number_input('Longitud',min_value=-180.0,max_value=180.0,step=0.000001,format='%.7f',key='geo_form_lon')
st.divider()
st.subheader('Buscar dirección o establecimiento')
st.caption('Búsqueda gratuita mundial. Si un negocio no figura en mapas abiertos, usa Google Maps para copiar sus coordenadas.')
query = st.text_input('Nombre, calle, sector, ciudad o dirección', key='geo_search_text',
                      placeholder='Ej.: supermercado en Santo Domingo')
if st.button('🔎 Buscar ubicación', use_container_width=True):
    if not query.strip():
        st.warning('Escribe un lugar o una dirección.')
    else:
        results = []
        try:
            r = requests.get('https://photon.komoot.io/api/',
                params={'q':query.strip(), 'limit':8, 'lang':'es'},
                headers={'User-Agent':'ConsultaPreciosLocationPicker/1.0'}, timeout=12)
            r.raise_for_status()
            for feature in r.json().get('features', []):
                coords=feature.get('geometry',{}).get('coordinates',[])
                props=feature.get('properties',{})
                if len(coords)==2:
                    label=', '.join(str(props.get(k)) for k in ('name','street','city','state','country') if props.get(k))
                    results.append({'label':label or 'Ubicación', 'lat':float(coords[1]),'lon':float(coords[0])})
        except (requests.RequestException, ValueError, TypeError, KeyError):
            pass
        if not results:
            try:
                r=requests.get('https://nominatim.openstreetmap.org/search',
                    params={'q':query.strip(),'format':'json','limit':8},
                    headers={'User-Agent':'ConsultaPreciosLocationPicker/1.0'},timeout=12)
                r.raise_for_status()
                results=[{'label':x['display_name'],'lat':float(x['lat']),'lon':float(x['lon'])} for x in r.json()]
            except (requests.RequestException, ValueError, TypeError, KeyError):
                pass
        st.session_state.geo_results=results
        if not results:
            st.warning('Sin resultados en los mapas abiertos. Puedes localizar el negocio en Google Maps y pegar sus coordenadas debajo.')
results=st.session_state.get('geo_results',[])
if results:
    selected_index=st.selectbox('Resultados encontrados',range(len(results)),
        format_func=lambda i:results[i]['label'],key='geo_result_index')
    if st.button('📍 Seleccionar resultado',use_container_width=True):
        result=results[selected_index]
        st.session_state.geo_pending_coordinates=(result['lat'],result['lon'])
        st.session_state.geo_location_applied=False
        st.rerun()

st.subheader('Usar coordenadas de Google Maps')
st.caption('En Google Maps haz clic derecho en el punto exacto y copia los dos números de latitud y longitud.')
coordinates=st.text_input('Pegar coordenadas o enlace de Google Maps',key='geo_pasted_coords',
                           placeholder='18.123456, -69.123456')
if st.button('Aplicar coordenadas',use_container_width=True):
    value=unquote(coordinates.strip())
    match=(re.search(r'@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)',value)
           or re.search(r'[?&](?:q|query|ll)=(-?\d{1,2}\.\d+)%?2[Cc](-?\d{1,3}\.\d+)',coordinates)
           or re.search(r'(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)',value))
    if match:
        lat0,lon0=map(float,match.groups())
        if -90<=lat0<=90 and -180<=lon0<=180:
            st.session_state.geo_pending_coordinates=(lat0,lon0)
            st.rerun()
        else:
            st.error('Las coordenadas están fuera del rango permitido.')
    else:
        st.warning('Este enlace no contiene coordenadas explícitas. Abre el lugar en Google Maps, haz clic derecho sobre el marcador y copia las coordenadas.')

st.subheader('Nombre o dirección de las coordenadas')
st.caption('La dirección se consulta en OpenStreetMap sin facturación. No es posible obtener el nombre comercial exclusivo de Google Maps sin su API.')
if st.button('🔎 Identificar dirección de estas coordenadas', use_container_width=True):
    try:
        latitude = float(st.session_state.geo_form_lat)
        longitude = float(st.session_state.geo_form_lon)
        if latitude == 0 and longitude == 0:
            st.warning('Primero selecciona unas coordenadas válidas.')
        else:
            response = requests.get(
                'https://nominatim.openstreetmap.org/reverse',
                params={'lat': latitude, 'lon': longitude, 'format': 'json', 'zoom': 18, 'addressdetails': 1},
                headers={'User-Agent': 'SistemaConsultaPrecios/1.0 (reverse-geocoding)'},
                timeout=15,
            )
            response.raise_for_status()
            place = response.json()
            st.session_state.geo_resolved_name = place.get('name') or place.get('display_name') or 'Sin dirección registrada'
            st.session_state.geo_resolved_point = (latitude, longitude)
    except (requests.RequestException, ValueError, TypeError):
        st.error('No se pudo consultar el nombre o dirección. Puedes guardar las coordenadas igualmente.')
if st.session_state.get('geo_resolved_point') == (
    float(st.session_state.geo_form_lat), float(st.session_state.geo_form_lon)
):
    st.info('📍 ' + st.session_state.get('geo_resolved_name', 'Sin dirección registrada'))

st.subheader('Vista previa del punto autorizado')
lat,lon=float(st.session_state.geo_form_lat),float(st.session_state.geo_form_lon)
if lat==0 and lon==0:
    st.info('Selecciona un resultado, detecta tu ubicación o introduce las coordenadas.')
else:
    st.map(pd.DataFrame([{'lat':lat,'lon':lon}]),latitude='lat',longitude='lon',zoom=16,size=140)
    st.caption('Centro seleccionado. La restricción de acceso móvil utilizará el radio configurado arriba. Puedes ajustar la latitud y longitud en los campos superiores.')
    st.link_button('Abrir punto en Google Maps',f'https://www.google.com/maps?q={lat:.7f},{lon:.7f}',use_container_width=True)

if st.button('Guardar ubicación',type='primary',use_container_width=True):
    try:
        latitude = float(st.session_state.geo_form_lat)
        longitude = float(st.session_state.geo_form_lon)
        if latitude == 0 and longitude == 0:
            st.error('Selecciona primero la ubicación del establecimiento.')
        else:
            save_settings(latitude, longitude, st.session_state.geo_form_enabled,
                          st.session_state.geo_form_radius)
            saved = get_settings()
            if (abs(float(saved['latitude']) - latitude) > 0.0000001
                or abs(float(saved['longitude']) - longitude) > 0.0000001
                or bool(saved['enabled']) != bool(st.session_state.geo_form_enabled)
                or int(saved['radius_m']) != int(st.session_state.geo_form_radius)):
                st.error('Supabase no confirmó los valores guardados. Revisa los permisos de la tabla mobile_geo_settings.')
            else:
                st.success('Ubicación guardada y verificada en Supabase.')
                st.caption(f'Latitud: {latitude:.7f} · Longitud: {longitude:.7f} · Radio: {int(st.session_state.geo_form_radius)} metros')
    except Exception as exc:
        st.error('No se pudo guardar la ubicación en Supabase.')
        st.code(str(exc))
