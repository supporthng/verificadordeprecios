"""Pagina administrativa para cargar el logo del verificador."""
from io import BytesIO

import requests
import streamlit as st
from supabase_cliente import cabeceras, clave_servidor, clave_publica
from PIL import Image, UnidentifiedImageError

st.title("🖼️ Logo del negocio")
st.write("Sube el logo que aparecera debajo del lector de codigo en Consulta de precios.")

url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
key = clave_servidor()
# Acceso por permisos del usuario que inició sesión (sin contraseña aparte).
from auth_usuarios import require
require("logo")

if not url or not key:
    st.error("Falta configurar SUPABASE_URL o SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY).")
    st.stop()

headers = cabeceras(key)

INFO_QR = "logo-negocio/qr-movil.json"   # de dónde vino el QR actual y cuándo


def leer_enlace_qr(datos_imagen):
    """Lee el QR de una imagen y devuelve el texto/dirección que contiene (o None)."""
    try:
        import zxingcpp
        with Image.open(BytesIO(datos_imagen)) as im:
            encontrados = zxingcpp.read_barcodes(im.convert("RGB"))
        return encontrados[0].text if encontrados else None
    except Exception:
        return None


def leer_info_qr():
    try:
        r = requests.get(f"{url}/storage/v1/object/{INFO_QR}", headers=headers, timeout=10)
        return r.json() if r.ok else {}
    except (requests.RequestException, ValueError):
        return {}


