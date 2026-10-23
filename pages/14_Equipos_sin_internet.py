"""Equipos sin internet: publicar precios y configuración para la app offline."""
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from auth_usuarios import require_admin
import publicar_equipos as pe

require_admin()
ZONA = ZoneInfo("America/Santo_Domingo")

st.title("📴 Equipos sin internet")
st.caption("Los verificadores y celulares con la app sin internet guardan una copia de los precios. "
           "Revisan cada pocos minutos si hay una versión nueva y **solo descargan cuando cambia**.")


def _fecha(iso):
    try:
        return datetime.fromisoformat(iso).astimezone(ZONA).strftime("%d/%m/%Y %I:%M %p")
    except (TypeError, ValueError):
        return "—"


if "aviso_equipos" in st.session_state:
    st.success(st.session_state.pop("aviso_equipos"))

# ---------------- Estado publicado ----------------
st.subheader("Lo que tienen los equipos")
actual = pe.estado()
if actual is None:
    st.info("Todavía no se ha publicado nada para los equipos. Define la clave de salida (abajo) "
            "y pulsa **Publicar precios a los equipos**.")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Productos", f"{actual.get('productos', 0):,}")
    c2.metric("Inventario", actual.get("inventario", "—"))
    c3.metric("Publicado", _fecha(actual.get("publicado")))
    faltan = []
    if not actual.get("salida"):
        faltan.append("la **clave de salida** (sin ella no se puede salir del verificador)")
    if not actual.get("registro"):
        faltan.append("la clave pública de Supabase en Secrets (sin ella no se sube el registro de consultas)")
    if faltan:
        st.warning("Falta " + " y ".join(faltan) + ".")
    st.caption(f"Versión `{actual.get('version')}` · "
               f"logo {'✅' if actual.get('logo') else '—'} · QR {'✅' if actual.get('qr') else '—'}")

st.caption("Los cambios en **Inventarios independientes**, **Logo** y **Apariencia** se publican solos "
           "una vez que los equipos están en uso. Este botón sirve para forzarlo.")
if st.button("📤 Publicar precios a los equipos", type="primary"):
    try:
        with st.spinner("Preparando el catálogo…"):
            nuevo = pe.publicar()
        if actual and actual.get("version") == nuevo["version"]:
            st.session_state["aviso_equipos"] = ("Publicado. Los precios no cambiaron, así que los equipos "
                                                 "no necesitan descargar nada.")
        else:
            st.session_state["aviso_equipos"] = (f"Publicado: {nuevo['productos']:,} productos. Los equipos "
                                                 "lo descargarán en los próximos minutos (si tienen internet).")
        st.rerun()
    except Exception as exc:
        st.error("No se pudo publicar: " + str(exc))

# ---------------- Clave de salida ----------------
st.subheader("🔐 Clave de salida del verificador")
st.markdown(
    "Se pide para salir del verificador o cambiar al modo celular, **también sin internet**. "
    "Por eso el equipo guarda una verificación cifrada de esta clave: usa una clave **distinta "
    "de tu contraseña de administrador** y de al menos "
    f"{pe.LARGO_MINIMO_CLAVE} caracteres (mejor con letras y números)."
)
try:
    tiene = pe.hay_clave_salida()
except Exception:
    tiene = False
st.caption("Estado: " + ("✅ definida" if tiene else "⚠️ todavía no definida"))
with st.form("clave_salida", clear_on_submit=True):
    nueva = st.text_input("Nueva clave de salida", type="password")
    repetir = st.text_input("Repite la clave", type="password")
    if st.form_submit_button("Guardar clave de salida"):
        try:
            if nueva != repetir:
                raise ValueError("Las dos claves no coinciden.")
            pe.guardar_clave_salida(nueva)
            ok, res = pe.actualizar_si_publicado()
            st.session_state["aviso_equipos"] = (
                "Clave de salida guardada" + (" y enviada a los equipos." if ok else
                                              ". Se enviará a los equipos al publicar."))
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

# ---------------- Instalar en un equipo ----------------
st.subheader("📲 Instalar en un equipo")
st.markdown(
    "La app sin internet está en la carpeta **docs** del repositorio y se publica gratis con "
    "**GitHub Pages** (en GitHub: *Settings > Pages > Deploy from a branch > main / docs*). "
    "GitHub te muestra su dirección, por ejemplo `https://tuusuario.github.io/verificadordeprecios/`."
)
guardada = pe.app_equipos()
with st.form("app_equipos"):
    direccion = st.text_input("Dirección de la app en GitHub Pages", value=guardada,
                              placeholder="https://tuusuario.github.io/verificadordeprecios/")
    if st.form_submit_button("Guardar dirección"):
        try:
            guardada = pe.guardar_app_equipos(direccion)
            st.success("Dirección guardada.")
        except Exception as exc:
            st.error(str(exc))
if guardada:
    enlace = pe.enlace_instalacion(guardada)
    st.markdown("**Enlace de instalación.** Ábrelo **una vez** en cada equipo con internet. "
                "El equipo queda vinculado y descarga los precios. Después funciona sin conexión.")
    st.code(enlace, language=None)
    try:
        import io
        import segno
        imagen = io.BytesIO()
        segno.make(enlace, error="m").save(imagen, kind="png", scale=6, border=3)
        st.image(imagen.getvalue(), caption="Escanéalo con la cámara del equipo", width=260)
    except Exception:
        pass
    st.caption("En Chrome para Android: menú ⋮ > **Instalar aplicación** (o *Agregar a la pantalla "
               "principal*) para abrirla a pantalla completa, como una app.")

# ---------------- Direcciones ----------------
with st.expander("Detalles técnicos"):
    st.markdown("Archivo que revisan los equipos:")
    st.code(pe.url_publica("estado.json"), language=None)
    st.caption("Es público a propósito: contiene los mismos precios que ya muestra la Consulta Móvil, "
               "y la clave de salida solo como verificación PBKDF2 (no la clave).")
