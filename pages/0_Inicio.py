"""Inicio: panel con el estado del sistema, la actividad reciente y accesos directos."""
import html
from datetime import datetime, time as hora, timedelta, timezone
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import requests
import streamlit as st

from auth_usuarios import allowed, current_user, es_admin
from supabase_cliente import cabeceras, url

usuario = current_user()
ZONA = ZoneInfo("America/Santo_Domingo")
admin = es_admin(usuario) and not usuario.get("must_change_password")
ve_registro = allowed(usuario, "consultar_base")
AZUL, NARANJA = "#0757d4", "#e8590c"      # validados: distinguibles también con daltonismo
NOMBRE_FUENTE = {"local": "Excel", "google": "Google", "external": "SQL Server"}


# ---------------------------------------------------------------- datos
def _contar(tabla, filtros):
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
    d = {"fuente": None, "inventario": None, "productos": None, "consultas": None,
         "equipos": None, "estado": None, "avisos": []}
    try:
        d["fuente"] = pe.fuente_activa()
    except Exception as exc:
        d["avisos"].append(("error", "No se pudo leer la fuente activa: " + str(exc)))
    try:
        r = requests.get(f"{url()}/rest/v1/price_inventories", headers=cabeceras(), timeout=15,
                         params={"select": "id,name", "is_active": "eq.true", "limit": 1})
        activo = (r.json() if r.ok else []) or []
        if activo:
            d["inventario"] = activo[0]["name"]
            d["productos"] = _contar("price_inventory_items", {"inventory_id": f"eq.{activo[0]['id']}"})
        elif d["fuente"] == "local":
            d["avisos"].append(("error", "No hay un inventario activo: la consulta no encontrará productos. "
                                         "Actívalo en Precios > Inventarios (Excel)."))
    except (requests.RequestException, ValueError):
        pass
    try:   # últimos 7 días del registro (solo las columnas necesarias)
        import registro_consultas
        inicio = datetime.combine(datetime.now(ZONA).date() - timedelta(days=6), hora.min, tzinfo=ZONA)
        filas = registro_consultas.leer(inicio.astimezone(timezone.utc), limite=60000)
        d["consultas"] = [{"t": f["created_at"], "codigo": f["barcode"], "ok": f["found"],
                           "producto": f.get("product_name"), "precio": f.get("price"),
                           "canal": f.get("channel")} for f in filas]
    except Exception:
        d["consultas"] = None
    d["estado"] = pe.estado()
    try:
        d["equipos"] = pe.equipos()
    except Exception:
        d["equipos"] = None
    if d["fuente"] == "external" and d["estado"]:
        info = pe.catalogo_externo_info()
        try:
            atraso = (datetime.now(timezone.utc) - datetime.fromisoformat(info["generado"])).total_seconds() / 60
        except (TypeError, ValueError, KeyError):
            atraso = None
        if atraso is None:
            d["avisos"].append(("warning", "SQL Server: el conector de Windows todavía no envió el catálogo a los "
                                           "equipos. Actualízalo a la versión 5."))
        elif atraso > 60:
            d["avisos"].append(("warning", f"SQL Server: el conector no envía el catálogo desde hace "
                                           f"{int(atraso // 60)} h. Revisa que la PC del conector esté encendida."))
    if d["estado"] and not d["estado"].get("salida"):
        d["avisos"].append(("warning", "Falta la clave de salida del verificador (Equipos sin internet)."))
    return d


def _minutos(iso):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60
    except (TypeError, ValueError):
        return 1e9


def _hace(minutos):
    if minutos < 1:
        return "ahora"
    if minutos < 60:
        return f"hace {int(minutos)} min"
    if minutos < 48 * 60:
        return f"hace {int(minutos // 60)} h"
    return f"hace {int(minutos // 1440)} días"


with st.spinner("Cargando el panel…"):
    d = resumen()

ahora = datetime.now(ZONA)
hoy = ahora.date()
df = pd.DataFrame(d["consultas"] or [], columns=["t", "codigo", "ok", "producto", "precio", "canal"])
if not df.empty:
    df["fecha"] = pd.to_datetime(df["t"], utc=True).dt.tz_convert(ZONA)
    df["dia"] = df["fecha"].dt.date
de_hoy = df[df["dia"] == hoy] if not df.empty else df
de_ayer = df[df["dia"] == hoy - timedelta(days=1)] if not df.empty else df

