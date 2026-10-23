"""Ubicación autorizada de Consulta Móvil: buscar el establecimiento por nombre,
pegar un enlace de Google Maps o detectar el GPS, y ver el radio en el mapa."""
import math
import re
from urllib.parse import unquote, urlsplit

import pandas as pd
import requests
import streamlit as st

from auth_usuarios import require_admin
from mobile_geofence import get_settings, save_settings

require_admin()

AGENTE = {"User-Agent": "SistemaConsultaPrecios/1.1 (configuracion de ubicacion)"}
# País para dar prioridad a los resultados: código ISO y recuadro (minLon, minLat, maxLon, maxLat).
PAISES = {
    "República Dominicana": ("do", (-72.01, 17.36, -68.32, 19.93)),
    "Todos los países": (None, None),
}

st.title("📍 Ubicación y acceso")
st.caption("Define dónde está el establecimiento y a qué distancia se permite consultar desde el celular "
           "y, si lo eliges, entrar a la Consulta de Precios sin usuario.")
try:
    cfg = get_settings()
except Exception:
    st.error("No se pudo leer la configuración geográfica de Supabase.")
    st.stop()

for clave, valor in [("geo_form_lat", float(cfg["latitude"])), ("geo_form_lon", float(cfg["longitude"])),
                     ("geo_form_enabled", bool(cfg["enabled"])), ("geo_form_radius", int(cfg["radius_m"])),
                     ("geo_attempt", 0), ("geo_detecting", False), ("geo_results", []),
                     ("geo_origen", "")]:
    st.session_state.setdefault(clave, valor)

# Aplicar coordenadas pendientes ANTES de crear los campos de latitud/longitud.
pendiente = st.session_state.pop("geo_pending_coordinates", None)
if pendiente is not None:
    st.session_state["geo_form_lat"], st.session_state["geo_form_lon"] = pendiente


def aplicar(lat, lon, origen):
    """Usar estas coordenadas como centro (se guardan con el botón Guardar)."""
    st.session_state.geo_pending_coordinates = (float(lat), float(lon))
    st.session_state.geo_origen = origen


# ---------------------------------------------------------------------------
# Búsqueda por nombre (OpenStreetMap: Photon + Nominatim, gratis, sin claves)
# ---------------------------------------------------------------------------
TIPOS = {"supermarket": "supermercado", "convenience": "colmado / tienda", "pharmacy": "farmacia",
         "hardware": "ferretería", "department_store": "tienda por departamentos", "mall": "centro comercial",
         "bakery": "panadería", "butcher": "carnicería", "greengrocer": "verdulería", "wholesale": "mayorista",
         "restaurant": "restaurante", "cafe": "cafetería", "fuel": "gasolinera", "bank": "banco",
         "clothes": "ropa", "electronics": "electrónica", "beauty": "salón de belleza", "shop": "tienda",
         "marketplace": "mercado", "residential": "zona residencial", "house": "dirección",
         "road": "calle", "primary": "avenida", "secondary": "calle", "tertiary": "calle",
         "city": "ciudad", "town": "pueblo", "suburb": "sector", "neighbourhood": "barrio"}


def _tipo(valor):
    v = str(valor or "").strip().lower()
    return TIPOS.get(v, v.replace("_", " "))


def _texto_direccion(partes):
    vistos, salida = set(), []
    for p in partes:
        p = str(p or "").strip()
        if p and p.lower() not in vistos:
            vistos.add(p.lower())
            salida.append(p)
    return ", ".join(salida)


