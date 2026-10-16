# Módulo Fuentes de datos — Consulta de precios

## Qué incluye
- `pages/2_Fuentes_de_datos.py`: página informativa de selección y modalidades.
- `conector_local/sync.py`: sincronizador **unidireccional** hacia Supabase.
- Configuraciones de ejemplo para SQL y API REST.

## Instalación sin alterar el verificador
1. Haz una copia de seguridad del repositorio.
2. Copia `pages/2_Fuentes_de_datos.py` a la carpeta `pages` del repositorio, **sin sobrescribir** `app.py`, `shared.py` ni Administración. Si renombraste la página principal a `Consulta_de_precios.py`, déjala igual.
3. Copia `conector_local/` al **servidor local** de facturación; NO subas `config.json` con datos reales ni credenciales a GitHub.
4. En el servidor local: `python -m pip install -r requirements.txt` y el driver indicado en ese archivo para tu motor.
5. Copia `config.example.json` como `config.json` y ajusta el tipo de fuente, tabla y nombres de columnas. La consulta debe devolver exactamente `barcode`, `name`, `price` mediante alias SQL. Para SQLite usa `source=sqlite` y `database` como ruta al archivo. Para Access usa `source=access` y la cadena ODBC de Access. Para REST usa `config_rest.example.json`.
6. Define variables de entorno en el servidor local:
   - `SUPABASE_URL` = URL del proyecto Supabase
   - `SUPABASE_SERVICE_ROLE_KEY` = clave de servicio (SECRETA, SOLO en servidor local)
   - Para SQL Server / Access: `SOURCE_ODBC_CONNECTION_STRING` (incluye usuario y contraseña si corresponde).
   - Para MySQL / PostgreSQL / Firebird: `SOURCE_DB_USER`, `SOURCE_DB_PASSWORD`.
   - Para API REST con bearer token: `SOURCE_API_TOKEN` (opcional).
7. Prueba **sin escribir datos**: `python sync.py --config config.json --dry-run`.
8. Si los productos y precios son correctos, ejecuta: `python sync.py --config config.json`.
9. Para sincronizar cada 5 minutos: `python sync.py --config config.json --every 5`. Configura el proceso como servicio del sistema para operación permanente.

## Reglas y límites importantes
- **No modifica** la base de facturación: ejecuta un `SELECT` de lectura o consulta una API GET.
- **Sí actualiza** la tabla `products` de Supabase con `barcode`, `name`, `price`, usando upsert. Por tanto, puede sobrescribir los precios actuales de los mismos códigos; haz una copia de seguridad antes de activar la sincronización.
- No elimina artículos que desaparezcan del origen; para eliminar o desactivar hay que diseñar una política explícita.
- La fuente de facturación debe ofrecer una cuenta de lectura y permiso de consulta. No todos los motores/drivers están disponibles en todos los sistemas operativos.
- El modo "Consulta directa por puente local" aparece como **pendiente**, no operativo. Streamlit Cloud no puede alcanzar directamente una IP privada de tu LAN.
- La página de selección es informativa: no cambia automáticamente el origen del verificador. El modo funcional incluido es sincronizar los precios a Supabase para que el verificador existente los lea.
- No expongas `SUPABASE_SERVICE_ROLE_KEY` ni contraseñas en Streamlit, páginas web, repositorios o capturas.
- La API REST de ejemplo supone una respuesta JSON `{"items":[{"codigo_barras":"123", "descripcion":"Producto", "precio_venta":10.0}]}`; adapta la configuración a la API real.

## Antes de producción
Identifica el sistema de facturación, motor de datos, tablas y precio correcto (impuestos, listas, ofertas). Prueba con un conjunto pequeño de productos y verifica precios antes de automatizar. Si necesitas mantener simultáneamente catálogos de varias empresas sin sobrescribir precios, hace falta un esquema multiempresa con origen por producto, no el `products` actual.
