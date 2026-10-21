"""Configuración y validación de la zona móvil (GPS del navegador no es antifraude)."""
import math
import requests
import streamlit as st

TABLE = 'mobile_geo_settings'

def _request(method, params=None, payload=None):
    base = str(st.secrets.get('SUPABASE_URL', '')).rstrip('/')
    key = str(st.secrets.get('SUPABASE_SERVICE_ROLE_KEY', ''))
    if not base or not key:
        raise RuntimeError('Configura SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY.')
    r = requests.request(method, base + '/rest/v1/' + TABLE,
        params=params, json=payload, timeout=12,
        headers={'apikey': key, 'Authorization': 'Bearer ' + key,
                 'Content-Type': 'application/json',
                 'Prefer': 'resolution=merge-duplicates,return=representation'})
    r.raise_for_status()
    return r.json()

def get_settings():
    rows = _request('GET', {'id': 'eq.1', 'select': 'enabled,latitude,longitude,radius_m'})
    if not rows:
        raise RuntimeError('No existe configuración geográfica. Ejecuta INSTALAR_GEO_MOVIL.sql.')
    return rows[0]

def save_settings(latitude, longitude, enabled=True, radius_m=100):
    radius_m = int(radius_m)
    if not 10 <= radius_m <= 10000:
        raise ValueError("El radio permitido debe estar entre 10 y 10000 metros.")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError('Coordenadas fuera de rango.')
    _request('POST', {'on_conflict': 'id'},
             {'id': 1, 'latitude': latitude, 'longitude': longitude,
              'radius_m': radius_m, 'enabled': bool(enabled)})

def distance_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2-p1, math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0, 1-a)))

def validate_location(location, settings):
    if not isinstance(location, dict):
        return False, 'Autoriza el acceso a la ubicación para utilizar Consulta Móvil.'
    try:
        lat, lon = float(location['latitude']), float(location['longitude'])
        accuracy = float(location.get('accuracy') or 0)
        if not all(map(math.isfinite, (lat, lon, accuracy))):
            raise ValueError()
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and accuracy > 0):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        return False, 'El navegador devolvió coordenadas incompletas o una precisión GPS inválida. Activa Ubicación precisa y vuelve a intentarlo.'
    radius = float(settings['radius_m'])
    if accuracy > radius:
        return False, f'Ubicación imprecisa (±{accuracy:.0f} m). Activa ubicación precisa y vuelve a intentar.'
    distance = distance_m(lat, lon, float(settings['latitude']), float(settings['longitude']))
    if distance > radius:
        return False, f'Fuera de la zona autorizada ({radius:.0f} metros). Distancia aproximada: {distance:.0f} m.'
    return True, f'Ubicación autorizada · distancia aproximada {distance:.0f} m.'