@st.cache_data(ttl=86400, show_spinner=False)
def buscar_lugares(texto, pais, lat_ref, lon_ref):
    """Combina Photon y Nominatim; prioriza el país elegido y la zona actual."""
    codigo, recuadro = PAISES.get(pais, (None, None))
    resultados = []
    # 1) Photon: tolera errores de escritura y búsquedas parciales.
    try:
        params = {"q": texto, "limit": 10, "lang": "default"}
        if codigo:
            params["countrycode"] = codigo.upper()
            params["bbox"] = ",".join(str(x) for x in recuadro)
        if lat_ref or lon_ref:
            params.update(lat=lat_ref, lon=lon_ref, location_bias_scale=0.3)
        r = requests.get("https://photon.komoot.io/api/", params=params, headers=AGENTE, timeout=12)
        r.raise_for_status()
        for f in r.json().get("features", []):
            lon, lat = f["geometry"]["coordinates"][:2]
            p = f.get("properties", {})
            calle = " ".join(str(x) for x in (p.get("street"), p.get("housenumber")) if x)
            resultados.append({
                "nombre": p.get("name") or calle or "Ubicación",
                "detalle": _texto_direccion([calle, p.get("district"), p.get("city"), p.get("state"), p.get("country")]),
                "tipo": _tipo(p.get("osm_value")),
                "lat": float(lat), "lon": float(lon)})
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError):
        pass
    # 2) Nominatim: direcciones y lugares registrados con su nombre oficial.
    try:
        params = {"q": texto, "format": "jsonv2", "limit": 10, "addressdetails": 1, "accept-language": "es"}
        if codigo:
            params["countrycodes"] = codigo
        r = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=AGENTE, timeout=12)
        r.raise_for_status()
        for x in r.json():
            a = x.get("address", {})
            nombre = x.get("name") or str(x.get("display_name", "")).split(",")[0]
            resultados.append({
                "nombre": nombre or "Ubicación",
                "detalle": _texto_direccion([a.get("road"), a.get("suburb") or a.get("neighbourhood"),
                                             a.get("city") or a.get("town") or a.get("village"),
                                             a.get("state"), a.get("country")]),
                "tipo": _tipo(x.get("type")),
                "lat": float(x["lat"]), "lon": float(x["lon"])})
    except (requests.RequestException, ValueError, TypeError, KeyError):
        pass
    # Quitar duplicados (mismo lugar devuelto por los dos servicios).
    unicos, vistos = [], set()
    for res in resultados:
        clave = (res["nombre"].lower(), round(res["lat"], 3), round(res["lon"], 3))
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(res)
    return unicos[:12]


st.subheader("🔎 1. Busca el establecimiento por nombre")
with st.form("buscar_lugar"):
    c1, c2 = st.columns([3, 2])
    texto = c1.text_input("Nombre, dirección o sector",
                          placeholder="Ej.: Supermercado Bravo Churchill, Santo Domingo")
    pais = c2.selectbox("Buscar en", list(PAISES))
    buscar = st.form_submit_button("Buscar", type="primary", use_container_width=True)
if buscar:
    if len(texto.strip()) < 3:
        st.warning("Escribe al menos 3 letras.")
    else:
        lat0, lon0 = float(st.session_state.geo_form_lat), float(st.session_state.geo_form_lon)
        cerca = (round(lat0, 2), round(lon0, 2)) if (lat0 or lon0) else (0.0, 0.0)
        with st.spinner("Buscando en los mapas…"):
            st.session_state.geo_results = buscar_lugares(texto.strip(), pais, *cerca)
        st.session_state.pop("geo_eleccion", None)
        if not st.session_state.geo_results:
            st.warning("No apareció en los mapas abiertos. Prueba con la calle o el sector, "
                       "o usa el enlace de Google Maps (opción 2).")

resultados = st.session_state.geo_results
if resultados:
    def _al_elegir():
        i = st.session_state.get("geo_eleccion")
        if i is not None:
            r = resultados[i]
            aplicar(r["lat"], r["lon"], f"{r['nombre']} · {r['detalle']}")

    st.radio(
        f"{len(resultados)} resultado(s). Elige el correcto (se marca en el mapa de abajo):",
        range(len(resultados)), index=None, key="geo_eleccion", on_change=_al_elegir,
        format_func=lambda i: (f"**{resultados[i]['nombre']}**"
                               + (f" · _{resultados[i]['tipo']}_" if resultados[i]["tipo"] else "")
                               + (f"  \n{resultados[i]['detalle']}" if resultados[i]["detalle"] else "")),
    )

