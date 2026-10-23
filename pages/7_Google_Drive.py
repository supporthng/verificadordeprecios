"""Conexión individual de Google Drive y Google Sheets para la instalación."""
import streamlit as st
from auth_usuarios import current_user, allowed
from google_oauth_source import (auth_url, signed_state, verify_state, exchange_code, connect, config, file_id,
                                 read_file, catalog, activate, api, setting)

st.title("☁️ Google Drive y Google Sheets")
user=current_user()
if not allowed(user,"configurar"):
    st.error("Acceso exclusivo para administración.")
    st.stop()
st.caption("Cada instalación puede conectar la cuenta Google de su cliente. No se solicita contraseña de Google.")

from google_oauth_source import faltantes


def _equipos():
    """Si Google es la fuente activa, enviar los precios a los equipos sin internet."""
    try:
        import publicar_equipos
        if publicar_equipos.fuente_activa() != "google":
            return
        ok, res = publicar_equipos.actualizar_si_publicado()
        if ok:
            st.caption(f"📴 Equipos sin internet: {res['productos']:,} productos de Google publicados.")
        elif isinstance(res, str):
            st.warning("No se pudo actualizar los equipos sin internet: " + res)
    except Exception as exc:
        st.warning("No se pudo actualizar los equipos sin internet: " + str(exc))