def guardar_qr(datos_png, origen, enlace=None):
    """Guarda el QR en el almacenamiento privado (crea el bucket si hace falta)
    y registra su origen ("generado" o "subido"), la dirección y la fecha."""
    estado = requests.get(f"{url}/storage/v1/bucket/logo-negocio", headers=headers, timeout=15)
    if estado.status_code == 404:
        creado = requests.post(
            f"{url}/storage/v1/bucket",
            headers={**headers, "Content-Type": "application/json"},
            json={"id": "logo-negocio", "name": "logo-negocio", "public": False},
            timeout=15,
        )
        if not creado.ok:
            raise RuntimeError(f"No se pudo crear el almacenamiento (HTTP {creado.status_code}).")
    elif not estado.ok:
        raise RuntimeError(f"No se pudo comprobar el almacenamiento (HTTP {estado.status_code}).")
    guardado = requests.post(
        f"{url}/storage/v1/object/logo-negocio/qr-movil.png",
        headers={**headers, "Content-Type": "image/png", "x-upsert": "true"},
        data=datos_png, timeout=25,
    )
    if not guardado.ok:
        raise RuntimeError(f"No se pudo guardar el QR (HTTP {guardado.status_code}): {guardado.text[:350]}")
    from datetime import datetime, timezone
    import json
    info = {"origen": origen, "enlace": enlace,
            "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:   # el registro es informativo: si falla, el QR igual quedó guardado
        requests.post(f"{url}/storage/v1/object/{INFO_QR}",
                      headers={**headers, "Content-Type": "application/json", "x-upsert": "true"},
                      data=json.dumps(info).encode("utf-8"), timeout=15)
    except requests.RequestException:
        pass
    import publicar_equipos
    publicar_equipos.actualizar_si_publicado()   # los equipos sin internet reciben el QR nuevo


def mostrar_qr_actual():
    """Muestra qué QR está puesto: imagen, origen, fecha y a dónde lleva."""
    st.markdown("**QR que se muestra ahora en la pantalla de consulta**")
    try:
        r = requests.get(f"{url}/storage/v1/object/logo-negocio/qr-movil.png", headers=headers, timeout=12)
    except requests.RequestException:
        st.warning("No se pudo consultar el QR guardado en Supabase.")
        return
    if r.status_code in (400, 404):
        st.warning("Todavía no hay un QR guardado. Genéralo con el botón de abajo.")
        return
    if not (r.ok and r.headers.get("Content-Type", "").startswith("image/")):
        st.warning(f"No se pudo comprobar el QR guardado (HTTP {r.status_code}).")
        return
    info = leer_info_qr()
    enlace = leer_enlace_qr(r.content) or info.get("enlace")
    col_img, col_txt = st.columns([1, 2])
    col_img.image(r.content, width=170)
    with col_txt:
        origen = {"generado": "⚙️ Generado automáticamente",
                  "subido": "🖼️ Imagen subida manualmente"}.get(info.get("origen"),
                  "❔ Origen desconocido (guardado antes de que existiera este registro)")
        st.markdown(f"**Origen:** {origen}")
        if info.get("fecha"):
            try:
                from datetime import datetime
                from zoneinfo import ZoneInfo
                # Hora de República Dominicana (el servidor de Streamlit Cloud usa UTC).
                fecha = datetime.fromisoformat(info["fecha"]).astimezone(ZoneInfo("America/Santo_Domingo"))
                st.markdown(f"**Guardado:** {fecha:%d/%m/%Y %H:%M}")
            except ValueError:
                pass
        if enlace:
            st.markdown(f"**Lleva a:** [{enlace}]({enlace})")
            if "escaner_movil" not in enlace.lower() and "movil=1" not in enlace:
                st.warning("Este QR **no** lleva a Consulta Móvil. Genera uno nuevo abajo.")
            elif "embed=true" not in enlace:
                st.info("Lleva a Consulta Móvil, pero con la barra y los íconos de Streamlit. "
                        "Si generas uno nuevo, se abrirá sin ellos.")
            elif "/escaner_movil" in enlace.lower() or "light_theme" not in enlace:
                st.info("Lleva a Consulta Móvil, pero es de una versión anterior: puede mostrar el aviso "
                        "«Page not found» o el tema oscuro. Pulsa «Generar y guardar QR» para actualizarlo.")
            else:
                st.success("Correcto: lleva a Consulta Móvil sin el marco de Streamlit.")
        else:
            st.warning("No se pudo leer el contenido de este QR (imagen borrosa o no es un QR).")


def generar_qr_png(enlace):
    """Genera el QR del enlace como PNG nítido (cuadros negros sobre blanco)."""
    import segno
    salida = BytesIO()
    segno.make(enlace, error="m", micro=False).save(
        salida, kind="png", scale=12, border=3, dark="#000000", light="#ffffff")
    return salida.getvalue()


def enlace_consulta_movil():
    """Dirección pública de Consulta Móvil, sin el marco de Streamlit (embed=true).
    Usa la dirección RAÍZ con ?movil=1: en modo embed, Streamlit Cloud no reconoce
    la ruta /Escaner_Movil y muestra "Page not found". light_theme evita el tema
    oscuro del teléfono, con el que algunos textos no se leen bien."""
    from urllib.parse import urlsplit
    try:
        partes = urlsplit(st.context.url)
        base = f"{partes.scheme}://{partes.netloc}" if partes.netloc else ""
    except (AttributeError, TypeError, ValueError):
        base = ""
    return (base or "https://TU-APP.streamlit.app") + "/?movil=1&embed=true&embed_options=light_theme"


st.divider()
st.subheader("📱 Código QR para consulta desde el celular")
if st.session_state.get("aviso_qr"):
    st.success(st.session_state.pop("aviso_qr"))
mostrar_qr_actual()
st.markdown("---")

# --- Opción recomendada: generar el QR automáticamente ---------------------
st.markdown("**Opción recomendada: generar el QR automáticamente**")
st.caption("La app crea el QR con la dirección de Consulta Móvil, sin el marco de "
           "Streamlit (sin barra ni íconos). Revisa la dirección y pulsa Generar.")
enlace_qr = st.text_input("Dirección a la que apunta el QR", value=enlace_consulta_movil(),
                          key="enlace_qr_movil")
if st.button("Generar y guardar QR", type="primary", key="generar_qr_movil"):
    enlace_limpio = enlace_qr.strip()
    if not enlace_limpio.startswith("https://") or " " in enlace_limpio:
        st.error("La dirección debe empezar con https:// y no tener espacios.")
    else:
        try:
            datos_generados = generar_qr_png(enlace_limpio)
            guardar_qr(datos_generados, "generado", enlace_limpio)
            st.session_state.aviso_qr = "QR generado y guardado. Aparecerá en Consulta de Precios en menos de un minuto."
            st.rerun()
        except ImportError:
            st.error("Falta instalar la librería segno (requirements.txt).")
        except (RuntimeError, requests.RequestException) as exc:
            st.error(str(exc))

# --- Alternativa: subir una imagen propia ----------------------------------
with st.expander("O subir una imagen de QR propia"):
    st.caption("PNG o JPG. Debe apuntar a la dirección pública de Consulta Móvil.")
    archivo_qr = st.file_uploader(
        "Imagen del código QR (PNG o JPG)",
        type=["png", "jpg", "jpeg"],
        key="qr_consulta_movil",
    )
    if archivo_qr is not None:
        try:
            with Image.open(archivo_qr) as imagen_original:
                imagen_qr = imagen_original.convert("RGB")
                imagen_qr.thumbnail((900, 900))
                salida_qr = BytesIO()
                imagen_qr.save(salida_qr, format="PNG", optimize=True)
                datos_qr = salida_qr.getvalue()
            st.image(datos_qr, caption="Vista previa del QR", width=210)
            if st.button("Guardar código QR", key="guardar_qr_movil"):
                guardar_qr(datos_qr, "subido", leer_enlace_qr(datos_qr))
                st.session_state.aviso_qr = "Imagen de QR guardada. Aparecerá en Consulta de Precios en menos de un minuto."
                st.rerun()
        except (UnidentifiedImageError, OSError, ValueError):
            st.error("La imagen del QR no es válida.")
        except (RuntimeError, requests.RequestException) as exc:
            st.error(str(exc))


archivo = st.file_uploader("Selecciona un logo JPG o PNG", type=["jpg", "jpeg", "png"])
if archivo is not None:
    try:
        imagen = Image.open(archivo)
        imagen.verify()
        archivo.seek(0)
        imagen = Image.open(archivo)
        imagen.thumbnail((1400, 900))
        if imagen.mode not in ("RGB", "RGBA"):
            imagen = imagen.convert("RGBA")
        buffer = BytesIO()
        imagen.save(buffer, format="PNG", optimize=True)
        logo_png = buffer.getvalue()
        st.image(logo_png, caption="Vista previa", use_container_width=True)
    except (UnidentifiedImageError, OSError, ValueError):
        st.error("La imagen no es valida.")
        st.stop()

    if st.button("Guardar logo", type="primary", use_container_width=True):
        try:
            # Consultar primero: Supabase puede devolver 400 si el bucket ya existe.
            consulta = requests.get(
                f"{url}/storage/v1/bucket/logo-negocio",
                headers=headers,
                timeout=15,
            )
            if consulta.status_code == 404:
                bucket = requests.post(
                    f"{url}/storage/v1/bucket",
                    headers={**headers, "Content-Type": "application/json"},
                    json={"id": "logo-negocio", "name": "logo-negocio", "public": False},
                    timeout=15,
                )
                if not bucket.ok:
                    # Un conflicto de creacion concurrente solo es aceptable
                    # si luego se puede verificar que el bucket existe.
                    verificacion = requests.get(
                        f"{url}/storage/v1/bucket/logo-negocio",
                        headers=headers,
                        timeout=15,
                    )
                    if not verificacion.ok:
                        st.error(
                            f"Supabase no pudo crear el almacenamiento del logo "
                            f"(HTTP {bucket.status_code}): {bucket.text[:600]}"
                        )
                        st.stop()
            elif not consulta.ok:
                st.error(
                    f"Supabase no pudo comprobar el almacenamiento del logo "
                    f"(HTTP {consulta.status_code}): {consulta.text[:600]}"
                )
                st.stop()
            respuesta = requests.post(
                f"{url}/storage/v1/object/logo-negocio/logo.png",
                headers={**headers, "Content-Type": "image/png", "x-upsert": "true"},
                data=logo_png,
                timeout=25,
            )
            if not respuesta.ok:
                st.error(
                    f"Supabase no pudo subir el logo "
                    f"(HTTP {respuesta.status_code}): {respuesta.text[:600]}"
                )
                st.stop()
            st.success("Logo guardado. Aparecera en Consulta de precios (puede tardar hasta un minuto).")
            import publicar_equipos
            if publicar_equipos.actualizar_si_publicado()[0]:
                st.caption("📴 También se envió a los equipos sin internet.")
        except requests.RequestException as exc:
            st.error(f"No se pudo guardar el logo en Supabase: {exc}")




st.divider()
st.subheader("Fotografías de productos")
st.caption("Sube una imagen para un código de barras. Tendrá prioridad sobre las imágenes encontradas automáticamente.")
codigo_imagen = st.text_input("Código de barras del producto", key="codigo_imagen_producto").strip()
archivo_imagen = st.file_uploader("Fotografía JPG o PNG", type=["jpg", "jpeg", "png"], key="foto_producto_manual")
if archivo_imagen is not None and codigo_imagen.isdigit() and 8 <= len(codigo_imagen) <= 14:
    try:
        with Image.open(archivo_imagen) as original:
            imagen_producto_manual = original.convert("RGB")
            imagen_producto_manual.thumbnail((800, 800))
            buffer_producto = BytesIO()
            imagen_producto_manual.save(buffer_producto, format="PNG", optimize=True)
        datos_imagen = buffer_producto.getvalue()
        st.image(datos_imagen, caption=f"Imagen para {codigo_imagen}", width=200)
        if st.button("Guardar fotografía del producto", type="primary"):
            cabeceras_img = cabeceras(key)
            try:
                bucket_check = requests.get(f"{url}/storage/v1/bucket/imagenes-productos", headers=cabeceras_img, timeout=12)
                if bucket_check.status_code == 404:
                    created = requests.post(f"{url}/storage/v1/bucket", headers={**cabeceras_img,"Content-Type":"application/json"}, json={"id":"imagenes-productos","name":"imagenes-productos","public":False}, timeout=12)
                    if not created.ok:
                        st.error(f"No se pudo crear el almacenamiento (HTTP {created.status_code}).")
                        st.stop()
                elif not bucket_check.ok:
                    st.error(f"No se pudo comprobar el almacenamiento (HTTP {bucket_check.status_code}).")
                    st.stop()
                response = requests.post(f"{url}/storage/v1/object/imagenes-productos/{codigo_imagen}.png", headers={**cabeceras_img,"Content-Type":"image/png","x-upsert":"true"}, data=datos_imagen, timeout=20)
                if response.ok:
                    st.success("Fotografía guardada. La imagen aparecerá en las próximas consultas (la caché puede tardar hasta 24 horas en renovarse).")
                else:
                    st.error(f"No se pudo guardar la imagen (HTTP {response.status_code}).")
            except requests.RequestException:
                st.error("No se pudo conectar con Supabase Storage.")
    except (OSError, ValueError):
        st.error("El archivo de imagen no es válido.")
elif archivo_imagen is not None:
    st.warning("Introduce un código de barras numérico de 8 a 14 dígitos.")
