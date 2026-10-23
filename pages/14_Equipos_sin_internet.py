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
           "Con internet revisan cada minuto si hay una versión nueva y **solo descargan cuando cambia**.")


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

try:
    fuente = pe.fuente_activa()
except Exception:
    fuente = "local"
NOMBRE_FUENTE = {"local": "Excel (Inventarios)", "google": "Google Drive / Sheets",
                 "external": "SQL Server"}
if fuente == "external":
    info = pe.catalogo_externo_info()
    if not info:
        st.warning("La fuente activa es **SQL Server**. El conector de Windows envía el catálogo a los equipos "
                   "cada 15 minutos, pero todavía no lo ha enviado: actualiza el conector a la **versión 5** "
                   "y déjalo encendido en la PC de la tienda.")
    else:
        try:
            minutos = (datetime.now(ZONA) - datetime.fromisoformat(info["generado"]).astimezone(ZONA)).total_seconds() / 60
        except (TypeError, ValueError):
            minutos = 1e9
        texto = (f"Fuente de precios para los equipos: **SQL Server** ({info['productos']:,} productos). "
                 f"El conector envió el catálogo por última vez el **{_fecha(info['generado'])}** y lo reenvía "
                 "cada 15 minutos si cambia.")
        (st.warning if minutos > 60 else st.caption)(
            texto + (" ⚠️ Hace más de una hora: revisa que la PC con el conector esté encendida." if minutos > 60 else ""))
else:
    st.caption(f"Fuente de precios para los equipos: **{NOMBRE_FUENTE.get(fuente, fuente)}**. "
               "Los cambios hechos en la app (inventario, Google, logo, QR, apariencia) se envían solos. "
               "Los equipos con internet los reciben en 1 minuto. Este botón sirve para forzarlo.")
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

# ---------------- Estado de los equipos ----------------
st.subheader("🖥️ Estado de los equipos")
try:
    lista = pe.equipos()
except Exception as exc:
    lista = None
    if "device_status" in str(exc) or "404" in str(exc) or "42P01" in str(exc):
        st.info("Para ver el estado de cada equipo, ejecuta **sql/MIGRACION_005_estado_equipos.sql** "
                "en Supabase > SQL Editor.")
    else:
        st.warning("No se pudo leer el estado de los equipos: " + str(exc))
if lista is not None and not lista:
    st.caption("Ningún equipo ha reportado todavía. Aparecen solos cuando abren la app con internet "
               "(versión 1.1.0 o más nueva).")
elif lista:
    import pandas as pd
    ahora = datetime.now(ZONA)
    version_publicada = (actual or {}).get("version")

    def _hace(iso):
        try:
            minutos = int((ahora - datetime.fromisoformat(iso).astimezone(ZONA)).total_seconds() // 60)
        except (TypeError, ValueError):
            return "—", "⚪"
        luz = "🟢" if minutos < 15 else ("🟡" if minutos < 24 * 60 else "🔴")
        if minutos < 1:
            return "ahora", luz
        if minutos < 60:
            return f"hace {minutos} min", luz
        if minutos < 48 * 60:
            return f"hace {minutos // 60} h", luz
        return f"hace {minutos // 1440} días", luz

    filas = []
    for e in lista:
        texto, luz = _hace(e.get("ultima_vez"))
        al_dia = e.get("precios_version") == version_publicada
        filas.append({
            " ": luz, "Equipo": e.get("nombre"), "Última conexión": texto,
            "Precios": "✅ al día" if al_dia else "⚠️ versión anterior",
            "Productos": e.get("productos"), "Consultas por subir": e.get("pendientes"),
            "App": e.get("app_version"),
        })
    st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)
    st.caption("🟢 conectado en los últimos 15 min · 🟡 hoy · 🔴 más de un día sin conexión (apagado o sin "
               "internet: sigue funcionando con los precios que tiene). Ponle nombre a cada equipo desde su "
               "menú ✕.")
    with st.expander("Quitar un equipo de la lista"):
        nombres = {e["device_id"]: f"{e.get('nombre')} · {_hace(e.get('ultima_vez'))[0]}" for e in lista}
        quitar = st.selectbox("Equipo", list(nombres), format_func=nombres.get)
        st.caption("Solo lo quita de esta lista (por ejemplo, un equipo que ya no usas). "
                   "Si sigue encendido, volverá a aparecer.")
        if st.button("Quitar de la lista"):
            try:
                pe.olvidar_equipo(quitar)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

