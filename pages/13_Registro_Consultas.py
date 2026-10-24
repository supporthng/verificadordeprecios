"""Registro de consultas: qué se busca, qué NO se encuentra y qué productos se consultan más."""
from datetime import datetime, time as hora, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from auth_usuarios import require, es_admin
import registro_consultas as registro

usuario = require("consultar_base")
ZONA = ZoneInfo("America/Santo_Domingo")
CANALES = {"verificador": "Verificador (pantalla)", "movil-camara": "Celular · cámara en vivo",
           "movil-manual": "Celular · manual / Bluetooth", "movil-foto": "Celular · foto", "movil": "Celular",
           "offline-verificador": "Verificador sin internet", "offline-movil": "Celular sin internet"}
FUENTES = {"local": "Excel (inventario)", "google": "Google Drive / Sheets", "external": "SQL Server"}

st.title("📊 Registro de consultas")
st.caption("Cada consulta de precio queda registrada: sirve para encontrar productos que faltan "
           "en el inventario o tienen el código mal cargado.")

# Sucursales: el encargado ve solo la suya; el usuario general elige (o ve todas).
import sucursales
try:
    lista_suc = sucursales.listar()
except RuntimeError:
    lista_suc = []
NOMBRE_SUC = {s["codigo"]: s["nombre"] for s in lista_suc}
filtro_suc = None
if usuario.get("sucursal_id"):
    propia = sucursales.por_id(usuario["sucursal_id"])
    filtro_suc = propia["codigo"] if propia else "—"
    st.caption(f"🏬 Sucursal: **{propia['nombre'] if propia else '—'}**")
col_periodo, col_suc = st.columns([3, 1.3]) if (lista_suc and not filtro_suc) else (st.container(), None)
with col_periodo:
    periodo = st.radio("Período", ["Hoy", "Últimos 7 días", "Últimos 30 días", "Últimos 90 días"],
                       index=1, horizontal=True)
if col_suc is not None:
    elegida = col_suc.selectbox("Sucursal", [None, registro.PRINCIPAL] + list(NOMBRE_SUC),
                                format_func=lambda c: "Todas" if c is None
                                else "🏠 Principal" if c == registro.PRINCIPAL else NOMBRE_SUC[c])
    filtro_suc = elegida
ahora = datetime.now(ZONA)
inicio_local = datetime.combine(ahora.date(), hora.min, tzinfo=ZONA) - timedelta(
    days={"Hoy": 0, "Últimos 7 días": 6, "Últimos 30 días": 29, "Últimos 90 días": 89}[periodo])


@st.cache_data(ttl=60, show_spinner=False)
def cargar(desde_utc_iso, sucursal=None):
    return registro.leer(datetime.fromisoformat(desde_utc_iso), sucursal=sucursal)


try:
    with st.spinner("Cargando registro…"):
        filas = cargar(inicio_local.astimezone(timezone.utc).isoformat(timespec="minutes"), filtro_suc)
except Exception as exc:
    if "price_lookup_log" in str(exc) or "42P01" in str(exc) or "404" in str(exc):
        st.warning("El registro todavía no está instalado. Ejecuta **sql/MIGRACION_003_registro_consultas.sql** "
                   "en Supabase > SQL Editor; desde ese momento se anotarán las consultas.")
    else:
        st.error("No se pudo leer el registro: " + str(exc))
    st.stop()

if not filas:
    st.info("No hay consultas registradas en este período.")
    st.stop()

df = pd.DataFrame(filas)
df["fecha"] = pd.to_datetime(df["created_at"], utc=True).dt.tz_convert(ZONA)
df["canal"] = df["channel"].map(CANALES).fillna(df["channel"].fillna("—"))
df["fuente"] = df["source"].map(FUENTES).fillna(df["source"].fillna("—"))
total = len(df)
encontrados = int(df["found"].sum())
no_enc = df[~df["found"]]

# ---------------- Resumen ----------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Consultas", f"{total:,}")
c2.metric("Encontrados", f"{encontrados / total:.0%}")
c3.metric("No encontrados", f"{len(no_enc):,}")
c4.metric("Códigos distintos sin precio", f"{no_enc['barcode'].nunique():,}")

col_a, col_b = st.columns(2)
with col_a:
    st.markdown("**Consultas por día**")
    por_dia = (df.assign(dia=df["fecha"].dt.strftime("%d/%m"), orden=df["fecha"].dt.date)
                 .groupby(["orden", "dia"]).agg(Encontrados=("found", "sum"), Total=("found", "size"))
                 .reset_index())
    por_dia["No encontrados"] = por_dia["Total"] - por_dia["Encontrados"]
    st.bar_chart(por_dia.set_index("dia")[["Encontrados", "No encontrados"]],
                 color=["#0757d4", "#dc2626"], stack=True)