_faltan = faltantes()
if _faltan:
    st.info("Google Drive / Sheets no está configurado. Es **opcional**: si tus precios "
            "vienen de Excel o de SQL Server, puedes ignorar esta sección.")
    with st.expander("Cómo activarlo"):
        st.markdown(
            "1. En **Google Cloud Console** crea un proyecto y habilita **Google Drive API** "
            "y **Google Sheets API**.\n"
            "2. En *APIs y servicios > Pantalla de consentimiento OAuth*, configúrala y agrega "
            "tu correo como usuario de prueba.\n"
            "3. En *APIs y servicios > Credenciales > Crear credenciales > ID de cliente OAuth*, "
            "elige **Aplicación web** y en *URI de redireccionamiento autorizados* pon la "
            "dirección de esta app (ej. `https://TU-APP.streamlit.app/`).\n"
            "4. Copia el ID y el secreto del cliente a Streamlit Secrets junto con:\n"
            "   - `GOOGLE_OAUTH_REDIRECT_URI`: la misma dirección del punto 3, idéntica.\n"
            "   - `GOOGLE_TOKEN_ENCRYPTION_KEY`: genérala con "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`\n\n"
            "Faltan ahora: " + ", ".join(f"`{n}`" for n in _faltan))
    st.stop()

# OAuth state atado a la sesión administrativa, de un solo uso.
code=st.query_params.get("code")
state=st.query_params.get("state")
error=st.query_params.get("error")
if error:
    st.warning("Google no autorizó la conexión: "+str(error))
    st.query_params.clear()
if code:
    if not verify_state(str(state or "")):
        st.error("La autorización caducó o no coincide con esta sesión. Intenta conectar de nuevo.")
    else:
        try:
            connect(exchange_code(str(code)))
            st.success("Cuenta de Google conectada.")
        except Exception as e:
            st.error("No se pudo completar la conexión: "+str(e))
    st.query_params.clear()

try:
    cfg=config() or {}
except Exception as e:
    st.error("Ejecuta INSTALAR_GOOGLE_OAUTH.sql en Supabase. Detalle: "+str(e))
    st.stop()

if not cfg.get("refresh_token_encrypted"):
    st.link_button("Conectar con Google",auth_url(signed_state()),type="primary")
    st.info("Autoriza el acceso en Google. Si debes iniciar sesión nuevamente en el verificador al regresar, hazlo como administrador.")
    st.stop()

try:
    from google_oauth_source import cuenta_conectada
    _cuenta = cuenta_conectada(str(cfg.get("refresh_token_encrypted", ""))[-16:])
    _quien = " · ".join(x for x in (_cuenta["nombre"], _cuenta["correo"]) if x) or "cuenta sin nombre"
    st.success(f"Cuenta de Google conectada: **{_quien}**")
    st.caption("Para usar otra cuenta: **Desconectar cuenta de Google** (abajo) y vuelve a conectar.")
except Exception as _exc:
    st.success("Cuenta de Google conectada.")
    st.caption("No se pudo leer el nombre de la cuenta: " + str(_exc)[:150])
kind=st.radio("Formato del archivo",["Excel (.xlsx) en Google Drive","Google Sheets"],
              index=1 if cfg.get("kind")=="sheets" else 0)
kind="sheets" if kind=="Google Sheets" else "excel"
from datetime import datetime as _dt
from google_oauth_source import listar_archivos, pestanas
modo=st.radio("¿Cómo eliges el archivo?",["Elegir de mi Google Drive","Pegar el enlace"],horizontal=True)
fid=None
if modo=="Elegir de mi Google Drive":
    buscar=st.text_input("Buscar por nombre (opcional)",placeholder="Ej.: precios")
    try:
        with st.spinner("Buscando archivos en tu Drive…"):
            archivos=listar_archivos(kind,buscar,str(cfg.get("refresh_token_encrypted",""))[-16:])
    except Exception as e:
        archivos=[]
        st.error("No se pudo leer la lista de archivos de Drive: "+str(e))
    if not archivos:
        st.info("No se encontraron archivos "+("de Excel (.xlsx)" if kind=="excel" else "de Google Sheets")
                +(" con ese nombre." if buscar else " en esta cuenta.")
                +" Prueba el otro formato, o pega el enlace.")
    else:
        def _etiqueta(a):
            try:fecha=_dt.fromisoformat(a["modifiedTime"].replace("Z","+00:00")).strftime("%d/%m/%Y")
            except (KeyError,ValueError):fecha=""
            dueno=(a.get("owners") or [{}])[0].get("displayName","")
            return a["name"]+(f"  ·  modificado {fecha}" if fecha else "")+(f"  ·  {dueno}" if dueno else "")
        ids=[a["id"] for a in archivos]
        por_id={a["id"]:a for a in archivos}
        inicial=ids.index(cfg["file_id"]) if cfg.get("file_id") in ids else 0
        fid=st.selectbox(f"Archivo ({len(archivos)} encontrados, los más recientes primero)",ids,
                         index=inicial,format_func=lambda i:_etiqueta(por_id[i]))
else:
    link=st.text_input("Enlace del archivo",value=cfg.get("file_id") or "",
                       help="En Drive: clic derecho sobre el archivo > Compartir > Copiar enlace. Pulsa Enter al pegar.")
    if link:
        try:fid=file_id(link)
        except ValueError as e:st.warning(str(e))
sheet=""
if fid:
    try:
        with st.spinner("Leyendo las pestañas…"):
            hojas=pestanas(kind,fid)
        if len(hojas)>1:
            inicial=hojas.index(cfg["sheet_name"]) if cfg.get("sheet_name") in hojas else 0
            sheet=st.selectbox("Pestaña con los precios",hojas,index=inicial)
        elif hojas:
            sheet=hojas[0]
            st.caption(f"Pestaña: **{sheet}** (la única del archivo)")
    except Exception as e:
        st.warning("No se pudieron leer las pestañas ("+str(e)[:120]+"). Se usará la primera.")
if st.button("Leer archivo",disabled=not bool(fid)):
    try:
        df=read_file(kind,fid,sheet)
        st.session_state.google_file_preview=(kind,fid,sheet,list(df.columns),df.head(10))
    except Exception as e:
        st.error("No se pudo leer el archivo: "+str(e))
preview=st.session_state.get("google_file_preview")
if preview and preview[:3]==(kind,fid,sheet):
    cols=preview[3]
    st.dataframe(preview[4],hide_index=True)
    def field(label,stored,hints):
        default=stored if stored in cols else next((c for c in cols if any(h in c.lower() for h in hints)),cols[0])
        return st.selectbox(label,cols,index=cols.index(default))
    code_col=field("Código de barras",cfg.get("code_column"),["codigo","código","barcode","ean"])
    name_col=field("Nombre o descripción",cfg.get("name_column"),["nombre","descrip","name"])
    price_col=field("Precio",cfg.get("price_column"),["precio","price"])
    if st.button("Guardar configuración de Google",type="primary"):
        try:
            df=catalog(kind,fid,sheet,code_col,name_col,price_col)
            api("PATCH","google_price_source",{"id":"eq.1"},
                {"kind":kind,"file_id":fid,"sheet_name":sheet,
                 "code_column":code_col,"name_column":name_col,"price_column":price_col})
            st.cache_data.clear()
            st.success(f"Configuración de Google guardada: {len(df)} productos. Actívala en Precios > Fuente activa.")
            _equipos()
        except Exception as e:
            st.error("No se pudo activar: "+str(e))
st.caption("La app vuelve a leer el archivo de Google cada 30 segundos. No se copian productos a Supabase.")
if st.button("Actualizar ahora"):
    read_file.clear()
    catalog.clear()
    st.success("Caché borrada. La próxima consulta leerá los datos actualizados.")
    _equipos()
st.divider()
if st.button("Desconectar cuenta de Google"):
    try:
        api("PATCH","google_price_source",{"id":"eq.1"},
            {"refresh_token_encrypted":None,"file_id":None,"kind":None,
             "sheet_name":"","code_column":None,"name_column":None,"price_column":None})
        # Si Google estaba activo, cambiar a Supabase para no dejar una fuente sin credenciales.
        current = api("GET","price_source_settings",{"id":"eq.1","select":"source_type"})
        if current and current[0].get("source_type") == "google":
            api("PATCH","price_source_settings",{"id":"eq.1"},{"source_type":"local"})
        st.cache_data.clear()
        st.success("Cuenta desconectada. Si estaba activa, se restauró Supabase.")
        st.rerun()
    except Exception as e:
        st.error("No se pudo desconectar: "+str(e))