# ---------------------------------------------------------------------------
# Enlace de Google Maps (incluye enlaces cortos maps.app.goo.gl)
# ---------------------------------------------------------------------------
HOSTS_GOOGLE = ("maps.app.goo.gl", "goo.gl", "g.co", "maps.google.com", "www.google.com", "google.com")


def coordenadas_de_texto(texto):
    """Extrae latitud y longitud de un texto o enlace de Google Maps."""
    t = unquote(texto)
    for patron in (r"!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)",          # punto exacto del lugar
                   r"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)",                # centro del mapa
                   r"[?&](?:q|query|ll|destination)=(-?\d{1,2}\.\d+),\s*(-?\d{1,3}\.\d+)",
                   r"(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})"):     # "18.47, -69.93"
        m = re.search(patron, t)
        if m:
            lat, lon = map(float, m.groups())
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
    return None


def expandir_enlace_google(enlace):
    """Sigue un enlace corto de Google Maps hasta la dirección completa (solo dominios de Google)."""
    host = (urlsplit(enlace).hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in HOSTS_GOOGLE):
        return enlace
    r = requests.get(enlace, headers={"User-Agent": "Mozilla/5.0"}, timeout=12, allow_redirects=True)
    finales = [x.url for x in r.history] + [r.url]
    return " ".join(finales) + " " + r.text[:20000]


st.subheader("🗺️ 2. O pega el enlace de Google Maps")
st.caption("En Google Maps busca el negocio, toca **Compartir** y copia el enlace "
           "(sirven los enlaces cortos `maps.app.goo.gl`). También puedes pegar coordenadas: `18.4861, -69.9312`.")
with st.form("enlace_google"):
    pegado = st.text_input("Enlace o coordenadas", placeholder="https://maps.app.goo.gl/…")
    usar = st.form_submit_button("Usar esta ubicación", use_container_width=True)
if usar and pegado.strip():
    coords = coordenadas_de_texto(pegado.strip())
    if coords is None and pegado.strip().startswith("http"):
        try:
            with st.spinner("Abriendo el enlace de Google Maps…"):
                coords = coordenadas_de_texto(expandir_enlace_google(pegado.strip()))
        except requests.RequestException:
            coords = None
    if coords:
        aplicar(*coords, "Enlace de Google Maps")
        st.rerun()
    else:
        st.warning("No se encontraron coordenadas en ese enlace. En Google Maps mantén pulsado el "
                   "punto exacto del negocio y copia los dos números que aparecen arriba.")

# ---------------------------------------------------------------------------
# GPS del dispositivo (estando en el establecimiento)
# ---------------------------------------------------------------------------
with st.expander("📡 3. O detecta tu ubicación actual (estando en el establecimiento)"):
    if st.button("📍 Detectar mi ubicación", use_container_width=True):
        st.session_state.geo_attempt += 1
        st.session_state.geo_detecting = True
    if st.session_state.geo_detecting:
        st.caption("Solicitando ubicación al navegador… Acepta el permiso cuando aparezca.")
        # El mismo componente que usa la Consulta Móvil (navigator.geolocation del navegador).
        from streamlit_js_eval import get_geolocation
        try:
            try:
                respuesta = get_geolocation(component_key=f"geo_admin_{st.session_state.geo_attempt}")
            except TypeError:
                respuesta = get_geolocation()
        except Exception as exc:
            st.session_state.geo_detecting = False
            respuesta = None
            st.error("No se pudo iniciar la solicitud de ubicación del navegador: " + type(exc).__name__)
        if isinstance(respuesta, dict) and respuesta.get("error"):
            ubic = {"error": respuesta["error"]}
        elif isinstance(respuesta, dict):
            ubic = respuesta.get("coords", respuesta)
        else:
            ubic = None
        if isinstance(ubic, dict) and ubic.get("latitude") is not None and ubic.get("longitude") is not None:
            try:
                lat, lon = float(ubic["latitude"]), float(ubic["longitude"])
                precision = float(ubic.get("accuracy") or 0)
                if not all(map(math.isfinite, (lat, lon))) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError
                st.session_state.geo_detecting = False
                st.session_state.geo_accuracy = precision
                aplicar(lat, lon, f"GPS de este dispositivo (±{precision:.0f} m)")
                st.rerun()
            except (ValueError, TypeError):
                st.error("El navegador devolvió coordenadas inválidas.")
        elif isinstance(ubic, dict) and ubic.get("error"):
            st.session_state.geo_detecting = False
            st.error("El navegador no pudo obtener la ubicación: " + str(ubic["error"])
                     + ". Revisa que la ubicación esté permitida para este sitio (candado de la barra de direcciones).")
        else:
            st.caption("Si no aparece el permiso, revisa los ajustes de ubicación del navegador.")

