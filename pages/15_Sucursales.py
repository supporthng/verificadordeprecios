"""Sucursales: crear tiendas, su ubicación (acceso por ubicación) y su fuente de precios.

- El usuario general (sin sucursal asignada) crea y administra todas.
- El encargado de una sucursal solo ve la suya y elige su fuente de precios.
- Los inventarios se cargan y se identifican en Precios › Inventarios (Excel).
"""
import json
import math
import re

import streamlit as st
import streamlit.components.v1 as components

from auth_usuarios import current_user, es_admin, allowed
import sucursales as suc

usuario = current_user()
general = bool(usuario) and es_admin(usuario) and not usuario.get("must_change_password") and not usuario.get("sucursal_id")
encargado = bool(usuario) and usuario.get("sucursal_id") and allowed(usuario, "cargar_archivo")
if not (general or encargado):
    st.error("Acceso restringido.")
    st.stop()

st.title("🏬 Sucursales")

try:
    todas = suc.listar()
except RuntimeError:
    st.warning("Las sucursales todavía no están instaladas. En Supabase › **SQL Editor**, ejecuta "
               "**sql/MIGRACION_006_sucursales.sql** (una sola vez) y recarga esta página.")
    st.stop()

if general:
    st.caption("Cada sucursal **elige su fuente de precios**: la misma de la Principal, uno de los inventarios "
               "de **Precios › Inventarios (Excel)**, Google Drive / Sheets o SQL Server.")
for clave in ("aviso_sucursal",):
    if st.session_state.get(clave):
        st.toast(st.session_state.pop(clave), icon="✅")


def _mapa(puntos, alto=360):
    """Mapa con las sucursales y su zona. puntos: [{lat, lon, radio, nombre}]."""
    puntos = [p for p in puntos if p.get("lat") is not None and p.get("lon") is not None]
    if not puntos:
        return
    datos = json.dumps(puntos)
    components.html("""
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<div id="mapa" style="height:""" + str(alto) + """px;border-radius:12px;border:1px solid #e3eaf5"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  const puntos = """ + datos + """;
  const mapa = L.map('mapa', { scrollWheelZoom: false });
  let fallos = 0, cambiado = false;
  const calles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19,
    attribution: '&copy; OpenStreetMap' }).addTo(mapa);
  calles.on('tileerror', function () {
    if (cambiado || ++fallos < 3) return;
    cambiado = true; mapa.removeLayer(calles);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
      { maxZoom: 19, attribution: 'Mapa &copy; Esri' }).addTo(mapa);
  });
  let caja = null;
  puntos.forEach(p => {
    L.circle([p.lat, p.lon], { radius: p.radio, color: '#0757d4', weight: 2, fillColor: '#0757d4',
                               fillOpacity: 0.12 }).addTo(mapa);
    L.circleMarker([p.lat, p.lon], { radius: 7, color: '#fff', weight: 2, fillColor: '#dc2626', fillOpacity: 1 })
      .addTo(mapa).bindTooltip(p.nombre, { permanent: puntos.length > 1, direction: 'top' });
    const b = L.latLng(p.lat, p.lon).toBounds(p.radio * 2);
    caja = caja ? caja.extend(b) : b;
  });
  mapa.fitBounds(caja, { padding: [30, 30], maxZoom: 17 });
</script>""", height=alto + 12)


def _enviar_a_equipos():
    """Los equipos sin internet de las sucursales reciben los cambios (si ya están en uso)."""
    try:
        import publicar_equipos
        publicar_equipos.actualizar_si_publicado()
    except Exception:
        pass


