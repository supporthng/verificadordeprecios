"""Apariencia de la pantalla lectora: nombre del negocio, estilo, colores, textos,
logo, código QR y fotos de productos, con vista previa a la resolución de cada equipo."""
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st
import streamlit.components.v1 as components
from PIL import UnidentifiedImageError

from auth_usuarios import require
import apariencia
import imagenes_negocio as img
import vista_previa

require("logo")
st.title("🎨 Apariencia de la pantalla lectora")
st.caption("Todo lo que ve el cliente en el verificador se administra aquí. Los cambios llegan a las "
           "pantallas en línea en segundos y a los equipos sin internet cuando tengan conexión.")

try:
    img.conexion()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

if "ap_marca_img" not in st.session_state:
    st.session_state.ap_marca_img = 0


def _imagenes():
    return img.imagenes_actuales(st.session_state.ap_marca_img)


def _imagenes_cambiaron():
    st.session_state.ap_marca_img += 1


def _aviso_publicacion(resultado):
    ok, res = resultado
    if ok:
        st.caption("📴 También se envió a los equipos sin internet.")
    elif isinstance(res, str):
        st.warning("No se pudo enviar a los equipos sin internet: " + res)


for clave in ("aviso_apariencia", "aviso_logo", "aviso_qr"):
    if st.session_state.get(clave):
        st.toast(st.session_state.pop(clave), icon="✅")

guardada = apariencia.obtener()
CAMPOS = list(apariencia.PREDETERMINADA)
# Los controles arrancan con lo guardado; "Descartar cambios" los vuelve a poner así.
recargar = st.session_state.pop("ap_descartar", False)
for campo in CAMPOS:
    if recargar or ("ap_" + campo) not in st.session_state:
        st.session_state["ap_" + campo] = guardada[campo]

pestana_pantalla, pestana_logo, pestana_qr, pestana_fotos = st.tabs(
    ["🖥️ Pantalla", "🖼️ Logo", "📱 Código QR", "📷 Fotos de productos"])