# ---------------------------------------------------------------------------
# Resultado: mapa con el radio autorizado, ajustes y guardar
# ---------------------------------------------------------------------------
st.divider()
st.subheader("✅ Ubicación y radio autorizado")
lat, lon = float(st.session_state.geo_form_lat), float(st.session_state.geo_form_lon)
if st.session_state.geo_origen:
    st.info("📍 Seleccionado: " + st.session_state.geo_origen)
if st.session_state.get("geo_accuracy", 0) > 50 and "GPS" in st.session_state.geo_origen:
    st.warning("Precisión GPS baja. Si puedes, usa la búsqueda por nombre o el enlace de Google Maps.")

st.number_input("Distancia máxima permitida (metros)", min_value=10, max_value=10000, step=10,
                key="geo_form_radius", help="Radio alrededor del establecimiento dentro del cual se permite consultar.")
radio = int(st.session_state.geo_form_radius)

if lat == 0 and lon == 0:
    st.info("Busca el establecimiento, pega un enlace o detecta tu ubicación para ver el mapa.")
else:
    # Mapa Leaflet: el círculo es la zona autorizada en metros reales y el acercamiento
    # se ajusta solo para que se vea completo.
    import json as _json
    import streamlit.components.v1 as _components
    otros = [r for r in resultados if (round(r["lat"], 6), round(r["lon"], 6)) != (round(lat, 6), round(lon, 6))]
    _datos = _json.dumps({"lat": lat, "lon": lon, "radio": radio,
                          "otros": [{"lat": r["lat"], "lon": r["lon"], "nombre": str(r.get("nombre", ""))[:80]}
                                    for r in otros[:20]]})
    _components.html("""
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<div id="mapa" style="height:400px;border-radius:12px;border:1px solid #e3eaf5"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  const d = """ + _datos + """;
  const mapa = L.map('mapa', { scrollWheelZoom: false }).setView([d.lat, d.lon], 16);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 19, attribution: '&copy; OpenStreetMap &copy; CARTO' }).addTo(mapa);
  const zona = L.circle([d.lat, d.lon], { radius: d.radio, color: '#0757d4', weight: 2,
                                         fillColor: '#0757d4', fillOpacity: 0.12 }).addTo(mapa);
  L.circleMarker([d.lat, d.lon], { radius: 7, color: '#ffffff', weight: 2, fillColor: '#dc2626',
                                   fillOpacity: 1 }).addTo(mapa).bindTooltip('Centro del establecimiento');
  d.otros.forEach(o => L.circleMarker([o.lat, o.lon], { radius: 5, color: '#ffffff', weight: 1,
      fillColor: '#64748b', fillOpacity: 0.9 }).addTo(mapa).bindTooltip(o.nombre));
  // Encuadrar la zona completa (el diámetro es 2 × radio).
  mapa.fitBounds(L.latLng(d.lat, d.lon).toBounds(d.radio * 2), { padding: [24, 24] });
</script>""", height=412)
    st.caption(f"🔴 Centro del establecimiento · 🔵 zona autorizada de {radio:,} m"
               + (" · ⚪ otros resultados de la búsqueda" if otros else ""))
    st.link_button("Ver este punto en Google Maps", f"https://www.google.com/maps?q={lat:.7f},{lon:.7f}",
                   use_container_width=True)

