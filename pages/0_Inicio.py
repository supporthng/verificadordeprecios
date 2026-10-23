"""Inicio: resumen del sistema y accesos directos para el personal."""
from datetime import datetime, time as hora, timezone
from zoneinfo import ZoneInfo

import requests
import streamlit as st

from auth_usuarios import allowed, current_user, es_admin
from supabase_cliente import cabeceras, url

usuario = current_user()
ZONA = ZoneInfo("America/Santo_Domingo")
admin = es_admin(usuario) and not usuario.get("must_change_password")

st.title("🏠 Inicio")
ahora = datetime.now(ZONA)
saludo = "Buenos días" if ahora.hour < 12 else ("Buenas tardes" if ahora.hour < 19 else "Buenas noches")
st.caption(f"{saludo}, **{usuario.get('username', '')}** · {ahora:%d/%m/%Y}")


def _contar(tabla, filtros):
    """Cantidad de filas (sin descargarlas), o None si no se pudo."""
    try:
        r = requests.head(f"{url()}/rest/v1/{tabla}", params={"select": "*", **filtros},
                          headers=cabeceras(None, {"Prefer": "count=exact", "Range": "0-0"}), timeout=15)
        total = r.headers.get("Content-Range", "").rsplit("/", 1)[-1]
        return int(total) if total.isdigit() else None
    except requests.RequestException:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def resumen():
    import publicar_equipos as pe
    datos = {"fuente": None, "inventario": None, "productos": None, "hoy": None, "no_encontrados": None,
             "equipos": None, "estado": None, "avisos": []}
    try:
        datos["fuente"] = pe.fuente_activa()
    except Exception as exc:
        datos["avisos"].append(("error", "No se pudo leer la fuente activa: " + str(exc)))
    try:
        r = requests.get(f"{url()}/rest/v1/price_inventories", headers=cabeceras(), timeout=15,
                         params={"select": "id,name", "is_active": "eq.true", "limit": 1})
        activo = (r.json() if r.ok else []) or []
        if activo:
            datos["inventario"] = activo[0]["name"]
            datos["productos"] = _contar("price_inventory_items", {"inventory_id": f"eq.{activo[0]['id']}"})
        elif datos["fuente"] == "local":
            datos["avisos"].append(("error", "No hay un inventario activo: la consulta no encontrará productos. "
                                             "Actívalo en Precios > Inventarios (Excel)."))
    except (requests.RequestException, ValueError):
        pass
    inicio = datetime.combine(datetime.now(ZONA).date(), hora.min, tzinfo=ZONA).astimezone(timezone.utc)
    desde = {"created_at": f"gte.{inicio.isoformat()}"}
    datos["hoy"] = _contar("price_lookup_log", desde)
    datos["no_encontrados"] = _contar("price_lookup_log", {**desde, "found": "eq.false"})

    datos["estado"] = pe.estado()
    try:
        datos["equipos"] = pe.equipos()
    except Exception:
        datos["equipos"] = None   # sin la migración 005
    if datos["fuente"] == "external" and datos["estado"]:
        datos["avisos"].append(("warning", "La fuente activa es SQL Server: los equipos sin internet siguen "
                                           "con los últimos precios que recibieron."))
    if datos["estado"] and not datos["estado"].get("salida"):
        datos["avisos"].append(("warning", "Falta la clave de salida del verificador (Equipos sin internet)."))
    return datos


with st.spinner("Cargando resumen…"):
    d = resumen()

NOMBRE_FUENTE = {"local": "Excel", "google": "Google", "external": "SQL Server"}

# ---------------- Avisos ----------------
equipos = d["equipos"] or []
version = (d["estado"] or {}).get("version")


def _minutos(iso):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60
    except (TypeError, ValueError):
        return 1e9


atrasados = [e for e in equipos if version and e.get("precios_version") != version and _minutos(e.get("ultima_vez")) < 24 * 60]
if admin and atrasados:
    d["avisos"].append(("warning", "Equipos con precios anteriores: " + ", ".join(e["nombre"] for e in atrasados)
                                   + ". Se pondrán al día solos en cuanto tengan internet."))
for tipo, texto in d["avisos"]:
    (st.error if tipo == "error" else st.warning)(texto)

# ---------------- Resumen ----------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Fuente de precios", NOMBRE_FUENTE.get(d["fuente"], "—"),
          help=("Inventario activo: " + d["inventario"]) if d["inventario"] and d["fuente"] == "local" else None)
c2.metric("Productos", f"{d['productos']:,}" if d["productos"] is not None and d["fuente"] == "local"
          else (f"{(d['estado'] or {}).get('productos', 0):,}" if d["estado"] else "—"))
c3.metric("Consultas hoy", f"{d['hoy']:,}" if d["hoy"] is not None else "—")
c4.metric("No encontrados hoy", f"{d['no_encontrados']:,}" if d["no_encontrados"] is not None else "—",
          help="Códigos escaneados que no están en el inventario. Revísalos en Registro de consultas.")

if admin and d["equipos"] is not None:
    en_linea = sum(1 for e in equipos if _minutos(e.get("ultima_vez")) < 15)
    st.caption(f"📴 Equipos: **{en_linea}** conectados ahora de **{len(equipos)}**"
               + (f" · **{len(equipos) - len(atrasados)}** con los precios al día" if equipos else ""))

# ---------------- Accesos directos ----------------
st.subheader("Accesos directos")
ACCESOS = [
    ("cargar_archivo", "pages/10_Inventarios.py", "Subir precios (Excel)", "📚",
     "Cargar un Excel nuevo o activar otro inventario."),
    ("consultar_base", "pages/13_Registro_Consultas.py", "Registro de consultas", "📊",
     "Qué se consulta y qué códigos no se encuentran."),
    ("consultar_base", "pages/4_Listado_Productos.py", "Buscar productos", "📋",
     "Ver el catálogo y buscar por nombre o código."),
    ("admin", "pages/14_Equipos_sin_internet.py", "Equipos sin internet", "📴",
     "Estado de los verificadores y publicación de precios."),
    ("logo", "pages/3_Logo_del_negocio.py", "Logo y QR", "🖼️", "Logo del negocio y QR para celulares."),
    ("usuarios", "pages/5_Administrador_Usuarios.py", "Usuarios", "👥", "Crear usuarios y permisos."),
    (None, "consulta_precios.py", "Pantalla del verificador", "🏷️", "Ver la consulta como la ve el cliente."),
    (None, "pages/8_Escaner_Movil.py", "Escáner móvil", "📱", "Consultar con la cámara del celular."),
]
visibles = [a for a in ACCESOS if a[0] is None or (admin if a[0] == "admin" else allowed(usuario, a[0]))]
columnas = st.columns(2)
for n, (_, ruta, titulo, icono, detalle) in enumerate(visibles):
    with columnas[n % 2].container(border=True):
        st.page_link(ruta, label=titulo, icon=icono)
        st.caption(detalle)

if st.button("🔄 Actualizar resumen"):
    resumen.clear()
    st.rerun()