# ====================================================================== PANTALLA
with pestana_pantalla:
    col_ajustes, col_vista = st.columns([1, 1.55], gap="large")

    with col_ajustes:
        st.text_input("Nombre del negocio", key="ap_nombre_negocio", max_chars=60,
                      placeholder="Ej.: Supermercado La Esquina")
        st.toggle("Mostrar el nombre en la pantalla", key="ap_mostrar_nombre")
        st.radio("Estilo de la pantalla", list(apariencia.ESTILOS), key="ap_estilo",
                 format_func=lambda k: apariencia.ESTILOS[k][0],
                 captions=[d for _, d in apariencia.ESTILOS.values()])
        st.color_picker("Color del negocio", key="ap_color_marca",
                        help="Se usa en el precio, la barra de tiempo y el fondo de los estilos "
                             "«Color del negocio» y «Panel lateral». Si un color no se lee bien sobre el "
                             "fondo, la pantalla lo oscurece o aclara sola.")
        es_panel = st.session_state.ap_estilo == "panel"
        st.radio("Logo", list(apariencia.POSICIONES_LOGO), key="ap_posicion_logo", horizontal=True,
                 format_func=apariencia.POSICIONES_LOGO.get, disabled=es_panel,
                 help="En el estilo «Panel lateral» el logo va siempre en el panel.")
        with st.expander("✏️ Textos de la pantalla"):
            st.text_input("Mensaje principal", key="ap_titulo_espera", max_chars=60)
            st.text_input("Indicación debajo", key="ap_mensaje_espera", max_chars=90)
            st.text_input("Texto junto al QR", key="ap_texto_qr", max_chars=60)
            st.text_input("Moneda", key="ap_moneda", max_chars=6)
            st.caption("Si dejas un texto vacío, se usa el de siempre.")
        st.markdown("**Qué se muestra**")
        st.toggle("Logo del negocio", key="ap_mostrar_logo")
        st.toggle("Código QR de Consulta Móvil", key="ap_mostrar_qr")
        st.toggle("Foto del producto junto al precio", key="ap_mostrar_foto",
                  help="Si el producto tiene foto (subida a mano o encontrada en internet).")
        st.toggle("Cuadro donde se escribe el código", key="ap_mostrar_cuadro",
                  help="Visible u oculto, el cuadro siempre está activo y con el cursor: el escáner "
                       "lee igual. Mostrarlo sirve para escribir el código a mano con un teclado.")

    elegida = apariencia.normalizar({c: st.session_state["ap_" + c] for c in CAMPOS})
    hay_cambios = elegida != guardada
    logo, qr = _imagenes()

    with col_vista:
        c1, c2 = st.columns([1.3, 1])
        resolucion = c1.selectbox("Ver en", list(vista_previa.RESOLUCIONES), key="ap_resolucion")
        pantalla = c2.segmented_control("Pantalla", list(vista_previa.PANTALLAS), key="ap_pantalla",
                                        format_func=vista_previa.PANTALLAS.get, default="espera")
        pantalla = pantalla or "espera"
        ancho, alto = vista_previa.RESOLUCIONES[resolucion]
        html, altura = vista_previa.componente(
            [{"apariencia": elegida, "pantalla": pantalla, "ancho": ancho, "alto": alto}],
            logo=logo, qr=qr, alto_max=440 if alto > ancho else 400)
        components.html(html, height=altura)
        avisos = []
        if elegida["mostrar_logo"] and not logo:
            avisos.append("todavía no hay logo (súbelo en la pestaña **Logo**)")
        if elegida["mostrar_qr"] and not qr:
            avisos.append("todavía no hay código QR (créalo en la pestaña **Código QR**)")
        if avisos:
            st.caption("ℹ️ No aparece en la vista previa porque " + " y ".join(avisos) + ".")
        st.caption("📐 La pantalla se acomoda sola a cualquier tamaño y orientación: cambia «Ver en» "
                   "para revisarla en cada equipo.")

        b1, b2 = st.columns(2)
        if b1.button("💾 Guardar apariencia", type="primary", use_container_width=True,
                     disabled=not hay_cambios):
            try:
                apariencia.guardar(elegida)
                st.session_state.aviso_apariencia = "Apariencia guardada. Las pantallas la aplicarán en segundos."
                import publicar_equipos
                ok, res = publicar_equipos.actualizar_si_publicado()
                if not ok and isinstance(res, str):
                    st.session_state.aviso_apariencia += " (No se pudo enviar a los equipos sin internet: " + res + ")"
                st.rerun()
            except Exception as exc:
                st.error("No se pudo guardar la apariencia: " + str(exc))
        if b2.button("↩️ Descartar cambios", use_container_width=True, disabled=not hay_cambios):
            st.session_state.ap_descartar = True
            st.rerun()
        if hay_cambios:
            st.info("Tienes cambios sin guardar: la vista previa los muestra, pero los equipos todavía no.")

    with st.expander("🧩 Comparar los estilos con tu logo y tus colores"):
        vistas = [{"apariencia": {**elegida, "estilo": k}, "pantalla": pantalla, "ancho": ancho,
                   "alto": alto, "titulo": nombre} for k, (nombre, _) in apariencia.ESTILOS.items()]
        html, altura = vista_previa.componente(vistas, logo=logo, qr=qr, columnas=3,
                                               alto_max=300 if alto > ancho else 190)
        components.html(html, height=altura)
        st.caption("Para usar uno, elígelo en «Estilo de la pantalla» y guarda.")

