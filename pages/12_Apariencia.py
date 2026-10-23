"""Apariencia de la pantalla de Consulta de Precios."""
import streamlit as st

from auth_usuarios import require
import apariencia

require("logo")
st.title("🎨 Apariencia")
st.caption("Elige qué se ve en la pantalla de Consulta de Precios. "
           "Los cambios se aplican en todas las pantallas en unos segundos, sin recargar.")

actual = apariencia.obtener()

with st.form("apariencia"):
    mostrar_logo = st.toggle("Mostrar el logo del negocio", value=actual["mostrar_logo"])
    mostrar_qr = st.toggle("Mostrar el código QR de Consulta Móvil", value=actual["mostrar_qr"])
    mostrar_cuadro = st.toggle("Mostrar el cuadro donde se escribe el código",
                               value=actual["mostrar_cuadro"])
    st.caption("🔎 Visible u oculto, el cuadro **siempre está activo** y con el cursor puesto: "
               "el escáner lee igual. Mostrarlo sirve para ver qué código llegó o para "
               "escribirlo a mano con un teclado.")
    guardar = st.form_submit_button("Guardar apariencia", type="primary")

if guardar:
    try:
        apariencia.guardar({"mostrar_logo": mostrar_logo, "mostrar_qr": mostrar_qr,
                            "mostrar_cuadro": mostrar_cuadro})
        st.success("Apariencia guardada. Las pantallas de consulta la aplicarán en unos segundos.")
        import publicar_equipos
        ok, res = publicar_equipos.actualizar_si_publicado()
        if ok:
            st.caption("📴 También se envió a los equipos sin internet.")
        elif isinstance(res, str):
            st.warning("No se pudo enviar a los equipos sin internet: " + res)
    except Exception as exc:
        st.error("No se pudo guardar la apariencia: " + str(exc))

st.divider()
st.caption("El logo y el código QR se suben en **Logo y QR**. "
           "Si un elemento está activado pero no se subió su imagen, simplemente no aparece.")
