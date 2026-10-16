# Actualización de Fuentes de datos

La pantalla antigua de Streamlit era informativa. Esta versión permite **preparar y descargar** un perfil `config.json` sin contraseñas. **No prueba conexiones desde Streamlit Cloud**, ya que el servidor de facturación está en una red privada.

## Instalación

1. En GitHub, sustituya SOLO `pages/2_Fuentes_de_datos.py` por el incluido en este paquete.
2. No cambie `app.py`, `shared.py` ni `pages/1_Administracion.py`.
3. En Streamlit, entre a Fuentes de datos, rellene campos y descargue `config.json`.
4. En el servidor Windows, instale el servidor local del paquete anterior `Consulta_Precios_Multibase_Windows_Android.zip` (carpeta `servidor_local`).
5. Copie `config.json` en esa carpeta. Configure `LOCAL_ADMIN_PASSWORD`, `SOURCE_DB_PASSWORD` y otras claves como variables de entorno **solo en Windows**.
6. Ejecute `INICIAR_WINDOWS.bat`. En Windows abra `http://127.0.0.1:8765/admin` y pulse Probar conexión y consulta.
7. En Android, en la misma LAN, abra `http://IP_DEL_WINDOWS:8765/`.

**Seguridad:** no exponga el puerto 8765 a internet. La página de administración local usa HTTP Basic: adminístrela solo desde el propio Windows mediante 127.0.0.1, o con HTTPS apropiado. Use un usuario SQL de solo lectura. El soporte para drivers varía por motor; Oracle, Firebird, Db2, SQL Anywhere y ODBC genérico pueden necesitar instalación/adaptación.

**Limitación:** el formulario de Streamlit genera un perfil; la prueba y la conexión real se hacen desde el servidor local Windows. No existe aún conexión de Streamlit Cloud directamente a IP privadas ni un selector LAN integrado en la aplicación cloud.
