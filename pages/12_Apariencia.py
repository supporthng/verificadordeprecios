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

# Si la app siguió corriendo mientras se subieron archivos nuevos a GitHub, Streamlit puede
# tener en memoria la versión vieja de estos módulos: recargarlos para no fallar.
import importlib
if not hasattr(apariencia, "ESTILOS") or "mostrar_foto" not in apariencia.PREDETERMINADA:
    apariencia = importlib.reload(apariencia)
if not hasattr(vista_previa, "FOTO_DEMO"):
    vista_previa = importlib.reload(vista_previa)
vista_previa._plantilla.cache_clear() if hasattr(vista_previa, "_plantilla") else None

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
CAMPOS = [c for c in apariencia.PREDETERMINADA if c != "nombre_principal"]   # se edita en Sucursales
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
        st.toggle("Mostrar el nombre de la sucursal debajo", key="ap_mostrar_sucursal",
                  help="Cada equipo muestra el de su sucursal; los de la Principal, el nombre que le pongas "
                       "en Administración › Sucursales › Principal.")
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

    elegida = apariencia.normalizar({**guardada, **{c: st.session_state["ap_" + c] for c in CAMPOS}})
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
                apariencia.guardar({k: v for k, v in elegida.items() if k != "nombre_principal"})
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

    with st.expander("🏪 Tiendas en línea donde buscar fotos"):
        st.caption("El sistema busca primero en estas tiendas, por código de barras y, si no aparece, por el "
                   "nombre del producto. Sirena ya está incluida. Agrega otras pegando su dirección (una por "
                   "línea): funcionan las tiendas hechas con VTEX o Shopify, que tienen catálogo público.")
        try:
            actuales = fp.tiendas_configuradas()
        except Exception:
            actuales = list(fp.TIENDAS_PREDETERMINADAS)
        for t in actuales:
            st.markdown(f"- **{t['nombre']}** · {t['sitio'].split('//', 1)[-1]} "
                        f"({'VTEX' if t['plataforma'] == 'vtex' else 'Shopify'})"
                        + (" · incluida" if t in fp.TIENDAS_PREDETERMINADAS else ""))
        agregadas = [t["sitio"] for t in actuales if t not in fp.TIENDAS_PREDETERMINADAS]
        texto_tiendas = st.text_area("Tiendas agregadas (una dirección por línea)", value="\n".join(agregadas),
                                     key="tiendas_fotos", placeholder="plazalama.com.do\nmerkapp.com")
        if st.button("Guardar tiendas", key="guardar_tiendas"):
            with st.spinner("Revisando cada tienda…"):
                try:
                    lineas = [x.strip() for x in texto_tiendas.splitlines() if x.strip()]
                    for sitio, plataforma in fp.guardar_tiendas(lineas):
                        if plataforma:
                            st.success(f"{sitio}: lista ({'VTEX' if plataforma == 'vtex' else 'Shopify'}).")
                        else:
                            st.warning(f"{sitio}: no tiene un catálogo público que el sistema pueda leer. "
                                       "Sus fotos igual pueden aparecer por el buscador de imágenes.")
                except Exception as exc:
                    st.error(f"No se pudieron guardar las tiendas: {exc}")

    if st.button("🔎 Buscar fotos ahora", type="primary", key="buscar_fotos",
                 help="Busca las fotos de los productos consultados que todavía no tienen. "
                      "Igual se hace sola cada 30 minutos."):
        with st.spinner("Buscando fotos en internet… (hasta 5 productos, cerca de un minuto)"):
            try:
                r = fp.procesar_pendientes(maximo=5, registro=lambda *_: None)
                _imagenes_cambiaron()
                import publicar_equipos
                publicar_equipos.actualizar_si_publicado()
                st.session_state.aviso_logo = (f"Fotos: {r['halladas']} encontradas, {r['sin_foto']} sin foto en "
                                               f"internet, {r['pendientes']} quedan por buscar.")
                st.rerun()
            except Exception as exc:
                st.error(f"No se pudo buscar: {exc}")
    if de_internet and st.button("🧹 Quitar las fotos que no son de catálogo", key="revisar_fotos",
                                 help="Revisa las fotos de internet ya guardadas y quita las tomadas en la "
                                      "tienda o con la mano; esos productos se vuelven a buscar."):
        with st.spinner("Revisando fotos…"):
            try:
                n = fp.revisar_guardadas()
                _imagenes_cambiaron()
                import publicar_equipos
                publicar_equipos.actualizar_si_publicado()
                st.session_state.aviso_logo = f"Se quitaron {n} foto(s) que no eran de catálogo."
                st.rerun()
            except Exception as exc:
                st.error(f"No se pudo revisar: {exc}")
    if sin_foto and st.button(f"🔄 Volver a buscar los {len(sin_foto)} productos sin foto", key="reintentar_fotos",
                              help="Los pone otra vez en la cola (no incluye los que quitaste tú). "
                                   "Úsalo después de agregar tiendas."):
        try:
            n = fp.reintentar_sin_foto()
            _imagenes_cambiaron()
            st.session_state.aviso_logo = f"{n} producto(s) vuelven a la cola de búsqueda."
            st.rerun()
        except Exception as exc:
            st.error(f"No se pudo: {exc}")
    st.caption("Solo se guardan fotos **de catálogo**: el producto solo, sobre fondo blanco. Las fotos tomadas "
               "en la tienda o con la mano se descartan solas.")
    st.caption("Se buscan solas: al consultar en la Consulta en línea (al instante) y cada 30 minutos para "
               "lo consultado en los equipos sin internet. Los equipos descargan las fotos nuevas solos. "
               "Fuentes: UPCitemdb (fotos de tiendas en línea, 100 búsquedas gratis al día), Open Food Facts "
               "(licencia libre CC BY-SA), las páginas de las tiendas que venden el producto y el buscador de "
               "imágenes DuckDuckGo, todo gratis y sin claves. A los productos que "
               "no estén en internet, súbeles la foto a mano.")

    with st.expander("🧪 Probar con un código", expanded=not fotos):
        st.caption("Busca ahora mismo la foto de un código en internet y muestra qué respondió cada base.")
        cp1, cp2 = st.columns([2, 1])
        codigo_prueba = cp1.text_input("Código de barras", key="codigo_prueba_foto",
                                       label_visibility="collapsed", placeholder="Ej.: 7501055363063").strip()
        nombre_prueba = st.text_input("Nombre del producto (opcional)", key="nombre_prueba_foto",
                                      placeholder="Si lo dejas vacío, se usa el de tu inventario").strip()
        if cp2.button("Buscar foto", key="probar_foto", use_container_width=True) and codigo_prueba:
            with st.spinner("Buscando…"):
                try:
                    r = fp.probar(codigo_prueba, nombre_prueba)
                except Exception as exc:
                    r = {"error": str(exc)}
            if r.get("error"):
                st.error(r["error"])
            elif r.get("ya"):
                st.success("Este código ya tiene foto " + ("subida a mano." if r["ya"] == "manual" else "de internet."))
                enlace = fp.enlaces_firmados([r["ruta"]]).get(r["ruta"])
                if enlace:
                    st.image(enlace, width=200)
            else:
                if r.get("ruta"):
                    _imagenes_cambiaron()
                    st.success(f"Foto encontrada en {r['fuente']} y guardada.")
                    enlace = fp.enlaces_firmados([r["ruta"]]).get(r["ruta"])
                    if enlace:
                        st.image(enlace, width=200)
                    import publicar_equipos
                    publicar_equipos.actualizar_si_publicado()
                elif not r.get("nombre"):
                    st.warning("Este código **no está en tu inventario** y por eso no se pudo buscar por nombre. "
                               "Revisa que esté completo (los EAN tienen 13 dígitos) o escribe el nombre arriba.")
                elif not r.get("respondio"):
                    st.error("Las bases de fotos no respondieron desde el servidor. Vuelve a intentar en unos minutos.")
                else:
                    st.warning("Ninguna base de internet tiene foto de este código. Súbela a mano abajo.")
                if r.get("nombre"):
                    st.caption(f"Nombre usado para buscar: **{r['nombre']}**")
                # En lista (no en tabla): en el celular la tabla corta los textos largos.
                st.markdown("\n".join(f"- **{b}**{' · ' + c if c else ''}: {t}" for b, c, t in r.get("informe", [])))

    # ---- Búsqueda con navegador real (GitHub Actions), iniciada desde aquí
    import github_acciones as ga
    st.markdown("#### 🌐 Buscar con el navegador")
    st.caption("La búsqueda de arriba la hace el servidor de Streamlit, donde los buscadores de imágenes dan "
               "pocos resultados. Este botón le pide a GitHub que abra un **Chrome de verdad** (Bing Imágenes "
               "completo, descarga o captura de la foto) y recorra Merkapp. Tarda unos 5 a 10 minutos.")
    if ga.configurado():
        cb1, cb2 = st.columns([2, 1])
        codigos_nav = cb1.text_input("Códigos a buscar primero (opcional, separados por coma)",
                                     value=st.session_state.get("codigo_prueba_foto", ""), key="codigos_navegador")
        if cb2.button("🌐 Buscar con el navegador ahora", key="iniciar_navegador", use_container_width=True):
            lista = [c.strip() for c in codigos_nav.replace(" ", ",").split(",") if c.strip()]
            ok, motivo = ga.iniciar(lista)
            if ok:
                st.success("Listo: GitHub ya empezó a buscar. En unos minutos toca «Ver estado» y, al terminar, "
                           "las fotos encontradas aparecen en «Fotos guardadas».")
            else:
                st.error(motivo)
        if st.button("Ver estado", key="estado_navegador"):
            ultima = ga.ultima_ejecucion()
            if not ultima:
                st.info("Todavía no hay ejecuciones.")
            else:
                texto = {"queued": "⏳ En cola", "in_progress": "🔄 Buscando…"}.get(ultima["estado"])
                if not texto:
                    texto = "✅ Terminó" if ultima["resultado"] == "success" else f"⚠️ Terminó: {ultima['resultado']}"
                try:
                    hora = datetime.fromisoformat(ultima["fecha"].replace("Z", "+00:00")).astimezone(
                        ZoneInfo("America/Santo_Domingo"))
                    texto += f" · iniciada {hora:%d/%m %H:%M}"
                except (ValueError, AttributeError):
                    pass
                st.markdown(f"{texto} · [ver el registro en GitHub]({ultima['enlace']})")
                if ultima["estado"] == "completed":
                    _imagenes_cambiaron()
    else:
        with st.expander("Activar este botón (una sola vez)"):
            st.markdown(
                "Hace falta una clave de GitHub que **solo** pueda iniciar las tareas de este repositorio:\n\n"
                "1. En GitHub: tu foto (arriba a la derecha) → **Settings** → **Developer settings** → "
                "**Personal access tokens** → **Fine-grained tokens** → **Generate new token**.\n"
                "2. **Token name:** `Verificador fotos`. **Expiration:** la más larga que permita.\n"
                "3. **Resource owner:** `supporthng` (el dueño del repositorio).\n"
                "4. **Repository access:** *Only select repositories* → `verificadordeprecios`.\n"
                "5. **Permissions → Repository permissions → Actions:** *Read and write*. Nada más.\n"
                "6. **Generate token** y copia la clave (empieza con `github_pat_`).\n"
                "7. En Streamlit: **Manage app → Settings → Secrets**, agrega la línea\n"
                "   `GITHUB_TOKEN_ACCIONES = \"github_pat_...\"` y guarda.\n\n"
                "La clave queda solo en los Secrets de Streamlit (nunca en los archivos de GitHub).")

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

        st.markdown("**O desde internet, sin descargarla:**")
        if codigo_imagen:
            from urllib.parse import quote_plus
            st.link_button("🔍 Buscar en Google Imágenes",
                           "https://www.google.com/search?tbm=isch&q=" + quote_plus(codigo_imagen))
        st.caption("En Google, abre la foto, mantén el dedo encima (o clic derecho) → **Copiar dirección de "
                   "la imagen**, y pégala aquí. Se recorta y se deja sobre fondo blanco.")
        enlace_foto = st.text_input("Enlace de la imagen", key="enlace_foto_producto",
                                    placeholder="https://…/foto.jpg").strip()
        if enlace_foto and codigo_imagen.isdigit() and 6 <= len(codigo_imagen) <= 14:
            if st.button("Guardar foto del enlace", type="primary", key="guardar_enlace_foto"):
                try:
                    from io import BytesIO
                    jpeg, puntaje = fp.importar_desde_enlace(enlace_foto)
                    datos = img.guardar_foto_producto(codigo_imagen, BytesIO(jpeg))
                    _imagenes_cambiaron()
                    import publicar_equipos
                    publicar_equipos.actualizar_si_publicado()
                    st.image(datos, caption=f"Foto para {codigo_imagen}", width=200)
                    st.success("Foto guardada. Los equipos la descargan solos.")
                    if puntaje < fp.FONDO_MINIMO:
                        st.warning("Ojo: esa foto no parece de catálogo (el fondo no es blanco). "
                                   "Si no te gusta, quítala en la galería y elige otra.")
                except (RuntimeError, requests.RequestException, OSError, ValueError) as exc:
                    st.error(str(exc))
        elif enlace_foto:
            st.warning("Escribe arriba el código de barras del producto.")

    if sin_foto:
        with st.expander(f"🚫 Códigos sin foto en internet ({len(sin_foto):,})"):
            st.caption("Se vuelven a buscar solos a los 30 días. Los marcados como quitados no se buscan más.")
            st.dataframe([{"Código": c, "Revisado": v.get("fecha", "")[:10],
                           "Estado": "Quitada por ti" if v.get("rechazada") else "No está en internet"}
                          for c, v in sorted(sin_foto.items())], hide_index=True, use_container_width=True)
