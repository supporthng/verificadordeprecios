"""Instaladores: descargar las apps Consulta de Precios (Android y Windows) desde la plataforma."""
import io
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st

from auth_usuarios import require_admin

require_admin()
ZONA = ZoneInfo("America/Santo_Domingo")
REPO = "https://github.com/supporthng/verificadordeprecios/releases/download"
APPS_JSON = "https://supporthng.github.io/verificadordeprecios/apps.json"
APPS = {
    "android": {"titulo": "Android", "icono": "🤖", "archivo": "ConsultaPrecios.apk",
                "url": f"{REPO}/android/ConsultaPrecios.apk",
                "para": "2connect, tabletas y celulares Android"},
    "windows": {"titulo": "Windows", "icono": "🪟", "archivo": "Instalador_Consulta_de_Precios.exe",
                "url": f"{REPO}/windows/Instalador_Consulta_de_Precios.exe",
                "para": "PC o pantalla táctil con lector, Windows 10 u 11"},
}

st.title("📦 Instaladores")
st.caption("Descarga las apps **Consulta de Precios** para los equipos verificadores. Siempre es la última "
           "versión publicada; una vez instaladas, se actualizan solas.")


@st.cache_data(ttl=300, show_spinner=False)
def versiones_publicadas():
    """Versión que anuncia docs/apps.json (la que los equipos buscan al actualizarse)."""
    try:
        r = requests.get(APPS_JSON, params={"t": int(datetime.now().timestamp() // 300)}, timeout=10)
        return {k: (v or {}).get("version") for k, v in r.json().items()} if r.ok else {}
    except Exception:
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def datos_archivo(url):
    """Tamaño y fecha del archivo publicado en GitHub (o None si todavía no existe)."""
    try:
        r = requests.head(url, allow_redirects=True, timeout=15)
        if not r.ok:
            return None
        tamano = int(r.headers.get("Content-Length") or 0)
        fecha = r.headers.get("Last-Modified")
        if fecha:
            fecha = datetime.strptime(fecha, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=ZoneInfo("UTC")) \
                .astimezone(ZONA).strftime("%d/%m/%Y %I:%M %p")
        return {"tamano": tamano, "fecha": fecha}
    except Exception:
        return {}


def _qr(texto):
    try:
        import segno
        img = io.BytesIO()
        segno.make(texto, error="l").save(img, kind="png", scale=5, border=3)
        return img.getvalue()
    except Exception:
        return None


versiones = versiones_publicadas()
columnas = st.columns(2)
for columna, (clave, app) in zip(columnas, APPS.items()):
    with columna, st.container(border=True):
        st.subheader(f"{app['icono']} {app['titulo']}")
        st.caption(app["para"])
        info = datos_archivo(app["url"])
        if info is None:
            st.warning("Todavía no hay instalador publicado. En GitHub › **Actions**, ejecuta "
                       f"*Construir app {app['titulo']}*.")
            continue
        detalles = []
        if versiones.get(clave):
            detalles.append(f"Versión **{versiones[clave]}**")
        if info.get("fecha"):
            detalles.append(f"publicada el {info['fecha']}")
        if info.get("tamano"):
            t = info["tamano"]
            detalles.append(f"{t / 1_048_576:.1f} MB" if t >= 1_048_576 else f"{max(1, round(t / 1024))} KB")
        if detalles:
            st.markdown(" · ".join(detalles))
        st.link_button(f"⬇️ Descargar {app['archivo']}", app["url"], type="primary", use_container_width=True)
        imagen = _qr(app["url"])
        if imagen:
            st.image(imagen, width=170, caption="O escanéalo con la cámara del equipo")
        st.code(app["url"], language=None)

st.markdown("#### Cómo instalar")
tab_android, tab_windows = st.tabs(["🤖 Android", "🪟 Windows"])
with tab_android:
    st.markdown("""
1. **En el equipo**, escanea el QR o abre el enlace en el navegador y descarga **ConsultaPrecios.apk**.
   (Si lo descargaste en la PC, pásalo al equipo por cable o USB.)
2. Ábrelo e **instálalo**. Si Android lo pide, permite *Instalar apps desconocidas* para el navegador.
3. Abre **Consulta de Precios**: descarga los precios y queda lista.
4. Pulsa **Inicio** de Android, elige **Consulta de Precios** y **Siempre**.
5. En **⚙**, ponle nombre al equipo y toca **🔒 Bloquear los botones de Android**.

Si el equipo ya tenía una versión anterior, instálala **encima**: conserva los precios y la configuración.
""")
with tab_windows:
    st.markdown("""
1. **En la PC del verificador**, toca **Descargar** y abre el instalador.
2. Si Windows avisa *«Windows protegió su PC»*: **Más información › Ejecutar de todas formas**.
3. Deja marcado **Abrir automáticamente al iniciar Windows**.
4. La app queda a pantalla completa. Para salir: **✕** y la clave de salida.

Si la PC ya tenía una versión anterior, cierra la app con **✕** y ejecuta el instalador: se instala encima.
""")
st.page_link("pages/14_Equipos_sin_internet.py", label="Guía completa y estado de los equipos", icon="📴")
