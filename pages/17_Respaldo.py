"""Respaldo y restauración: descargar una copia de todo el sistema y volver a cargarla."""
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from auth_usuarios import current_user, es_admin
import respaldo

usuario = current_user()
if not (usuario and es_admin(usuario) and not usuario.get("sucursal_id") and not usuario.get("must_change_password")):
    st.error("Solo el administrador general puede hacer respaldos.")
    st.stop()

ZONA = ZoneInfo("America/Santo_Domingo")
st.title("💾 Respaldo y restauración")
st.caption("Una copia de todo el sistema: inventarios y productos, sucursales, usuarios, fuentes de precios "
           "(Google, SQL Server), ubicación, apariencia, logo, QR y fotos de productos.")

for clave in ("aviso_respaldo",):
    if st.session_state.get(clave):
        st.success(st.session_state.pop(clave))


def _fecha(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(ZONA).strftime("%d/%m/%Y %I:%M %p")
    except (TypeError, ValueError):
        return "—"


def _tamano(n):
    n = int(n or 0)
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{max(1, round(n / 1024))} KB"


tab_crear, tab_nube, tab_restaurar = st.tabs(["⬇️ Crear respaldo", "☁️ Respaldos automáticos", "♻️ Restaurar"])

# ====================================================================== crear
with tab_crear:
    st.markdown("Descarga un archivo **.zip** con todo y guárdalo fuera de la plataforma (tu PC, un pendrive, "
                "Google Drive). Con él puedes recuperar el sistema si algo se borra o sale mal.")
    c1, c2 = st.columns(2)
    con_fotos = c1.toggle("Incluir las fotos de productos", value=True,
                          help="Las subidas a mano y las encontradas en internet. Sin ellas el archivo pesa menos.")
    con_registro = c2.toggle("Incluir el registro de consultas", value=False,
                             help="Todas las consultas hechas. Puede ser grande.")
    guardar_nube = st.checkbox("Guardar también una copia en la nube (Respaldos automáticos)", value=True)
    if st.button("Crear respaldo ahora", type="primary"):
        estado = st.status("Creando el respaldo…", expanded=True)
        try:
            datos, manifest = respaldo.crear(con_registro, con_fotos, progreso=estado.write)
            nombre = respaldo.nombre_archivo(manifest)
            if guardar_nube:
                respaldo.guardar_en_la_nube(datos, manifest, "manual")
            estado.update(label=f"Respaldo listo · {_tamano(len(datos))}", state="complete", expanded=False)
            st.session_state["respaldo_listo"] = (nombre, datos, manifest)
        except Exception as exc:
            estado.update(label="No se pudo crear el respaldo", state="error")
            st.error(str(exc))
    listo = st.session_state.get("respaldo_listo")
    if listo:
        nombre, datos, manifest = listo
        st.download_button(f"⬇️ Descargar {nombre}", datos, file_name=nombre, mime="application/zip",
                           type="primary", use_container_width=True)
        st.caption("Contiene: " + ", ".join(f"{n:,} {t}" for t, n in manifest["tablas"].items())
                   + f", {manifest['archivos']} archivo(s).")
    st.warning("🔐 Guarda el respaldo en un lugar seguro: incluye los usuarios (con sus claves cifradas) y la "
               "conexión a Google. No lo compartas.")

# ====================================================================== nube
with tab_nube:
    st.markdown("Cada día se guarda **un respaldo automático** en la nube del sistema (sin el registro de "
                "consultas). Se conservan los últimos **14**. También aparecen aquí los que creas a mano con "
                "«Guardar también una copia en la nube».")
    st.caption("Los automáticos los hace la revisión de GitHub (la misma que mantiene al día los equipos sin "
               "internet); si no tienes configurado el secreto STREAMLIT_SECRETS en GitHub, crea respaldos a mano.")
    try:
        lista = respaldo.automaticos()
    except Exception as exc:
        lista = []
        st.error(f"No se pudo leer la lista: {exc}")
    if not lista:
        st.info("Todavía no hay respaldos guardados en la nube.")
    for nombre, tamano, fecha in lista[:30]:
        c1, c2, c3 = st.columns([3, 1, 1.4])
        tipo = "Automático" if nombre.startswith("auto-") else "Manual"
        c1.markdown(f"**{tipo}** · {_fecha(fecha)}  \n`{nombre}`")
        c2.caption(_tamano(tamano))
        if c3.button("Preparar descarga", key=f"prep_{nombre}", use_container_width=True):
            st.session_state[f"nube_{nombre}"] = respaldo.descargar_automatico(nombre)
        if st.session_state.get(f"nube_{nombre}"):
            c3.download_button("⬇️ Descargar", st.session_state[f"nube_{nombre}"], file_name=nombre,
                               mime="application/zip", key=f"dl_{nombre}", use_container_width=True)

# ====================================================================== restaurar
with tab_restaurar:
    st.markdown("Vuelve a cargar un respaldo. Lo que está en el respaldo **reemplaza** a lo actual; lo que no "
                "está en el respaldo se deja como está.")
    origenes = {"archivo": "Un archivo de mi computadora", "nube": "Un respaldo de la nube"}
    origen = st.radio("Respaldo a restaurar", list(origenes), format_func=origenes.get, horizontal=True)
    datos = None
    if origen == "archivo":
        subido = st.file_uploader("Archivo de respaldo (.zip)", type="zip")
        if subido is not None:
            datos = subido.getvalue()
    else:
        try:
            lista = respaldo.automaticos()
        except Exception:
            lista = []
        if lista:
            elegido = st.selectbox("Respaldo", [x[0] for x in lista],
                                   format_func=lambda n: f"{_fecha(next(x[2] for x in lista if x[0] == n))} · {n}")
            if st.button("Abrir este respaldo"):
                st.session_state["restaurar_nube"] = (elegido, respaldo.descargar_automatico(elegido))
            if st.session_state.get("restaurar_nube", (None,))[0] == elegido:
                datos = st.session_state["restaurar_nube"][1]
        else:
            st.info("Todavía no hay respaldos en la nube.")

    if datos:
        try:
            manifest, tablas, archivos = respaldo.leer(datos)
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
        st.success(f"Respaldo del **{_fecha(manifest['creado'])}**.")
        partes = respaldo.resumen(manifest, tablas, archivos)
        st.dataframe([{k: v for k, v in p.items() if k != "clave"} for p in partes], hide_index=True,
                     use_container_width=True)
        elegidas = st.multiselect("Qué restaurar", [p["clave"] for p in partes],
                                  default=[p["clave"] for p in partes if p["clave"] != "registro"],
                                  format_func=lambda c: respaldo.PARTES[c][0])
        if "usuarios" in elegidas:
            st.caption("👥 Los usuarios vuelven con la clave que tenían en el respaldo.")
        st.warning("Antes de restaurar se guarda automáticamente una copia del estado actual en la nube, "
                   "por si necesitas volver atrás.")
        confirma = st.text_input("Para confirmar, escribe RESTAURAR")
        if st.button("♻️ Restaurar", type="primary", disabled=confirma.strip().upper() != "RESTAURAR" or not elegidas):
            estado = st.status("Restaurando…", expanded=True)
            try:
                estado.write("Guardando una copia del estado actual…")
                previo, m_previo = respaldo.crear(incluir_registro=False, incluir_fotos=True)
                copia = respaldo.guardar_en_la_nube(previo, m_previo, "antes-de-restaurar")
                hecho = respaldo.restaurar(datos, set(elegidas), progreso=estado.write)
                estado.update(label="Restauración terminada", state="complete", expanded=False)
                st.cache_data.clear()
                st.session_state["aviso_respaldo"] = ("Restaurado: " + "; ".join(hecho)
                                                      + f". Copia previa guardada como {copia}.")
                st.session_state.pop("restaurar_nube", None)
                st.rerun()
            except Exception as exc:
                estado.update(label="La restauración no terminó", state="error")
                st.error(f"{exc}. Si quedó a medias, puedes restaurar la copia previa desde «Un respaldo de la nube».")
