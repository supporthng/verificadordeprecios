"""Sucursales: crear tiendas, su ubicación (acceso por ubicación) y sus precios propios.

- El usuario general (sin sucursal asignada) crea y administra todas.
- El encargado de una sucursal solo ve la suya y carga sus precios propios.
"""
import io
import json
import math
import re

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from auth_usuarios import current_user, es_admin, allowed
import sucursales as suc
from shared import normalize_header

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
    st.caption("El catálogo general (tu fuente de precios activa) vale para todas las sucursales. Cada sucursal "
               "puede tener **precios propios**: mandan sobre el general solo en esa sucursal.")
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


# ====================================================================== lista (general)
if general:
    if todas:
        filas = []
        for s in todas:
            try:
                n = suc.contar_excepciones(s["id"])
            except Exception:
                n = None
            filas.append({"Sucursal": s["nombre"], "Código": s["codigo"],
                          "Estado": "✅ Activa" if s["activa"] else "⏸️ Inactiva",
                          "Ubicación": (f"📍 {s['radius_m']} m" if s.get("geo_enabled") and s.get("latitude") is not None
                                        else "—"),
                          "Precios propios": n})
        st.dataframe(filas, hide_index=True, use_container_width=True)
        _mapa([{"lat": s.get("latitude"), "lon": s.get("longitude"), "radio": s["radius_m"], "nombre": s["nombre"]}
               for s in todas if s.get("geo_enabled")], alto=300)
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
    elegida_id = st.selectbox("Administrar", [s["id"] for s in todas],
                              format_func=lambda i: next(s["nombre"] for s in todas if s["id"] == i))
else:
    elegida_id = usuario["sucursal_id"]

sucursal = next((s for s in todas if s["id"] == elegida_id), None)
if not sucursal:
    st.error("Tu sucursal ya no existe. Pide al administrador que te asigne otra.")
    st.stop()

st.subheader(f"🏬 {sucursal['nombre']}")
pestanas = ["💲 Precios propios", "📍 Ubicación"] + (["⚙️ Datos"] if general else [])
tabs = st.tabs(pestanas)

