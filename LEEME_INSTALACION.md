# Corrección /scan v1.2

Se corrigió el error 500 no explicado en el endpoint `/scan`: ahora se informa si Supabase devuelve HTTP 401, 403, 404, etc. y se registra el error interno sin exponer claves. La subred mostrada se toma de `ALLOWED_NETWORKS` en lugar de usar siempre 192.168.1.0/24.

**No se ha demostrado todavía la causa exacta del error 500 en tu equipo.** Esta versión mejora el diagnóstico y puede resolver el problema de la subred predeterminada, pero podría requerir revisar permisos/clave de Supabase.

Para compilar: reemplaza las carpetas `windows_bridge`, `installer` y `.github/workflows/windows-build.yml` en GitHub, luego ejecuta Actions → Construir conector Windows → Run workflow. Descarga el instalador en Artifacts e instálalo como administrador. No borres `%PROGRAMDATA%\ConsultaPrecios\bridge.env`.

Después de instalar: abre el enlace NUEVO generado en Streamlit, inicia sesión y pulsa Buscar servidores. Si falla, copia **solo el mensaje de error**, nunca contraseñas ni claves.

La detección de puertos no identifica de forma definitiva el motor SQL ni consulta precios.