equipos = d["equipos"] or []
version = (d["estado"] or {}).get("version")
recientes = [e for e in equipos if _minutos(e.get("ultima_vez")) < 24 * 60]
atrasados = [e for e in recientes if version and e.get("precios_version") != version]
conectados = [e for e in equipos if _minutos(e.get("ultima_vez")) < 15]
if admin and atrasados:
    d["avisos"].append(("warning", "Con precios anteriores: " + ", ".join(e["nombre"] for e in atrasados)
                                   + ". Se pondrán al día solos en cuanto tengan internet."))

# ---------------------------------------------------------------- estilos
st.markdown("""
<style>
.panel-hero {
  background: linear-gradient(115deg, #0b2f5e 0%, #0757d4 70%, #2f7bf0 100%);
  color: #fff; border-radius: 18px; padding: 22px 26px; margin-bottom: 18px;
  display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap;
  box-shadow: 0 10px 30px rgba(7, 87, 212, .18);
}
.panel-hero h1 { color: #fff !important; font-size: clamp(22px, 3vw, 32px) !important; margin: 0 !important; padding: 0 !important; font-weight: 800; }
.panel-hero p { margin: 4px 0 0; color: #d6e6ff; font-size: 15px; }
.panel-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip { background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.25); color: #fff;
        border-radius: 999px; padding: 6px 12px; font-size: 14px; font-weight: 600; white-space: nowrap; }
.chip.ok::before { content: "●"; color: #4ade80; margin-right: 6px; }
.chip.aviso::before { content: "●"; color: #fbbf24; margin-right: 6px; }
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 6px; }
@media (max-width: 900px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.kpi { background: #fff; border: 1px solid #e3eaf5; border-radius: 16px; padding: 16px 18px;
       box-shadow: 0 2px 10px rgba(16, 43, 80, .05); }
.kpi-top { display: flex; align-items: center; gap: 10px; color: #5b6b84; font-size: 14px; font-weight: 600; }
.kpi-icono { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; font-size: 18px; background: #eef4ff; }
.kpi-valor { font-size: clamp(26px, 2.6vw, 34px); font-weight: 800; color: #0d2d58; margin-top: 10px; line-height: 1.1;
             font-variant-numeric: tabular-nums; }
.kpi-sub { color: #7c8ca6; font-size: 13px; margin-top: 4px; }
.kpi-sub .sube { color: #15803d; font-weight: 700; }
.kpi-sub .baja { color: #b45309; font-weight: 700; }
.tarjeta { background: #fff; border: 1px solid #e3eaf5; border-radius: 16px; padding: 16px 18px;
           box-shadow: 0 2px 10px rgba(16, 43, 80, .05); }
.tarjeta h3 { font-size: 16px !important; color: #0d2d58 !important; margin: 0 0 10px !important; padding: 0 !important; font-weight: 700; }
.fila { display: flex; justify-content: space-between; align-items: center; gap: 10px;
        padding: 9px 0; border-top: 1px solid #f0f4fa; font-size: 14px; color: #102b50; }
.fila:first-of-type { border-top: 0; }
.fila .codigo { font-family: ui-monospace, Menlo, Consolas, monospace; font-weight: 600; }
.fila .suave { color: #7c8ca6; font-size: 13px; }
.insignia { background: #fff4ec; color: #9a3412; border-radius: 999px; padding: 2px 10px; font-weight: 700; font-size: 13px; white-space: nowrap; }
.insignia.ok { background: #ecfdf3; color: #166534; }
.punto { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 8px; }
.vacio { color: #7c8ca6; font-size: 14px; padding: 8px 0; }
.top-fila { display: grid; grid-template-columns: 28px 1fr auto; gap: 10px; align-items: center;
            padding: 9px 0; border-top: 1px solid #f0f4fa; }
.top-fila:first-of-type { border-top: 0; }
.top-n { width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center;
         background: #eef4ff; color: #0757d4; font-weight: 800; font-size: 13px; }
.top-fila:first-of-type .top-n { background: #0757d4; color: #fff; }
.top-nombre { font-weight: 700; color: #0d2d58; font-size: 14px; line-height: 1.25;
              overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.top-detalle { color: #7c8ca6; font-size: 12.5px; }
.top-barra { height: 5px; border-radius: 3px; background: #eef2f8; margin-top: 5px; overflow: hidden; }
.top-barra span { display: block; height: 100%; border-radius: 3px; background: #0757d4; }
.top-veces { text-align: right; font-weight: 800; color: #0d2d58; font-size: 15px; font-variant-numeric: tabular-nums; }
.top-veces small { display: block; color: #7c8ca6; font-weight: 600; font-size: 11.5px; }
/* El gráfico con el mismo estilo de tarjeta */
.st-key-tarjeta_grafico { background: #fff; border: 1px solid #e3eaf5; border-radius: 16px;
  padding: 16px 18px 6px; box-shadow: 0 2px 10px rgba(16, 43, 80, .05); }
.st-key-tarjeta_grafico p strong { color: #0d2d58; font-size: 16px; }
/* Accesos directos como mosaicos */
.st-key-accesos [data-testid="stPageLink"] a {
  background: #fff; border: 1px solid #e3eaf5; border-radius: 14px; padding: 14px 16px !important;
  box-shadow: 0 2px 10px rgba(16, 43, 80, .05); transition: transform .12s, box-shadow .12s, border-color .12s;
  min-height: 58px; align-items: center;
}
.st-key-accesos [data-testid="stPageLink"] a:hover {
  transform: translateY(-2px); border-color: #b9cff5; box-shadow: 0 8px 20px rgba(7, 87, 212, .12);
}
.st-key-accesos [data-testid="stPageLink"] p { font-weight: 700; color: #0d2d58; font-size: 15px; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- encabezado
saludo = "Buenos días" if ahora.hour < 12 else ("Buenas tardes" if ahora.hour < 19 else "Buenas noches")
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
fecha_larga = f"{DIAS[ahora.weekday()]} {ahora.day} de {MESES[ahora.month - 1]}"
n_avisos = len(d["avisos"])
chips = [f'<span class="chip {"aviso" if n_avisos else "ok"}">'
         + (f"{n_avisos} aviso{'s' if n_avisos != 1 else ''}" if n_avisos else "Todo en orden") + "</span>",
         f'<span class="chip">Fuente: {html.escape(NOMBRE_FUENTE.get(d["fuente"], "—"))}</span>']
if d["inventario"] and d["fuente"] == "local":
    chips.append(f'<span class="chip">Inventario: {html.escape(d["inventario"])}</span>')
st.markdown(
    f'<div class="panel-hero"><div><h1>{saludo}, {html.escape(str(usuario.get("username", "")))}</h1>'
    f'<p>{fecha_larga.capitalize()} · {ahora:%I:%M %p}</p></div>'
    f'<div class="panel-chips">{"".join(chips)}</div></div>', unsafe_allow_html=True)

for tipo, texto in d["avisos"]:
    (st.error if tipo == "error" else st.warning)(texto, icon="⚠️")

# ---------------------------------------------------------------- indicadores
def _kpi(icono, titulo, valor, sub=""):
    return (f'<div class="kpi"><div class="kpi-top"><span class="kpi-icono">{icono}</span>{titulo}</div>'
            f'<div class="kpi-valor">{valor}</div><div class="kpi-sub">{sub}</div></div>')


productos = (d["productos"] if d["fuente"] == "local" else (d["estado"] or {}).get("productos"))
n_hoy, n_ayer = len(de_hoy), len(de_ayer)
if d["consultas"] is None:
    sub_hoy = "registro no disponible"
elif n_ayer:
    cambio = (n_hoy - n_ayer) / n_ayer
    sub_hoy = (f'<span class="{"sube" if cambio >= 0 else "baja"}">{"▲" if cambio >= 0 else "▼"} '
               f'{abs(cambio):.0%}</span> vs. ayer ({n_ayer:,})')
else:
    sub_hoy = "ayer: sin consultas"
pct = (de_hoy["ok"].mean() if n_hoy else None)
no_enc_hoy = int((~de_hoy["ok"]).sum()) if n_hoy else 0
tarjetas = [
    _kpi("📦", "Productos", f"{productos:,}" if isinstance(productos, int) else "—",
         html.escape(NOMBRE_FUENTE.get(d["fuente"], ""))),
    _kpi("🔎", "Consultas hoy", f"{n_hoy:,}" if d["consultas"] is not None else "—", sub_hoy),
    _kpi("✅", "Encontrados hoy", f"{pct:.0%}" if pct is not None else "—",
         f"{no_enc_hoy:,} código{'s' if no_enc_hoy != 1 else ''} sin precio" if n_hoy else "sin consultas todavía"),
]
if admin:
    tarjetas.append(_kpi("📴", "Equipos conectados",
                         f"{len(conectados)} / {len(equipos)}" if d["equipos"] is not None else "—",
                         ("todos con precios al día" if equipos and not atrasados else
                          f"{len(atrasados)} con precios anteriores" if atrasados else
                          "aún no reporta ninguno" if d["equipos"] is not None else "falta la migración 005")))
else:
    tarjetas.append(_kpi("🧾", "Consultas 7 días", f"{len(df):,}" if d["consultas"] is not None else "—", ""))
st.markdown(f'<div class="kpis">{"".join(tarjetas)}</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------- actividad
if ve_registro:
    izq, der = st.columns([3, 2], gap="medium")
    with izq.container(key="tarjeta_grafico"):
        st.markdown("**Consultas de los últimos 7 días**")
        dias = pd.DataFrame({"dia": [hoy - timedelta(days=i) for i in range(6, -1, -1)]})
        if not df.empty:
            por_dia = df.groupby("dia").agg(total=("ok", "size"), encontrados=("ok", "sum")).reset_index()
            dias = dias.merge(por_dia, on="dia", how="left").fillna(0)
        else:
            dias["total"], dias["encontrados"] = 0, 0
        dias["no_encontrados"] = dias["total"] - dias["encontrados"]
        dias["etiqueta"] = [("Hoy" if x == hoy else f"{DIAS[x.weekday()][:3]} {x.day}") for x in dias["dia"]]
        dias["fecha"] = [f"{DIAS[x.weekday()]} {x.day}/{x.month}" for x in dias["dia"]]
        orden = list(dias["etiqueta"])
        largo = dias.melt(id_vars=["etiqueta", "fecha", "total"], value_vars=["encontrados", "no_encontrados"],
                          var_name="resultado", value_name="consultas")
        largo["resultado"] = largo["resultado"].map({"encontrados": "Encontrados", "no_encontrados": "No encontrados"})
        grafico = (
            alt.Chart(largo)
            .mark_bar(size=22, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, stroke="#ffffff", strokeWidth=2)
            .encode(
                x=alt.X("etiqueta:N", sort=orden, title=None, axis=alt.Axis(labelAngle=0, labelColor="#5b6b84",
                                                                            domainColor="#e3eaf5", ticks=False)),
                y=alt.Y("sum(consultas):Q", title=None, axis=alt.Axis(gridColor="#eef2f8", domain=False,
                                                                       ticks=False, labelColor="#7c8ca6",
                                                                       tickMinStep=1, format="~s")),
                color=alt.Color("resultado:N", title=None,
                                scale=alt.Scale(domain=["Encontrados", "No encontrados"], range=[AZUL, NARANJA]),
                                legend=alt.Legend(orient="top", direction="horizontal", labelColor="#102b50",
                                                  symbolType="square", offset=4, padding=0)),
                order=alt.Order("resultado:N", sort="ascending"),
                tooltip=[alt.Tooltip("fecha:N", title="Día"), alt.Tooltip("resultado:N", title="Resultado"),
                         alt.Tooltip("consultas:Q", title="Consultas", format=","),
                         alt.Tooltip("total:Q", title="Total del día", format=",")],
            )
            .properties(height=210, padding={"top": 0, "left": 4, "right": 4, "bottom": 4})
            .configure_view(strokeWidth=0)
        )
        st.altair_chart(grafico, use_container_width=True)

    with der:
        if not df.empty and (~df["ok"]).any():
            top = (df[~df["ok"]].groupby("codigo").agg(veces=("codigo", "size"), ultima=("fecha", "max"))
                   .sort_values(["veces", "ultima"], ascending=False).head(5))
            filas = "".join(
                f'<div class="fila"><div><div class="codigo">{html.escape(str(c))}</div>'
                f'<div class="suave">última vez {r.ultima:%d/%m %I:%M %p}</div></div>'
                f'<span class="insignia">{int(r.veces)} {"vez" if r.veces == 1 else "veces"}</span></div>'
                for c, r in top.iterrows())
        else:
            filas = '<div class="vacio">🎉 Todos los códigos consultados en 7 días tienen precio.</div>'
        st.markdown(f'<div class="tarjeta"><h3>❌ Códigos sin precio (7 días)</h3>{filas}</div>',
                    unsafe_allow_html=True)
        st.page_link("pages/13_Registro_Consultas.py", label="Ver el registro completo", icon="📊")

# ---------------------------------------------------------------- más consultados
def _mas_consultados():
    encontrados = df[df["ok"]] if not df.empty else df
    if encontrados.empty:
        cuerpo = '<div class="vacio">Todavía no hay productos consultados en los últimos 7 días.</div>'
    else:
        top = (encontrados.sort_values("fecha").groupby("codigo")
               .agg(veces=("codigo", "size"), producto=("producto", "last"), precio=("precio", "last"))
               .sort_values("veces", ascending=False).head(5))
        maximo = int(top["veces"].max()) or 1
        filas = []
        for n, (codigo, r) in enumerate(top.iterrows(), start=1):
            try:
                precio = f"RD$ {float(r.precio):,.2f}"
            except (TypeError, ValueError):
                precio = ""
            filas.append(
                f'<div class="top-fila"><span class="top-n">{n}</span><div style="min-width:0">'
                f'<div class="top-nombre" title="{html.escape(str(r.producto or ""))}">{html.escape(str(r.producto or "—"))}</div>'
                f'<div class="top-detalle">{html.escape(str(codigo))}{" · " + precio if precio else ""}</div>'
                f'<div class="top-barra"><span style="width:{max(6, round(100 * r.veces / maximo))}%"></span></div></div>'
                f'<div class="top-veces">{int(r.veces):,}<small>{"consulta" if r.veces == 1 else "consultas"}</small></div></div>')
        cuerpo = "".join(filas)
    st.markdown(f'<div class="tarjeta" style="margin-top:14px"><h3>🔝 Productos más consultados (7 días)</h3>{cuerpo}</div>',
                unsafe_allow_html=True)


if ve_registro and admin and d["equipos"] is not None:
    col_top, col_equipos = st.columns(2, gap="medium")
else:
    col_top = col_equipos = st.container()
if ve_registro:
    with col_top:
        _mas_consultados()

# ---------------------------------------------------------------- equipos
if admin and d["equipos"] is not None:
    if equipos:
        filas = []
        for e in equipos[:6]:
            m = _minutos(e.get("ultima_vez"))
            color = "#16a34a" if m < 15 else ("#d97706" if m < 24 * 60 else "#94a3b8")
            estado_txt = "Conectado" if m < 15 else ("Hoy" if m < 24 * 60 else "Sin conexión")
            al_dia = version and e.get("precios_version") == version
            filas.append(
                f'<div class="fila"><div><span class="punto" style="background:{color}"></span>'
                f'<strong>{html.escape(str(e.get("nombre") or "Equipo"))}</strong>'
                f'<div class="suave" style="margin-left:17px">{estado_txt} · {_hace(m)}</div></div>'
                f'<span class="insignia {"ok" if al_dia else ""}">{"Precios al día" if al_dia else "Precios anteriores"}</span></div>')
        cuerpo = "".join(filas)
    else:
        cuerpo = ('<div class="vacio">Ningún verificador ha reportado todavía. Aparecen al abrir la app sin '
                  'internet versión 1.1.0 o más nueva.</div>')
    with col_equipos:
        st.markdown(f'<div class="tarjeta" style="margin-top:14px"><h3>📴 Verificadores</h3>{cuerpo}</div>',
                    unsafe_allow_html=True)

# ---------------------------------------------------------------- accesos directos
st.markdown("#### Accesos directos")
ACCESOS = [
    ("cargar_archivo", "pages/10_Inventarios.py", "Subir precios (Excel)", "📚"),
    ("consultar_base", "pages/4_Listado_Productos.py", "Buscar productos", "📋"),
    ("admin", "pages/14_Equipos_sin_internet.py", "Equipos sin internet", "📴"),
    ("logo", "pages/3_Logo_del_negocio.py", "Logo y QR", "🖼️"),
    ("logo", "pages/12_Apariencia.py", "Apariencia", "🎨"),
    ("usuarios", "pages/5_Administrador_Usuarios.py", "Usuarios", "👥"),
    (None, "consulta_precios.py", "Pantalla del verificador", "🏷️"),
    (None, "pages/8_Escaner_Movil.py", "Escáner móvil", "📱"),
]
visibles = [a for a in ACCESOS if a[0] is None or (admin if a[0] == "admin" else allowed(usuario, a[0]))]
with st.container(key="accesos"):
    columnas = st.columns(4)
    for n, (_, ruta, titulo, icono) in enumerate(visibles):
        with columnas[n % 4]:
            st.page_link(ruta, label=titulo, icon=icono)

st.caption(f"Actualizado {ahora:%I:%M %p} · se renueva cada minuto")
if st.button("🔄 Actualizar ahora"):
    resumen.clear()
    st.rerun()