# ====================================================================== precios propios
with tabs[0]:
    try:
        cantidad = suc.contar_excepciones(sucursal["id"])
    except Exception:
        cantidad = 0
    st.markdown(f"Esta sucursal tiene **{cantidad:,}** precio(s) propio(s). Para cualquier otro producto se usa "
                "el precio del catálogo general.")
    st.caption("Sube un Excel o CSV con **código de barras** y **precio** (y, si quieres, **nombre** para productos "
               "que solo vende esta sucursal). Al publicar, la lista **reemplaza** a la anterior completa.")
    archivo = st.file_uploader("Archivo de precios propios", type=["xlsx", "csv"], key=f"exc_{sucursal['id']}")
    if archivo is not None:
        try:
            if archivo.name.lower().endswith(".csv"):
                df = pd.read_csv(archivo, dtype=str, sep=None, engine="python")
            else:
                crudo = pd.read_excel(archivo, header=None, dtype=str, engine="openpyxl")
                claves = ("codigobarra", "codigobarras", "barcode", "codigo", "upc", "ean")
                fila = next((i for i, r in crudo.head(40).iterrows()
                             if any(normalize_header(x) in claves for x in r)), 0)
                archivo.seek(0)
                df = pd.read_excel(archivo, header=fila, dtype=str, engine="openpyxl")
            cols = [str(c) for c in df.columns]
            df.columns = cols

            def _idx(opciones, defecto=0):
                return next((i for i, x in enumerate(cols) if normalize_header(x) in opciones), defecto)

            c1, c2, c3 = st.columns(3)
            col_cod = c1.selectbox("Código de barras", cols, index=_idx(("codigobarra", "codigobarras", "barcode",
                                                                         "codigo", "upc", "ean")))
            col_pre = c2.selectbox("Precio", cols, index=_idx(("precio", "precioventa", "price"), min(1, len(cols) - 1)))
            col_nom = c3.selectbox("Nombre (opcional)", ["(sin nombre)"] + cols,
                                   index=1 + _idx(("nombre", "descripcion", "producto", "nombredelproducto"), -1)
                                   if any(normalize_header(x) in ("nombre", "descripcion", "producto", "nombredelproducto")
                                          for x in cols) else 0)
            datos = pd.DataFrame({
                "barcode": df[col_cod].astype(str).str.strip().str.replace(r"\.0$", "", regex=True),
                "price": pd.to_numeric(df[col_pre].astype(str).str.replace(",", "", regex=False)
                                       .str.replace("RD$", "", regex=False).str.strip(), errors="coerce"),
                "name": df[col_nom].astype(str).str.strip() if col_nom != "(sin nombre)" else None,
            })
            datos = datos[datos["barcode"].str.len().between(1, 64)
                          & ~datos["barcode"].str.upper().isin(["NAN", "NONE", "N/D", ""])
                          & datos["price"].notna() & (datos["price"] >= 0)]
            if "name" in datos:
                datos["name"] = datos["name"].where(~datos["name"].isin(["nan", "None", ""]), None)
            datos = datos.drop_duplicates("barcode", keep="last")
            st.write(f"Precios válidos: **{len(datos):,}**")
            st.dataframe(datos.head(30), hide_index=True, use_container_width=True)
            confirmar = st.checkbox(f"Confirmo que esta lista reemplaza los precios propios de {sucursal['nombre']}",
                                    key=f"conf_{sucursal['id']}")
            if st.button("Publicar precios propios", type="primary", disabled=not confirmar or datos.empty,
                         key=f"pub_{sucursal['id']}"):
                with st.spinner("Guardando y enviando a los equipos…"):
                    n = suc.reemplazar_excepciones(sucursal["id"], datos.to_dict("records"))
                    _enviar_a_equipos()
                st.session_state.aviso_sucursal = f"{n:,} precios propios publicados para {sucursal['nombre']}."
                st.rerun()
        except Exception as exc:
            st.error(f"No se pudo leer el archivo: {exc}")

    if cantidad:
        with st.expander("Ver o descargar los precios propios actuales"):
            actuales = pd.DataFrame(suc.listar_excepciones(sucursal["id"]))
            buscar = st.text_input("Buscar por código o nombre", key=f"bus_{sucursal['id']}").strip().lower()
            vista = actuales
            if buscar:
                vista = actuales[actuales["barcode"].str.contains(buscar, regex=False)
                                 | actuales["name"].fillna("").str.lower().str.contains(buscar, regex=False)]
            st.dataframe(vista.rename(columns={"barcode": "Código", "name": "Nombre", "price": "Precio"}),
                         hide_index=True, use_container_width=True)
            salida = io.StringIO()
            actuales.assign(barcode=actuales["barcode"].map(lambda c: f'="{c}"')).rename(
                columns={"barcode": "codigo", "name": "nombre", "price": "precio"}).to_csv(salida, index=False)
            st.download_button("⬇️ Descargar (Excel / CSV)", salida.getvalue().encode("utf-8-sig"),
                               file_name=f"precios_{sucursal['codigo']}.csv", mime="text/csv")
            if general and st.button("🗑️ Quitar todos los precios propios", key=f"vaciar_{sucursal['id']}"):
                suc.reemplazar_excepciones(sucursal["id"], [])
                _enviar_a_equipos()
                st.session_state.aviso_sucursal = "Precios propios quitados: la sucursal usa el catálogo general."
                st.rerun()

# ====================================================================== ubicación
with tabs[1]:
    st.caption("Con la ubicación activa, un equipo que entra a la Consulta de Precios **por ubicación** queda "
               "en la sucursal en cuya zona está, y muestra sus precios propios.")
    if not general:
        if sucursal.get("geo_enabled") and sucursal.get("latitude") is not None:
            _mapa([{"lat": sucursal["latitude"], "lon": sucursal["longitude"], "radio": sucursal["radius_m"],
                    "nombre": sucursal["nombre"]}])
        else:
            st.info("Esta sucursal todavía no tiene ubicación. La configura el administrador general.")
    else:
        clave = f"geo_{sucursal['id']}"
        if st.session_state.get(clave + "_suc") != sucursal["id"]:
            st.session_state[clave + "_lat"] = float(sucursal.get("latitude") or 0)
            st.session_state[clave + "_lon"] = float(sucursal.get("longitude") or 0)
            st.session_state[clave + "_suc"] = sucursal["id"]
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
            radio = f3.number_input("Radio (metros)", 10, 10000, value=int(sucursal["radius_m"]), step=10)
            activa_geo = st.toggle("Usar esta ubicación para el acceso por ubicación",
                                   value=bool(sucursal.get("geo_enabled")))
            guardar_geo = st.form_submit_button("Guardar ubicación", type="primary")
        if guardar_geo:
            if activa_geo and lat == 0 and lon == 0:
                st.error("Primero indica la ubicación de la sucursal.")
            else:
                suc.guardar({"latitude": lat, "longitude": lon, "radius_m": int(radio), "geo_enabled": activa_geo},
                            sucursal["id"])
                st.session_state.aviso_sucursal = "Ubicación guardada."
                st.rerun()
        if not (lat == 0 and lon == 0) and all(map(math.isfinite, (lat, lon))):
            _mapa([{"lat": lat, "lon": lon, "radio": int(radio), "nombre": sucursal["nombre"]}])

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
            st.warning("Se borran sus precios propios. Si tiene usuarios, primero pásalos a otra sucursal o "
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