if lista_suc and not filtro_suc and "sucursal" in df:
    st.markdown("**Por sucursal**")
    por_suc = (df.assign(Sucursal=df["sucursal"].map(NOMBRE_SUC).fillna("🏠 Principal"))
                 .groupby("Sucursal").agg(Consultas=("found", "size"), Encontrados=("found", "sum"))
                 .sort_values("Consultas", ascending=False))
    por_suc["% encontrados"] = (por_suc["Encontrados"] / por_suc["Consultas"]).map("{:.0%}".format)
    st.dataframe(por_suc[["Consultas", "% encontrados"]], use_container_width=True)
with col_b:
    st.markdown("**Por canal**")
    por_canal = (df.groupby("canal").agg(Consultas=("found", "size"), Encontrados=("found", "sum"))
                   .sort_values("Consultas", ascending=False))
    por_canal["% encontrados"] = (por_canal["Encontrados"] / por_canal["Consultas"]).map("{:.0%}".format)
    st.dataframe(por_canal[["Consultas", "% encontrados"]], use_container_width=True)


def _fmt(serie):
    return serie.dt.strftime("%d/%m/%Y %H:%M")


# ---------------- Códigos no encontrados ----------------
st.subheader("❌ Códigos no encontrados")
if no_enc.empty:
    st.success("Todas las consultas del período encontraron su producto.")
else:
    tabla_ne = (no_enc.groupby("barcode")
                .agg(Veces=("barcode", "size"), Ultima=("fecha", "max"),
                     Canales=("canal", lambda c: ", ".join(sorted(set(c)))))
                .sort_values(["Veces", "Ultima"], ascending=[False, False]).reset_index())
    tabla_ne["Ultima"] = _fmt(tabla_ne["Ultima"])
    tabla_ne = tabla_ne.rename(columns={"barcode": "Código", "Ultima": "Última consulta"})
    st.caption("Ordenados por cantidad de consultas. Revisa en tu inventario si el producto falta "
               "o si su código está cargado de otra forma.")
    st.dataframe(tabla_ne, hide_index=True, use_container_width=True,
                 column_config={"Código": st.column_config.TextColumn("Código")})
    # ="0087..." hace que Excel conserve los ceros iniciales del código al abrir el CSV.
    para_excel = tabla_ne.assign(Código=tabla_ne["Código"].map(lambda c: f'="{c}"'))
    st.download_button("⬇️ Descargar no encontrados (Excel / CSV)",
                       para_excel.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"codigos_no_encontrados_{ahora:%Y%m%d}.csv", mime="text/csv")

# ---------------- Más consultados ----------------
st.subheader("🔝 Productos más consultados")
enc = df[df["found"]]
if enc.empty:
    st.info("No hay productos encontrados en este período.")
else:
    top = (enc.sort_values("fecha").groupby("barcode")
           .agg(Producto=("product_name", "last"), Veces=("barcode", "size"), Precio=("price", "last"))
           .sort_values("Veces", ascending=False).head(25).reset_index()
           .rename(columns={"barcode": "Código"}))
    st.dataframe(top, hide_index=True, use_container_width=True,
                 column_config={"Precio": st.column_config.NumberColumn("Último precio", format="RD$ %.2f")})

with st.expander("Últimas 200 consultas"):
    ultimas = df.head(200).assign(Fecha=lambda d: _fmt(d["fecha"]),
                                  Resultado=lambda d: d["found"].map({True: "✅ Encontrado", False: "❌ No encontrado"}))
    st.dataframe(ultimas[["Fecha", "barcode", "Resultado", "product_name", "price", "canal", "fuente"]]
                 .rename(columns={"barcode": "Código", "product_name": "Producto", "price": "Precio",
                                  "canal": "Canal", "fuente": "Fuente"}),
                 hide_index=True, use_container_width=True)

# ---------------- Limpieza (solo administradores) ----------------
if es_admin(usuario) and not usuario.get("sucursal_id"):
    with st.expander("🧹 Borrar registros antiguos"):
        dias = st.number_input("Borrar consultas con más de (días)", min_value=7, max_value=3650, value=90, step=1)
        confirmar = st.checkbox(f"Confirmo que quiero borrar las consultas con más de {int(dias)} días")
        if st.button("Borrar", disabled=not confirmar):
            try:
                borrados = registro.borrar_anteriores(int(dias))
                cargar.clear()
                st.success("Registros antiguos borrados" + (f": {borrados:,}." if borrados is not None else "."))
            except Exception as exc:
                st.error("No se pudieron borrar: " + str(exc))
