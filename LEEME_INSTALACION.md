# Consulta de Precios Multibase — Servidor Windows + Android

## Qué contiene

Este paquete **no reemplaza** `app.py`, `shared.py` ni `pages/1_Administracion.py` de Streamlit. Es un **servidor web LAN independiente** que permite consultar la base local desde Android y, opcionalmente, Supabase.

- `servidor_local/app.py`: interfaz Android, API de precios, administración de conexión, modos local/nube/automático.
- `servidor_local/sincronizar.py`: sincronización manual SQL → Supabase (simulación por defecto).
- `servidor_local/requirements.txt`: dependencias comunes.
- `servidor_local/requirements_motores_opcionales.txt`: guía de drivers.
- `servidor_local/config.example.json`: configuración de ejemplo.
- `servidor_local/INICIAR_WINDOWS.bat`: inicia el servicio web.

## 1. Instalar en Windows

1. Copie la carpeta `servidor_local` a la computadora Windows que pueda alcanzar la base de datos.
2. Instale Python 3.11 o 3.12, habilitando `py` en Windows.
3. Instale el controlador de su motor, por ejemplo: `py -3 -m pip install pyodbc` (SQL Server / Access), `pymysql` (MySQL), `psycopg2-binary` (PostgreSQL), `oracledb` (Oracle). Firebird, Db2 y SQL Anywhere requieren drivers/dialectos adicionales específicos del fabricante; su compatibilidad debe validarse.
4. **Antes de iniciar**, configure en Windows la variable `LOCAL_ADMIN_PASSWORD` con una contraseña fuerte. Para bases SQL configure `SOURCE_DB_PASSWORD` si aplica. Para nube configure `SUPABASE_URL` y `SUPABASE_ANON_KEY`. Para sincronización, también `SUPABASE_SERVICE_ROLE_KEY`, **solo en el servidor local**.
5. Ejecute `INICIAR_WINDOWS.bat`. Instalará las dependencias y levantará el servicio en el puerto 8765.
6. En Windows abra `http://127.0.0.1:8765/admin`, usuario `admin` y la contraseña definida.
7. Elija motor, dirección, puerto, base, usuario, consulta SQL y modo. Pulse **Guardar configuración** y luego **Probar conexión**.
8. Desde Android conectado al mismo Wi-Fi, abra `http://IP_DEL_SERVIDOR_WINDOWS:8765/` (reemplace la IP por la IP real de Windows). Permita TCP 8765 **solo en el perfil de red privada** del firewall de Windows.

## 2. Configurar consulta SQL

El SQL de búsqueda debe ser un `SELECT` que devuelva `barcode`, `name` y `price`, con parámetro **`:barcode`**. Ejemplo:

```sql
SELECT CodigoBarra AS barcode, Descripcion AS name, PrecioVenta AS price
FROM Productos
WHERE CodigoBarra = :barcode
```

La consulta de sincronización usa las mismas tres columnas, pero sin el filtro por código. **Adapte nombres a la base real**. Use un usuario de **solo lectura**. El servidor valida la forma básica de SELECT, pero no sustituye los permisos de la base.

## 3. Modos

- **local:** busca únicamente en la base de facturación de la LAN. No necesita internet para consultas SQL locales.
- **cloud:** consulta Supabase por HTTPS (requiere internet).
- **auto:** consulta la fuente local primero; **solo si hay un error de conexión** utiliza Supabase. Un producto inexistente en la fuente local NO activa el respaldo.

El lector Android **no se conecta directamente a SQL**; abre la web local del servidor Windows. El servicio local debe permanecer encendido. El verificador Streamlit Cloud existente sigue funcionando por separado con Supabase.

## 4. Sincronización a Supabase

Desde una terminal en la carpeta `servidor_local`, con el entorno virtual activado:

```powershell
python sincronizar.py
```

Muestra el número de productos sin modificar Supabase. Para actualizar, tras verificar los datos:

```powershell
python sincronizar.py --apply
```

Pide escribir `ACTUALIZAR`. **Puede sobrescribir precios existentes**. No elimina productos que ya estén en Supabase. Antes de usar, haga copia de seguridad. No programe la tarea hasta validar una sincronización manual.

## 5. Seguridad y limitaciones

- **Nunca suba** `config.json`, contraseñas ni claves de servicio a GitHub.
- La interfaz `/admin` usa HTTP Basic y está pensada para LAN confiable; como HTTP no cifra las credenciales, **adminístrela desde el propio Windows por `127.0.0.1`**, o coloque HTTPS delante si necesita acceso remoto.
- La interfaz de consulta y `/api/product` no requieren contraseña: limite el puerto 8765 a dispositivos de confianza de su LAN/VLAN. No haga port-forward al internet público.
- El modo LAN es una web **separada** de la aplicación Streamlit Cloud, no un selector integrado en esa aplicación. Integración en una sola interfaz y autenticación más avanzada serían desarrollos posteriores.
- Los motores Oracle, Db2, Firebird, SQL Anywhere y ODBC genérico figuran como **adaptadores configurables**, pero requieren controladores/dialectos y pruebas en el entorno real. El adaptador ODBC genérico actual usa el dialecto `mssql+pyodbc`; no se garantiza compatibilidad con cualquier driver no SQL Server.
- `api_rest` supone una API GET que devuelve un objeto `{barcode,name,price}`, una lista de objetos o `{product:{...}}`; otros formatos requieren adaptador específico.
- El servidor muestra resultados durante 10 segundos. No se garantiza foco de escaneo en todos los navegadores Android hasta probarlo en el dispositivo.

## 6. Diagnóstico

Si falla **Probar conexión**, revise la consola Windows, la IP, firewall, driver instalado, credenciales y nombres reales de tabla/columnas. No comparta contraseñas ni tokens en capturas.