with st.expander("Ajuste fino de coordenadas"):
    st.number_input("Latitud", min_value=-90.0, max_value=90.0, step=0.000001, format="%.7f", key="geo_form_lat")
    st.number_input("Longitud", min_value=-180.0, max_value=180.0, step=0.000001, format="%.7f", key="geo_form_lon")

st.toggle("Exigir ubicación para Consulta Móvil", key="geo_form_enabled")

if st.button("💾 Guardar ubicación", type="primary", use_container_width=True):
    try:
        latitude, longitude = float(st.session_state.geo_form_lat), float(st.session_state.geo_form_lon)
        if latitude == 0 and longitude == 0:
            st.error("Selecciona primero la ubicación del establecimiento.")
        else:
            save_settings(latitude, longitude, st.session_state.geo_form_enabled, st.session_state.geo_form_radius)
            saved = get_settings()
            if (abs(float(saved["latitude"]) - latitude) > 1e-7 or abs(float(saved["longitude"]) - longitude) > 1e-7
                    or bool(saved["enabled"]) != bool(st.session_state.geo_form_enabled)
                    or int(saved["radius_m"]) != int(st.session_state.geo_form_radius)):
                st.error("Supabase no confirmó los valores guardados. Revisa la tabla mobile_geo_settings.")
            else:
                st.success(f"Ubicación guardada: {latitude:.7f}, {longitude:.7f} · radio {radio} m.")
    except Exception as exc:
        st.error("No se pudo guardar la ubicación en Supabase.")
        st.code(str(exc))


# ---------------- Acceso a la pantalla de Consulta de Precios ----------------
st.divider()
st.subheader("🔐 Acceso a la Consulta de Precios")
st.caption("Cómo entra el verificador a la app en línea. La zona es la misma de arriba.")
import acceso_verificador as _acceso
_actual = _acceso.modo()
_elegido = st.radio("Los verificadores entran…", list(_acceso.MODOS), index=list(_acceso.MODOS).index(_actual),
                    format_func=_acceso.MODOS.get, key="modo_acceso_verificador")
st.markdown(
    "- **Con usuario y contraseña:** como hasta ahora, con la cuenta del verificador.\n"
    "- **Por ubicación del local:** el equipo abre la app y, si está dentro de la zona autorizada, entra "
    "directo a la Consulta de Precios, **sin usuario**. Para salir sigue haciendo falta la clave de un administrador (✕).\n"
    "- **Cualquiera de los dos:** la pantalla de inicio de sesión muestra además el botón "
    "*📍 Entrar como verificador*.")
if _elegido != "usuario":
    _zona_activa = bool(st.session_state.get("geo_form_enabled"))
    if not _zona_activa:
        st.warning("Activa **Exigir ubicación** y guarda la ubicación de arriba: sin zona autorizada no se puede "
                   "entrar por ubicación (el verificador tendría que usar su usuario).")
    st.info("📌 **Personal de la tienda:** dentro del local, la app entrará como verificador. Para iniciar sesión "
            "con tu usuario usa la dirección **`/?personal=1`** (por ejemplo "
            "`https://verificadordeprecios.streamlit.app/?personal=1`), o el botón ✕ del verificador con la "
            "clave de administrador.")
    st.caption("⚠️ El equipo necesita ubicación activada. Muchos verificadores fijos (como el 2connect) no tienen GPS "
               "y ubican por Wi-Fi, con poca precisión: si no logra entrar, aumenta el radio o usa el acceso con "
               "usuario. La app sin internet (GitHub Pages) no pide usuario de todos modos.")
if st.button("💾 Guardar forma de acceso", use_container_width=True, disabled=_elegido == _actual):
    try:
        _acceso.guardar(_elegido)
        st.success("Forma de acceso guardada: " + _acceso.MODOS[_elegido] + ".")
    except Exception as exc:
        st.error("No se pudo guardar: " + str(exc))