# ====================================================================== LOGO
with pestana_logo:
    logo, _ = _imagenes()
    col_actual, col_subir = st.columns([1, 1.4], gap="large")
    with col_actual:
        st.markdown("**Logo actual**")
        if logo:
            st.image(logo, width=260)
            if st.button("🗑️ Quitar logo", key="quitar_logo",
                         help="La pantalla mostrará solo el nombre del negocio."):
                try:
                    _aviso_publicacion(img.quitar_logo())
                    _imagenes_cambiaron()
                    st.session_state.aviso_logo = "Logo quitado."
                    st.rerun()
                except (RuntimeError, requests.RequestException) as exc:
                    st.error(str(exc))
        else:
            st.info("Todavía no hay logo. Mientras tanto, la pantalla muestra el nombre del negocio.")
    with col_subir:
        st.markdown("**Subir un logo nuevo**")
        st.caption("PNG con fondo transparente se ve mejor. En los estilos oscuros o de color, "
                   "el logo se pone sobre una tarjeta blanca para que siempre se lea.")
        archivo = st.file_uploader("Logo JPG o PNG", type=["jpg", "jpeg", "png"], key="archivo_logo")
        if archivo is not None:
            try:
                logo_png = img.preparar_logo(archivo)
                st.image(logo_png, caption="Vista previa", width=260)
                if st.button("Guardar logo", type="primary", key="guardar_logo"):
                    try:
                        resultado = img.guardar_logo(logo_png)
                        _imagenes_cambiaron()
                        st.session_state.aviso_logo = "Logo guardado. Aparecerá en las pantallas en menos de un minuto."
                        if resultado[0]:
                            st.session_state.aviso_logo += " También se envió a los equipos sin internet."
                        st.rerun()
                    except (RuntimeError, requests.RequestException) as exc:
                        st.error(f"No se pudo guardar el logo: {exc}")
            except (UnidentifiedImageError, OSError, ValueError):
                st.error("La imagen no es válida. Usa un archivo JPG o PNG.")

# ====================================================================== CÓDIGO QR
with pestana_qr:
    _, qr = _imagenes()
    st.markdown("Los clientes lo escanean con su celular para consultar precios desde el pasillo.")
    col_actual, col_crear = st.columns([1, 1.4], gap="large")
    with col_actual:
        st.markdown("**QR actual**")
        if qr:
            info = img.leer_info_qr()
            enlace = img.leer_enlace_qr(qr) or info.get("enlace")
            st.image(qr, width=180)
            origen = {"generado": "⚙️ Generado automáticamente",
                      "subido": "🖼️ Imagen subida manualmente"}.get(info.get("origen"), "❔ Origen desconocido")
            st.markdown(f"**Origen:** {origen}")
            if info.get("fecha"):
                try:
                    fecha = datetime.fromisoformat(info["fecha"]).astimezone(ZoneInfo("America/Santo_Domingo"))
                    st.markdown(f"**Guardado:** {fecha:%d/%m/%Y %H:%M}")
                except ValueError:
                    pass
            if enlace:
                st.markdown(f"**Lleva a:** [{enlace}]({enlace})")
            nivel, mensaje = img.revisar_enlace_qr(enlace)
            getattr(st, nivel)(mensaje)
        else:
            st.warning("Todavía no hay un QR guardado. Genéralo con el botón de la derecha.")
    with col_crear:
        st.markdown("**Generar el QR automáticamente** (recomendado)")
        st.caption("Crea el QR con la dirección de Consulta Móvil, sin la barra ni los íconos de Streamlit.")
        enlace_qr = st.text_input("Dirección a la que apunta el QR", value=img.enlace_consulta_movil(),
                                  key="enlace_qr_movil")
        if st.button("Generar y guardar QR", type="primary", key="generar_qr_movil"):
            enlace_limpio = enlace_qr.strip()
            if not enlace_limpio.startswith("https://") or " " in enlace_limpio:
                st.error("La dirección debe empezar con https:// y no tener espacios.")
            else:
                try:
                    img.guardar_qr(img.generar_qr_png(enlace_limpio), "generado", enlace_limpio)
                    _imagenes_cambiaron()
                    st.session_state.aviso_qr = "QR generado y guardado. Aparecerá en las pantallas en menos de un minuto."
                    st.rerun()
                except ImportError:
                    st.error("Falta instalar la librería segno (requirements.txt).")
                except (RuntimeError, requests.RequestException) as exc:
                    st.error(str(exc))
        with st.expander("O subir una imagen de QR propia"):
            st.caption("PNG o JPG. Debe apuntar a la dirección pública de Consulta Móvil.")
            archivo_qr = st.file_uploader("Imagen del código QR", type=["png", "jpg", "jpeg"],
                                          key="qr_consulta_movil")
            if archivo_qr is not None:
                try:
                    datos_qr = img.preparar_qr(archivo_qr)
                    st.image(datos_qr, caption="Vista previa del QR", width=200)
                    if st.button("Guardar código QR", key="guardar_qr_movil"):
                        img.guardar_qr(datos_qr, "subido", img.leer_enlace_qr(datos_qr))
                        _imagenes_cambiaron()
                        st.session_state.aviso_qr = "Imagen de QR guardada. Aparecerá en las pantallas en menos de un minuto."
                        st.rerun()
                except (UnidentifiedImageError, OSError, ValueError):
                    st.error("La imagen del QR no es válida.")
                except (RuntimeError, requests.RequestException) as exc:
                    st.error(str(exc))