# ---------------- Clave de salida ----------------
st.subheader("🔐 Clave de salida del verificador")
st.markdown(
    "Se pide para salir del verificador o cambiar al modo celular, **también sin internet**. "
    "Por eso el equipo guarda una verificación cifrada de esta clave: usa una clave **distinta "
    "de tu contraseña de administrador** y de al menos "
    f"{pe.LARGO_MINIMO_CLAVE} caracteres."
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
    st.markdown("**Para instalar en un equipo**, abre esta dirección **una vez con internet**. "
                "Descarga los precios y después funciona sin conexión:")
    st.markdown(f"### {guardada.replace('https://', '').rstrip('/')}")
    try:
        import io
        import segno
        imagen = io.BytesIO()
        segno.make(guardada, error="m").save(imagen, kind="png", scale=8, border=3)
        st.image(imagen.getvalue(), caption="O escanéalo con la cámara del equipo", width=220)
    except Exception:
        pass
    with st.expander("¿El equipo no encuentra los precios?"):
        st.caption("La app ya trae la dirección de los precios (archivo docs/config.js). Si cambias de "
                   "proyecto de Supabase, actualiza ese archivo, o abre una vez este enlace largo:")
        st.code(pe.enlace_instalacion(guardada), language=None)
    st.caption("En Chrome para Android: menú ⋮ > **Instalar aplicación** (o *Agregar a la pantalla "
               "principal*) para abrirla a pantalla completa, como una app.")

# ---------------- Revisión automática ----------------
with st.expander("🔁 Revisión automática (si cambias precios directamente en Google)"):
    st.markdown("""
Si editas la hoja **directamente en Google Drive / Sheets**, la app no se entera sola. GitHub puede
revisarla **cada 30 minutos** y, si cambió, enviar los precios nuevos a los equipos. Es gratis y funciona
aunque nadie tenga abierta la app.

1. Copia **todo** el contenido de tus Secrets de Streamlit (*Manage app > Settings > Secrets*).
2. En GitHub, en tu repositorio: **Settings > Secrets and variables > Actions > New repository secret**.
   - Name: `STREAMLIT_SECRETS`
   - Secret: pega lo que copiaste. GitHub lo guarda cifrado: no se ve en el repositorio público.
3. Para probar: pestaña **Actions** > *Mantener al día los equipos sin internet* > **Run workflow**.
   En el resultado verás *Precios nuevos publicados* o *Sin cambios*.

Con el Excel no hace falta: al publicarlo en *Precios > Inventarios (Excel)* se envía al instante.
Si la revisión falla (por ejemplo, si Google pide reconectar la cuenta), GitHub te avisa por correo.
""")

# ---------------- Guía Fully Kiosk ----------------
with st.expander("🔒 Guía: dejar el verificador fijo como quiosco"):
    direccion_app = guardada or "https://tuusuario.github.io/verificadordeprecios/"
    tab_free, tab_fully = st.tabs(["FreeKiosk (gratis, recomendado)", "Fully Kiosk"])
    with tab_free:
        st.markdown(f"""
**FreeKiosk** es gratis y de código abierto. Requiere **Android 8 o más nuevo**.
Se instala con el APK de [GitHub](https://github.com/RushB-fr/freekiosk/releases).

**1. Configuración** (los nombres pueden variar un poco según la versión)
- Modo **página web** (*WebView / URL*), no el de abrir otra app.
- Dirección: `{direccion_app}`
- **PIN** de salida: para salir de FreeKiosk a Android (distinto de la clave de salida del verificador).
- Activar, si aparecen: **arrancar al encender**, **pantalla siempre encendida**, **pantalla completa**,
  orientación **horizontal**.
- **Nunca** activar opciones de *borrar caché* o *borrar datos* al iniciar o recargar: se borrarían los precios.

**2. Probar**
- Con internet: menú ✕ → debe decir la versión más nueva y **Reporte al panel: ✅**. Ponle **nombre** al equipo.
- **Sin internet**: apaga el Wi-Fi, reinicia el equipo y escanea: debe dar el precio.
- Vuelve el Wi-Fi: abajo a la derecha debe decir **Precios al día**, y en **Inicio** el equipo aparece en 🟢.

**3. Bloqueo completo (opcional)**
- Para que nadie pueda salir, FreeKiosk usa el modo *Device Owner*. Se activa una vez desde una PC con
  **ADB** y cable USB, con el equipo **sin cuentas de Google**:
  `adb shell dpm set-device-owner com.freekiosk/.DeviceAdminReceiver`

**Botón "Cerrar aplicación"** del menú ✕: con FreeKiosk no puede cerrar la app; se sale con el **PIN** de FreeKiosk.
""")
    with tab_fully:
        st.markdown(f"""
Abre **Fully Kiosk Browser** en el 2connect y entra a su **Configuración** (*Settings*).
Los nombres pueden variar un poco según la versión y el idioma.

**1. Dirección de inicio**
- *Web Content Settings* → **Start URL**: `{direccion_app}`

**2. Que nunca borre los precios guardados** (muy importante)
- *Web Auto Reload* → **desactivar** *Clear Cache*, *Clear Web Storage* y *Delete Cookies*.
- No actives ninguna opción que diga *Clear cache* o *Delete web storage* al iniciar o al recargar.
- La app ya revisa los precios sola: **no hace falta** *Auto Reload* (si lo usas, que sea cada varias horas).

**3. Pantalla completa**
- *Toolbars & Appearance*: **desactivar** *Show Address Bar*, *Show Status Bar* y *Show Navigation Bar*
  (activar *Fullscreen Mode* si aparece).

**4. Botón "Cerrar aplicación" del menú ✕**
- *Advanced Web Settings* → activar **Enable JavaScript Interface**. Así el botón puede cerrar Fully.

**5. Siempre encendido**
- *Device Management*: activar **Launch on Boot** y **Keep Screen On**.
- *Screen orientation*: **Landscape** (horizontal).

**6. Que no se pueda salir** (*Kiosk Mode*, requiere la licencia **Fully PLUS**)
- *Kiosk Mode* → **Enable Kiosk Mode** y define un **Kiosk Exit PIN**.
- Sin licencia PLUS se puede probar, pero muestra una marca de agua.

**7. Probar**
- Reinicia el 2connect: debe abrir solo la consulta de precios.
- Desconecta el Wi-Fi y escanea: debe dar el precio.
- Toca ✕ → clave de salida → ponle **nombre** al equipo (ej.: *Pasillo 3*). Aparecerá arriba, en
  *Estado de los equipos*.

**Dos claves distintas**
- **Clave de salida del verificador** (botón ✕): menú de la app (actualizar, nombre del equipo).
- **PIN de Fully**: salir de Fully a Android (configurar Wi-Fi, etc.).
""")


# ---------------- Direcciones ----------------
with st.expander("Detalles técnicos"):
    st.markdown("Archivo que revisan los equipos:")
    st.code(pe.url_publica("estado.json"), language=None)
    st.caption("Es público a propósito: contiene los mismos precios que ya muestra la Consulta Móvil, "
               "y la clave de salida solo como verificación PBKDF2 (no la clave).")