def _coordenadas(texto):
    """Latitud y longitud de un enlace de Google Maps o de un texto «18.47, -69.93»."""
    texto = str(texto or "")
    for patron in (r"@(-?\d+\.\d+),(-?\d+\.\d+)", r"[?&](?:q|ll|query)=(-?\d+\.\d+),\s*(-?\d+\.\d+)",
                   r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", r"^\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*$"):
        m = re.search(patron, texto)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
    return None


def _editor_ubicacion(clave, datos, nombre, guardar_fn):
    """Ubicación con enlace de Maps, GPS o coordenadas. datos: {latitude, longitude, radius_m, geo_enabled}."""
    if st.session_state.get(clave + "_suc") != clave:
        st.session_state[clave + "_lat"] = float(datos.get("latitude") or 0)
        st.session_state[clave + "_lon"] = float(datos.get("longitude") or 0)
        st.session_state[clave + "_suc"] = clave
    c1, c2 = st.columns([2, 1])
    enlace = c1.text_input("Pega un enlace de Google Maps o «latitud, longitud»", key=clave + "_enlace")
    if enlace:
        punto = _coordenadas(enlace)
        if punto:
            st.session_state[clave + "_lat"], st.session_state[clave + "_lon"] = punto
        else:
            st.warning("No encontré coordenadas en ese texto. En Google Maps, mantén presionado el punto y copia "
                       "las coordenadas que aparecen (ej.: 18.4719, -69.9312).")
    if c2.button("📍 Usar mi ubicación actual", use_container_width=True, key=clave + "_btn"):
        st.session_state[clave + "_pedir"] = st.session_state.get(clave + "_pedir", 0) + 1
    if st.session_state.get(clave + "_pedir"):
        from streamlit_js_eval import get_geolocation
        try:
            respuesta = get_geolocation(component_key=f"{clave}_gps_{st.session_state[clave + '_pedir']}")
        except TypeError:
            respuesta = get_geolocation()
        coords = (respuesta or {}).get("coords", respuesta) if isinstance(respuesta, dict) else None
        if isinstance(coords, dict) and coords.get("latitude") is not None:
            st.session_state[clave + "_lat"] = float(coords["latitude"])
            st.session_state[clave + "_lon"] = float(coords["longitude"])
            st.session_state[clave + "_pedir"] = 0
            st.rerun()
        elif isinstance(respuesta, dict) and respuesta.get("error"):
            st.error("El navegador no pudo obtener la ubicación: " + str(respuesta["error"]))
            st.session_state[clave + "_pedir"] = 0
        else:
            st.caption("Solicitando la ubicación… acepta el permiso del navegador.")
    with st.form(clave + "_form"):
        f1, f2, f3 = st.columns(3)
        lat = f1.number_input("Latitud", -90.0, 90.0, step=0.000001, format="%.7f", key=clave + "_lat")
        lon = f2.number_input("Longitud", -180.0, 180.0, step=0.000001, format="%.7f", key=clave + "_lon")
        radio = f3.number_input("Radio (metros)", 10, 10000, value=int(datos.get("radius_m") or 100), step=10)
        activa_geo = st.toggle("Usar esta ubicación para el acceso por ubicación",
                               value=bool(datos.get("geo_enabled")))
        guardar_geo = st.form_submit_button("Guardar ubicación", type="primary")
    if guardar_geo:
        if activa_geo and lat == 0 and lon == 0:
            st.error("Primero indica la ubicación.")
        else:
            guardar_fn(lat, lon, int(radio), activa_geo)
            st.session_state.aviso_sucursal = "Ubicación guardada."
            st.rerun()
    if not (lat == 0 and lon == 0) and all(map(math.isfinite, (lat, lon))):
        _mapa([{"lat": lat, "lon": lon, "radio": int(radio), "nombre": nombre}])


# ====================================================================== la principal
# La tienda principal no es una fila de la tabla de sucursales: es el catálogo general, los equipos
# sin sucursal y la ubicación de «Ubicación y acceso». Se muestra aquí junto a las demás.
PRINCIPAL = "__principal__"


def _zona_principal():
    try:
        from mobile_geofence import get_settings
        return get_settings()
    except Exception:
        return None


zona_principal = _zona_principal()
NOMBRE_PRINCIPAL = suc.nombre_principal()


@st.cache_data(ttl=30, show_spinner=False)
def _inventarios():
    try:
        from inventarios import all_inventories
        return all_inventories()
    except Exception:
        return []


@st.cache_data(ttl=30, show_spinner=False)
def _fuente_principal():
    """('local'|'google'|'external', nombre del inventario activo o None)."""
    try:
        import publicar_equipos
        tipo = publicar_equipos.fuente_activa()
    except Exception:
        tipo = "local"
    activo = next((i["name"] for i in _inventarios() if i.get("is_active")), None)
    return tipo, activo


ETIQUETA_FUENTE = {"local": "Excel", "google": "Google Drive / Sheets", "external": "SQL Server"}


def _texto_fuente(f):
    """Nombre corto de la fuente de una sucursal (o de la Principal si f es None)."""
    if f is None or f["tipo"] == "principal":
        tipo, activo = _fuente_principal()
        texto = f"📚 {activo}" if tipo == "local" and activo else ETIQUETA_FUENTE.get(tipo, tipo)
        return texto if f is None else "Igual que la Principal (" + texto + ")"
    if f["tipo"] == "inventario":
        nombre = next((i["name"] for i in _inventarios() if int(i["id"]) == f["inventario_id"]), None)
        return f"📚 {nombre}" if nombre else "⚠️ Inventario borrado"
    if f["tipo"] == "google":
        g = f["google"] or {}
        return "☁️ " + (g.get("file_name") or "Google") + (f" › {g['sheet_name']}" if g.get("sheet_name") else "")
    c = next((x for x in _externas() if str(x["id"]) == f["external_id"]), None)
    return f"🔌 {c['name']}" if c else "⚠️ Configuración de SQL Server borrada"


@st.cache_data(ttl=30, show_spinner=False)
def _externas():
    """Configuraciones de SQL Server guardadas en SQL Server › Consulta externa."""
    try:
        return suc._api("GET", "external_price_sources",
                        {"select": "id,name,database,schema_name,table_name,enabled", "order": "name.asc"})
    except Exception:
        return []


def _adivinar(columnas, pistas):
    return next((i for i, c in enumerate(columnas) if any(p in str(c).lower() for p in pistas)), 0)


def _elegir_google(clave, actual):
    """Archivo, hoja y columnas de Google para la sucursal. Devuelve el dict o None si falta algo."""
    try:
        import google_oauth_source as g
        if g.faltantes():
            st.warning("Google no está configurado. Ve a **Precios › Google Drive / Sheets**.")
            return None
        cfg_p = g.config() or {}
        if not cfg_p.get("refresh_token_encrypted"):
            st.warning("Primero conecta la cuenta de Google en **Precios › Google Drive / Sheets**.")
            return None
        marca = str(cfg_p.get("refresh_token_encrypted", ""))[-16:]
    except Exception as exc:
        st.error(f"No se pudo usar Google: {exc}")
        return None
    actual = actual or {}
    tipos = {"sheets": "Google Sheets", "excel": "Excel (.xlsx) en Drive"}
    kind = st.radio("Tipo de archivo", list(tipos), horizontal=True, format_func=tipos.get, key=clave + "_kind",
                    index=list(tipos).index(actual.get("kind")) if actual.get("kind") in tipos else 0)
    buscar = st.text_input("Buscar archivo por nombre", key=clave + "_buscar")
    try:
        archivos = g.listar_archivos(kind, buscar, marca)
    except Exception as exc:
        st.error(f"No se pudieron listar los archivos de Drive: {exc}")
        return None
    if actual.get("file_id") and actual.get("kind") == kind and all(a["id"] != actual["file_id"] for a in archivos):
        archivos = [{"id": actual["file_id"], "name": actual.get("file_name") or actual["file_id"]}] + archivos
    if not archivos:
        st.info("No hay archivos de ese tipo en la cuenta de Google conectada.")
        return None
    ids = [a["id"] for a in archivos]
    nombres = {a["id"]: a["name"] for a in archivos}
    fid = st.selectbox("Archivo", ids, format_func=nombres.get, key=clave + "_file",
                       index=ids.index(actual["file_id"]) if actual.get("file_id") in ids else 0)
    try:
        hojas = g.pestanas(kind, fid)
    except Exception as exc:
        st.error(f"No se pudo abrir el archivo: {exc}")
        return None
    hoja = st.selectbox("Hoja", hojas, key=clave + "_hoja",
                        index=hojas.index(actual["sheet_name"]) if actual.get("sheet_name") in hojas else 0)
    try:
        columnas = [str(c) for c in g.read_file(kind, fid, hoja).columns]
    except Exception as exc:
        st.error(f"No se pudo leer la hoja: {exc}")
        return None
    if len(columnas) < 3:
        st.warning("La hoja necesita al menos tres columnas: código, nombre y precio.")
        return None

    def _col(etiqueta, campo, pistas):
        indice = columnas.index(actual[campo]) if actual.get(campo) in columnas else _adivinar(columnas, pistas)
        return st.selectbox(etiqueta, columnas, index=indice, key=f"{clave}_{campo}_{fid}_{hoja}")
    c1, c2, c3 = st.columns(3)
    with c1:
        codigo = _col("Código de barras", "code_column", ("codigo", "código", "barra", "barcode", "ean", "upc"))
    with c2:
        nombre = _col("Nombre", "name_column", ("nombre", "descrip", "producto", "name"))
    with c3:
        precio = _col("Precio", "price_column", ("precio", "price", "pvp"))
    if len({codigo, nombre, precio}) != 3:
        st.warning("Elige tres columnas distintas.")
        return None
    try:
        n = len(g.catalog(kind, fid, hoja, codigo, nombre, precio))
        st.caption(f"✅ {n:,} productos válidos en esa hoja.")
    except Exception as exc:
        st.warning(f"Con esas columnas no se encontraron productos válidos ({exc}).")
        return None
    return {"kind": kind, "file_id": fid, "file_name": nombres.get(fid, ""), "sheet_name": hoja,
            "code_column": codigo, "name_column": nombre, "price_column": precio}

# ====================================================================== lista (general)
if general:
    if todas:
        zp = zona_principal or {}
        filas = [{"Sucursal": "🏠 " + NOMBRE_PRINCIPAL, "Código": "—", "Estado": "✅ Activa",
                  "Ubicación": (f"📍 {zp.get('radius_m')} m" if zp.get("enabled") and zp.get("latitude") else "—"),
                  "Fuente de precios": _texto_fuente(None)}]
        for s in todas:
            filas.append({"Sucursal": s["nombre"], "Código": s["codigo"],
                          "Estado": "✅ Activa" if s["activa"] else "⏸️ Inactiva",
                          "Ubicación": (f"📍 {s['radius_m']} m" if s.get("geo_enabled") and s.get("latitude") is not None
                                        else "—"),
                          "Fuente de precios": _texto_fuente(suc.fuente(s))})
        st.dataframe(filas, hide_index=True, use_container_width=True)
        puntos = [{"lat": s.get("latitude"), "lon": s.get("longitude"), "radio": s["radius_m"], "nombre": s["nombre"]}
                  for s in todas if s.get("geo_enabled")]
        if zp.get("enabled") and zp.get("latitude"):
            puntos.insert(0, {"lat": zp["latitude"], "lon": zp["longitude"], "radio": zp["radius_m"],
                              "nombre": NOMBRE_PRINCIPAL})
        _mapa(puntos, alto=300)
    else:
        st.info("Todavía no hay sucursales. Crea la primera: mientras no haya ninguna, todo funciona como una sola tienda.")

    with st.expander("➕ Nueva sucursal", expanded=not todas):
        with st.form("nueva_sucursal", clear_on_submit=True):
            nombre_nueva = st.text_input("Nombre", placeholder="Ej.: Sucursal Centro", max_chars=80)
            codigo_nuevo = st.text_input("Código corto (opcional)", max_chars=30, placeholder="se arma solo: sucursal-centro",
                                         help="Identifica la sucursal en equipos e informes. Minúsculas, números y guiones.")
            crear = st.form_submit_button("Crear sucursal", type="primary")
        if crear:
            codigo = suc.codigo_desde_nombre(codigo_nuevo or nombre_nueva)
            if not nombre_nueva.strip():
                st.error("Escribe el nombre de la sucursal.")
            elif any(s["codigo"] == codigo for s in todas):
                st.error(f"Ya existe una sucursal con el código «{codigo}».")
            else:
                try:
                    suc.guardar({"nombre": nombre_nueva.strip(), "codigo": codigo, "activa": True})
                    _enviar_a_equipos()
                    st.session_state.aviso_sucursal = f"Sucursal «{nombre_nueva.strip()}» creada."
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
    if not todas:
        st.stop()
    elegida_id = st.selectbox("Administrar", [PRINCIPAL] + [s["id"] for s in todas],
                              format_func=lambda i: "🏠 " + NOMBRE_PRINCIPAL if i == PRINCIPAL
                              else "🏬 " + next(s["nombre"] for s in todas if s["id"] == i))
else:
    elegida_id = usuario["sucursal_id"]

if elegida_id == PRINCIPAL:
    st.subheader("🏠 " + NOMBRE_PRINCIPAL)
    tab_p, tab_u, tab_d = st.tabs(["💲 Fuente de precios", "📍 Ubicación", "⚙️ Datos"])
    with tab_p:
        st.markdown(f"La Principal usa la **fuente activa**: **{_texto_fuente(None)}**. Las sucursales que "
                    "eligen «Igual que la Principal» usan esta misma.")
        st.markdown("- Los **equipos sin internet** sin sucursal asignada son de la principal.\n"
                    "- En el **registro de consultas** aparece como «Principal».")
        c1, c2 = st.columns(2)
        with c1:
            st.page_link("pages/11_Seleccion_Fuentes.py", label="Fuente activa", icon="🎯")
        with c2:
            st.page_link("pages/10_Inventarios.py", label="Inventarios (Excel)", icon="📚")
    with tab_u:
        st.caption("Es la ubicación de **Ubicación y acceso**: la Consulta Móvil y el acceso por ubicación la usan "
                   "cuando el equipo no está dentro de ninguna sucursal.")
        if zona_principal is None:
            st.warning("No se pudo leer la ubicación de la principal. Revísala en **Ubicación y acceso**.")
        else:
            def _guardar_principal(lat, lon, radio, activa):
                from mobile_geofence import save_settings
                save_settings(lat, lon, enabled=activa, radius_m=radio)
            _editor_ubicacion("geo_principal", {**zona_principal, "geo_enabled": zona_principal.get("enabled")},
                              NOMBRE_PRINCIPAL, _guardar_principal)
        st.page_link("pages/9_Ubicacion_Movil.py", label="Más opciones (buscar el negocio por nombre)", icon="📍")
    with tab_d:
        with st.form("datos_principal"):
            nombre_p = st.text_input("Nombre", value="" if NOMBRE_PRINCIPAL == "Principal" else NOMBRE_PRINCIPAL,
                                     max_chars=80, placeholder="Ej.: Casa Matriz, Sucursal Renacimiento…")
            st.caption("Sale en la pantalla de consulta debajo del nombre del negocio (si en **Apariencia** está "
                       "activado «Mostrar el nombre de la sucursal debajo»), y en las listas e informes. "
                       "Vacío = «Principal», sin nombre en la pantalla.")
            if st.form_submit_button("Guardar", type="primary"):
                import apariencia
                apariencia.guardar({"nombre_principal": nombre_p.strip()})
                _enviar_a_equipos()
                st.session_state.aviso_sucursal = "Nombre de la Principal guardado."
                st.rerun()
        st.caption("La Principal no se puede borrar ni desactivar: es la tienda base del sistema.")
    st.stop()

sucursal = next((s for s in todas if s["id"] == elegida_id), None)
if not sucursal:
    st.error("Tu sucursal ya no existe. Pide al administrador que te asigne otra.")
    st.stop()

st.subheader(f"🏬 {sucursal['nombre']}")
pestanas = ["💲 Fuente de precios", "📍 Ubicación"] + (["⚙️ Datos"] if general else [])
tabs = st.tabs(pestanas)

# ====================================================================== fuente de precios
with tabs[0]:
    actual = suc.fuente(sucursal)
    st.markdown(f"Fuente actual: **{_texto_fuente(actual)}**")
    clave_f = f"fuente_{sucursal['id']}"
    tipos = {"principal": "🏠 Igual que la Principal (" + _texto_fuente(None) + ")",
             "inventario": "📚 Inventario independiente",
             "google": "☁️ Google Drive / Sheets",
             "external": "🔌 SQL Server (conector de Windows)"}
    tipo = st.radio("¿De dónde toma los precios esta sucursal?", list(tipos), format_func=tipos.get,
                    index=list(tipos).index(actual["tipo"]), key=clave_f + "_tipo")
    eleccion = {"tipo": tipo}
    listo = True
    if tipo == "inventario":
        inventarios = _inventarios()
        if not inventarios:
            st.info("Todavía no hay inventarios. Créalos y cárgalos en **Precios › Inventarios (Excel)**.")
            listo = False
        else:
            ids = [int(i["id"]) for i in inventarios]
            nombres_inv = {int(i["id"]): i["name"] + ("  · 🏠 lo usa la Principal" if i.get("is_active") else "")
                           for i in inventarios}
            eleccion["inventario_id"] = st.selectbox(
                "Inventario", ids, format_func=nombres_inv.get, key=clave_f + "_inv",
                index=ids.index(actual["inventario_id"]) if actual["inventario_id"] in ids else 0)
            st.caption("Los inventarios se crean, se cargan y se renombran en **Precios › Inventarios (Excel)**.")
    elif tipo == "google":
        actual_g = actual["google"]
        if not actual_g:   # para empezar, el mismo archivo de la Principal (si tiene)
            try:
                import google_oauth_source as _g
                actual_g = {k: (_g.config() or {}).get(k) for k in suc.CAMPOS_GOOGLE}
            except Exception:
                actual_g = None
        eleccion["google"] = _elegir_google(clave_f + "_g", actual_g)
        listo = eleccion["google"] is not None
    elif tipo == "external":
        externas = _externas()
        if not externas:
            st.info("Todavía no hay configuraciones de SQL Server. Créalas en **SQL Server › Consulta externa** "
                    "(base de datos, tabla y columnas).")
            listo = False
        else:
            ids = [str(x["id"]) for x in externas]
            def _nombre_ext(i):
                x = next(e for e in externas if str(e["id"]) == i)
                return (f"{x['name']} — {x['database']} / {x['schema_name']}.{x['table_name']}"
                        + ("  · 🏠 la usa la Principal" if x.get("enabled") else ""))
            eleccion["external_id"] = st.selectbox(
                "Base de datos y tabla", ids, format_func=_nombre_ext, key=clave_f + "_ext",
                index=ids.index(actual["external_id"]) if actual["external_id"] in ids else 0)
            st.caption("Las bases y tablas se configuran en **SQL Server › Consulta externa**. Para que esta "
                       "sucursal las use, el conector de Windows debe ser la **versión 6** y estar encendido.")
    if st.button("Guardar fuente", type="primary", disabled=not listo, key=clave_f + "_guardar"):
        with st.spinner("Guardando y enviando a los equipos de la sucursal…"):
            suc.guardar_fuente(sucursal, tipo, eleccion.get("inventario_id"), eleccion.get("google"),
                               eleccion.get("external_id"))
            _inventarios.clear()
            _enviar_a_equipos()
        nuevo = suc.fuente({"excepciones_config": {"fuente": tipo, **{k: v for k, v in eleccion.items() if k != "tipo"}}})
        st.session_state.aviso_sucursal = f"{sucursal['nombre']} ahora usa: {_texto_fuente(nuevo)}."
        st.rerun()

# ====================================================================== ubicación
with tabs[1]:
    st.caption("Con la ubicación activa, un equipo que entra a la Consulta de Precios **por ubicación** queda "
               "en la sucursal en cuya zona está, y muestra los precios de su fuente.")
    if not general:
        if sucursal.get("geo_enabled") and sucursal.get("latitude") is not None:
            _mapa([{"lat": sucursal["latitude"], "lon": sucursal["longitude"], "radio": sucursal["radius_m"],
                    "nombre": sucursal["nombre"]}])
        else:
            st.info("Esta sucursal todavía no tiene ubicación. La configura el administrador general.")
    else:
        _editor_ubicacion(f"geo_{sucursal['id']}", sucursal, sucursal["nombre"],
                          lambda lat, lon, radio, activa: suc.guardar(
                              {"latitude": lat, "longitude": lon, "radius_m": radio, "geo_enabled": activa},
                              sucursal["id"]))

# ====================================================================== datos (general)
if general:
    with tabs[2]:
        with st.form(f"datos_{sucursal['id']}"):
            nombre = st.text_input("Nombre", value=sucursal["nombre"], max_chars=80)
            activa = st.toggle("Sucursal activa", value=bool(sucursal["activa"]),
                               help="Inactiva: no se asigna por ubicación.")
            st.caption(f"Código: `{sucursal['codigo']}` (no cambia: lo usan los equipos y los informes).")
            if st.form_submit_button("Guardar", type="primary"):
                suc.guardar({"nombre": nombre.strip() or sucursal["nombre"], "activa": activa}, sucursal["id"])
                _enviar_a_equipos()
                st.session_state.aviso_sucursal = "Sucursal guardada."
                st.rerun()
        with st.expander("🗑️ Eliminar sucursal"):
            st.warning("Sus inventarios no se borran. Si tiene usuarios, primero pásalos a otra sucursal o "
                       "elimínalos en Usuarios. El registro de consultas se conserva.")
            ok = st.checkbox(f"Confirmo que quiero eliminar «{sucursal['nombre']}»", key=f"del_{sucursal['id']}")
            if st.button("Eliminar", disabled=not ok, key=f"delb_{sucursal['id']}"):
                try:
                    suc.eliminar(sucursal["id"])
                    _enviar_a_equipos()
                    st.session_state.aviso_sucursal = "Sucursal eliminada."
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