# ====================================================================== FOTOS
import fotos_productos as fp


@st.cache_data(ttl=60, show_spinner=False)
def _resumen_fotos(marca=0):
    fotos, indice = fp.resumen()
    return fotos, indice


with pestana_fotos:
    st.markdown("Cuando un producto se consulta por **primera vez** y no tiene foto, el sistema la busca "
                "sola en internet por su código de barras y guarda una copia. Desde ahí se usa siempre, "
                "también en los equipos sin internet.")
    try:
        fotos, indice = _resumen_fotos(st.session_state.ap_marca_img)
    except Exception as exc:
        st.error(f"No se pudieron leer las fotos: {exc}")
        fotos, indice = {}, {"sin_foto": {}, "pendientes": [], "origen": {}}
    de_internet = {c: v for c, v in fotos.items() if v[2] == "internet"}
    a_mano = {c: v for c, v in fotos.items() if v[2] == "manual"}
    sin_foto = {c: v for c, v in indice["sin_foto"].items() if c not in fotos}
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("De internet", f"{len(de_internet):,}")
    m2.metric("Subidas a mano", f"{len(a_mano):,}")
    m3.metric("Sin foto en internet", f"{len(sin_foto):,}")
    m4.metric("Por buscar", f"{len(indice['pendientes']):,}")

    if st.button("🔎 Buscar fotos ahora", type="primary", key="buscar_fotos",
                 help="Busca las fotos de los productos consultados que todavía no tienen. "
                      "Igual se hace sola cada 30 minutos."):
        with st.spinner("Buscando fotos en internet… (unos segundos por producto)"):
            try:
                r = fp.procesar_pendientes(maximo=25, registro=lambda *_: None)
                _imagenes_cambiaron()
                import publicar_equipos
                publicar_equipos.actualizar_si_publicado()
                st.session_state.aviso_logo = (f"Fotos: {r['halladas']} encontradas, {r['sin_foto']} sin foto en "
                                               f"internet, {r['pendientes']} quedan por buscar.")
                st.rerun()
            except Exception as exc:
                st.error(f"No se pudo buscar: {exc}")
    st.caption("Se buscan solas: al consultar en la Consulta en línea (al instante) y cada 30 minutos para "
               "lo consultado en los equipos sin internet. Los equipos descargan las fotos nuevas solos. "
               "Fuente: bases abiertas de Open Food Facts (licencia libre CC BY-SA). Muchos productos locales "
               "no aparecen en internet: súbeles la foto a mano.")

    st.markdown("#### Fotos guardadas")
    filtro = st.text_input("Buscar por código", key="filtro_fotos", placeholder="Ej.: 7501055363063").strip()
    orden = sorted(fotos.items(), key=lambda kv: (indice["origen"].get(kv[0], {}).get("fecha", ""), kv[0]),
                   reverse=True)
    if filtro:
        orden = [kv for kv in orden if filtro in kv[0]]
    visibles = orden[:30]
    if not fotos:
        st.info("Todavía no hay fotos. Aparecerán solas a medida que se consulten productos.")
    elif not visibles:
        st.info("Ningún código coincide.")
    else:
        enlaces = fp.enlaces_firmados([v[0] for _, v in visibles])
        for inicio in range(0, len(visibles), 5):
            columnas = st.columns(5)
            for col, (codigo, (ruta, _, origen)) in zip(columnas, visibles[inicio:inicio + 5]):
                with col:
                    if enlaces.get(ruta):
                        st.image(enlaces[ruta], use_container_width=True)
                    fuente = indice["origen"].get(codigo, {}).get("fuente", "internet")
                    st.caption(f"**{codigo}**  \n{'✋ Subida a mano' if origen == 'manual' else '🌐 ' + fuente}")
                    if origen == "internet":
                        c1, c2 = st.columns(2)
                        if c1.button("🗑️", key=f"quitar_{codigo}", help="Quitar esta foto y no volver a buscarla"):
                            fp.quitar(codigo)
                            _imagenes_cambiaron()
                            import publicar_equipos
                            publicar_equipos.actualizar_si_publicado()
                            st.rerun()
                        if c2.button("🔄", key=f"otra_{codigo}", help="Volver a buscarla en internet"):
                            fp.volver_a_buscar(codigo)
                            _imagenes_cambiaron()
                            st.rerun()
                    elif st.button("🗑️", key=f"quitarm_{codigo}", help="Quitar la foto subida a mano"):
                        fp.quitar_manual(codigo)
                        _imagenes_cambiaron()
                        import publicar_equipos
                        publicar_equipos.actualizar_si_publicado()
                        st.rerun()
        if len(orden) > len(visibles):
            st.caption(f"Se muestran 30 de {len(orden):,}. Busca por código para ver otra.")

    with st.expander("✋ Subir una foto a mano (tiene prioridad sobre la de internet)"):
        codigo_imagen = st.text_input("Código de barras del producto", key="codigo_imagen_producto").strip()
        archivo_imagen = st.file_uploader("Fotografía JPG o PNG", type=["jpg", "jpeg", "png"],
                                          key="foto_producto_manual")
        if archivo_imagen is not None and codigo_imagen.isdigit() and 6 <= len(codigo_imagen) <= 14:
            if st.button("Guardar fotografía del producto", type="primary"):
                try:
                    datos = img.guardar_foto_producto(codigo_imagen, archivo_imagen)
                    _imagenes_cambiaron()
                    import publicar_equipos
                    publicar_equipos.actualizar_si_publicado()
                    st.image(datos, caption=f"Imagen para {codigo_imagen}", width=200)
                    st.success("Fotografía guardada. Los equipos la descargan solos.")
                except (UnidentifiedImageError, OSError, ValueError):
                    st.error("El archivo de imagen no es válido.")
                except (RuntimeError, requests.RequestException) as exc:
                    st.error(str(exc))
        elif archivo_imagen is not None:
            st.warning("Introduce un código de barras numérico de 6 a 14 dígitos.")

    if sin_foto:
        with st.expander(f"🚫 Códigos sin foto en internet ({len(sin_foto):,})"):
            st.caption("Se vuelven a buscar solos a los 30 días. Los marcados como quitados no se buscan más.")
            st.dataframe([{"Código": c, "Revisado": v.get("fecha", "")[:10],
                           "Estado": "Quitada por ti" if v.get("rechazada") else "No está en internet"}
                          for c, v in sorted(sin_foto.items())], hide_index=True, use_container_width=True)
