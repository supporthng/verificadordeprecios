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

# La sección QR se muestra antes del logo para que sea fácil encontrarla.
st.info("📱 CONFIGURACIÓN DEL CÓDIGO QR: sube aquí la imagen para consultar desde tu celular.")
try:
    qr_actual = requests.get(
        f"{url}/storage/v1/object/logo-negocio/qr-movil.png",
        headers=headers, timeout=12,
    )
    if qr_actual.ok and qr_actual.headers.get("Content-Type", "").startswith("image/"):
        st.success("Código QR guardado actualmente en Supabase.")
        st.image(qr_actual.content, caption="QR que se mostrará en Consulta de Precios", width=180)
    elif qr_actual.status_code in (400, 404):
        st.warning("Aún no hay un código QR guardado. Sube la imagen debajo.")
    else:
        st.warning(f"No se pudo comprobar el QR guardado (HTTP {qr_actual.status_code}).")
except requests.RequestException:
    st.warning("No se pudo consultar el estado del QR en Supabase.")

st.divider()
st.subheader("📱 Código QR para consulta desde el celular")
st.caption(
    "Sube una imagen PNG o JPG de tu código QR. Se mostrará centrada junto "
    "al logo en la pantalla de Consulta de Precios. "
    "El QR debe apuntar a la dirección pública de Consulta Móvil."
)
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
        if st.button("Guardar código QR", type="primary", key="guardar_qr_movil"):
            # El bucket logo-negocio es privado; reutilizarlo evita migraciones SQL.
            estado = requests.get(
                f"{url}/storage/v1/bucket/logo-negocio", headers=headers, timeout=15
            )
            if estado.status_code == 404:
                creado = requests.post(
                    f"{url}/storage/v1/bucket",
                    headers={**headers, "Content-Type": "application/json"},
                    json={"id": "logo-negocio", "name": "logo-negocio", "public": False},
                    timeout=15,
                )
                if not creado.ok:
                    st.error(f"No se pudo crear el almacenamiento (HTTP {creado.status_code}).")
                    st.stop()
            elif not estado.ok:
                st.error(f"No se pudo comprobar el almacenamiento (HTTP {estado.status_code}).")
                st.stop()
            guardado = requests.post(
                f"{url}/storage/v1/object/logo-negocio/qr-movil.png",
                headers={**headers, "Content-Type": "image/png", "x-upsert": "true"},
                data=datos_qr,
                timeout=25,
            )
            if guardado.ok:
                st.success("Código QR guardado. Aparecerá junto al logo en Consulta de Precios.")
            else:
                st.error(f"No se pudo guardar el QR (HTTP {guardado.status_code}): {guardado.text[:350]}")
    except (UnidentifiedImageError, OSError, ValueError):
        st.error("La imagen del QR no es válida.")
    except requests.RequestException as exc:
        st.error(f"No se pudo comunicar con Supabase: {exc}")


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
