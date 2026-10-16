"""Configurador de perfil de conexión; ejecución/prueba real en el servidor Windows."""
import json
import ipaddress
import streamlit as st

st.set_page_config(page_title="Fuentes de datos", page_icon="🗄️", layout="centered")
st.title("Fuentes de datos")
st.info("Esta página prepara el perfil de conexión. La conexión y la prueba reales se ejecutan en el servidor Windows, no en Streamlit Cloud.")
st.warning("No introduzcas contraseñas ni claves privadas aquí. Configúralas únicamente en Windows.")

motors = {
    "SQL Server": ("sqlserver", "1433"),
    "MySQL / MariaDB": ("mysql", "3306"),
    "PostgreSQL": ("postgresql", "5432"),
    "Firebird": ("firebird", "3050"),
    "SQLite": ("sqlite", ""),
    "Microsoft Access": ("access", ""),
    "Oracle": ("oracle", "1521"),
    "IBM Db2": ("db2", "50000"),
    "SAP SQL Anywhere": ("sqlanywhere", "2638"),
    "ODBC genérico": ("odbc", ""),
    "API REST": ("api_rest", ""),
    "Supabase": ("supabase", ""),
}

st.subheader("1. Preparar conexión")
with st.form("perfil"):
    label = st.selectbox("Motor o fuente", list(motors))
    engine, default_port = motors[label]
    mode = st.selectbox("Modo de consulta", ["local", "cloud", "auto"], format_func=lambda x: {"local":"Local (LAN)","cloud":"Nube (Supabase)","auto":"Automático (local y respaldo nube)"}[x])
    host = st.text_input("Servidor / IP", placeholder="192.168.1.100")
    port = st.text_input("Puerto (opcional)", placeholder=f"Ejemplo: {default_port}" if default_port else "Opcional")
    database = st.text_input("Base de datos o ruta de archivo", placeholder="Facturacion o C:/datos/facturacion.db")
    username = st.text_input("Usuario de solo lectura", placeholder="consulta_precios")
    odbc_driver = st.text_input("Controlador ODBC (si corresponde)", value="ODBC Driver 18 for SQL Server")
    api_url = st.text_input("URL de API (solo API REST)", placeholder="https://servidor-interno/api/productos")
    sql_lookup = st.text_area("Consulta SQL por código de barras", value="SELECT CodigoBarra AS barcode, Descripcion AS name, PrecioVenta AS price FROM Productos WHERE CodigoBarra = :barcode", height=110)
    sql_sync = st.text_area("Consulta SQL para sincronizar", value="SELECT CodigoBarra AS barcode, Descripcion AS name, PrecioVenta AS price FROM Productos", height=100)
    generate = st.form_submit_button("Preparar configuración", type="primary")

if generate:
    if port and not port.isdecimal():
        st.error("El puerto debe ser un número.")
    elif engine in ("api_rest",) and not api_url.startswith(("https://", "http://")):
        st.error("Escribe la URL de la API REST.")
    else:
        profile = {
            "mode": mode, "engine": engine, "host": host.strip(),
            "port": port.strip() or default_port,
            "database": database.strip(), "username": username.strip(),
            "odbc_driver": odbc_driver.strip(), "api_url": api_url.strip(),
            "api_key_env": "SOURCE_API_KEY", "api_barcode_param": "barcode",
            "sql_lookup": sql_lookup.strip(), "sql_sync": sql_sync.strip(),
            "sync_batch_size": 200,
        }
        st.success("Perfil preparado. Descárgalo y colócalo en la carpeta servidor_local de Windows con el nombre config.json.")
        st.download_button("Descargar config.json", data=json.dumps(profile, ensure_ascii=False, indent=2), file_name="config.json", mime="application/json")

st.subheader("2. Conectar y probar en Windows")
st.markdown("1. Instala e inicia `servidor_local/INICIAR_WINDOWS.bat` en el equipo Windows.\n2. Guarda `config.json` en esa misma carpeta, junto a `app.py`.\n3. Abre **http://127.0.0.1:8765/admin** desde ese Windows.\n4. Inicia sesión con el usuario `admin` y la contraseña `LOCAL_ADMIN_PASSWORD` definida en Windows.\n5. Pulsa **Probar conexión y consulta**.\n6. Desde Android, conectado al Wi-Fi local, abre `http://IP_DEL_WINDOWS:8765/`.")
st.caption("La configuración del servidor local no modifica automáticamente la aplicación de Streamlit Cloud ni sus secretos de Supabase.")
