# Buscar bases de datos SQL Server — instalación

1. Ejecuta `supabase_lan_db_requests.sql` en el SQL Editor de Supabase.
2. Reemplaza `windows_bridge/bridge.py` y `windows_bridge/requirements.txt` en GitHub.
3. Reemplaza `pages/2_Fuentes_de_datos.py` en GitHub (no modifiques app.py).
4. En el Windows conector (`10.0.0.190`) instala **Microsoft ODBC Driver 18 for SQL Server** (x64).
5. En `%PROGRAMDATA%\ConsultaPrecios\bridge.env` añade:

   SQL_READ_USER=USUARIO_SOLO_LECTURA
   SQL_READ_PASSWORD=CONTRASENA_LOCAL
   SQL_ODBC_DRIVER=ODBC Driver 18 for SQL Server

   Usa una cuenta SQL que solo pueda ver las bases autorizadas y leer lo necesario. No compartas este archivo.
   Para SQL Server con certificado no confiable, configura un certificado TLS válido para el servidor;
   el código exige `Encrypt=yes;TrustServerCertificate=no`.
6. Ejecuta GitHub Actions Windows Build y reinstala el instalador; comprueba que el proceso viejo se cierre.
7. En Streamlit: Buscar bases de datos → Abrir consulta en Windows → Consultar bases de datos → Recibir bases de datos.

La nueva funcionalidad solo lista nombres de bases accesibles, **no consulta productos ni cambia precios**.
El usuario SQL debe tener acceso a `master` y permisos de visualización a las bases relevantes.
Si el driver ODBC no está instalado o el certificado SQL no es confiable, la consulta mostrará un error.
