# Sistema de Consulta de Precios

Verificador de precios para tiendas. Un cliente escanea un código de barras en una
pantalla (lector USB/Bluetooth) o en su celular, y ve el nombre y el precio del producto.

- **App web:** Streamlit (Streamlit Cloud).
- **Base de datos:** Supabase (usuarios, inventarios, configuración y colas de trabajo).
- **Fuentes de precios** (se elige una activa):
  1. **Inventarios Excel** cargados en Supabase (varios inventarios, uno activo).
  2. **Google Drive / Google Sheets** de la cuenta del negocio.
  3. **SQL Server del negocio**, a través del **Conector Windows** instalado en la red local.

```
 Pantalla / celular ──► Streamlit ──► Supabase ◄── Conector Windows ──► SQL Server (LAN)
                                         ▲
                              Google Drive / Sheets
```

Con SQL Server, Streamlit no se conecta directo al servidor del negocio: deja una
solicitud en Supabase, el Conector Windows la recoge, consulta SQL Server y devuelve el
resultado. Las credenciales SQL quedan cifradas en el equipo Windows (DPAPI).

## Estructura

| Ruta | Contenido |
|---|---|
| `app.py` | Punto de entrada: inicio de sesión, permisos y menú |
| `consulta_precios.py` | Pantalla del verificador (lector de códigos) |
| `pages/` | Páginas del menú (ver tabla de permisos) |
| `auth_usuarios.py` | Usuarios, contraseñas, roles y bloqueo por intentos |
| `inventarios.py` | Inventarios Excel y búsqueda por código |
| `google_oauth_source.py` | Conexión y lectura de Google Drive / Sheets |
| `mobile_geofence.py` | Zona autorizada (GPS) de Consulta Móvil |
| `sql/` | Instalación y migraciones de Supabase |
| `windows_bridge/` | Código del Conector Windows |
| `installer/` | Instalador del conector (Inno Setup) y su configuración de ejemplo |
| `.github/workflows/` | Compilación automática del conector en GitHub Actions |
| `pwa_offline/` | App offline independiente (PWA). No la usa la app Streamlit |

## Instalación

### 1. Supabase
- **Instalación nueva:** en *SQL Editor* ejecuta `sql/INSTALAR_COMPLETO.sql`.
  Se puede volver a ejecutar sin borrar datos.
- **Base ya instalada:** ejecuta, una sola vez y en orden, las migraciones pendientes:
  - `sql/MIGRACION_001_fuente_google.sql`: corrige la activación de Google como fuente.
  - `sql/MIGRACION_002_seguridad_login.sql`: bloqueo por intentos y permiso de kiosko.

### 2. Streamlit Secrets
Copia `.streamlit-secrets-EJEMPLO.toml` en *App settings > Secrets* y completa:

| Clave | Obligatoria | Uso |
|---|---|---|
| `SUPABASE_URL` | Sí | Dirección del proyecto Supabase |
| `SUPABASE_ANON_KEY` | Sí | Clave pública (lectura del inventario activo) |
| `SUPABASE_SERVICE_ROLE_KEY` | Sí | Clave privada del servidor. **Nunca en GitHub** |
| `SESSION_COOKIE_KEY` | Sí | Firma de la cookie "Recordar mi acceso" |
| `ADMIN_INITIAL_PASSWORD` | Primera vez | Crea el usuario `admin` si no hay usuarios |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_TOKEN_ENCRYPTION_KEY` | Solo para Google | Conexión a Drive / Sheets |

### 3. Primer acceso
Entra con el usuario `admin` y la clave de `ADMIN_INITIAL_PASSWORD`. La app obliga a
cambiarla. Después crea los usuarios en **Administrador de Usuarios**.

## Usuarios y permisos

- **Rol administrador:** acceso a todo, incluida *Ubicación Consulta Móvil*.

La sesión **solo se cierra con el botón "Cerrar sesión"** (o la ✕ en la cuenta kiosko).
Recargar la página, reiniciar el equipo o que Streamlit Cloud reinicie la app no la cierra.
Se cierra sola únicamente si la cuenta se desactiva o se le cambia la contraseña.
- **Rol usuario:** accede solo a las secciones de sus permisos:

| Permiso | Sección |
|---|---|
| Cargar Archivo Local | Inventarios independientes |
| Consulta de Base de Datos | Listado de productos de cualquier fuente |
| Fuentes de Datos | Administración y selección de la fuente activa |
| Configurar Consulta | Conexiones SQL Server y conexión Google |
| Logo del Negocio | Logo y código QR de la pantalla |
| Administrador de Usuarios | Cambiar su propia contraseña (crear usuarios requiere rol admin) |
| **Modo verificador (kiosko)** | Solo la pantalla de consulta, sin menú. Para salir pide usuario y clave de un administrador |

Tras 5 contraseñas incorrectas, la cuenta se bloquea 5 minutos. Para desbloquearla
antes, en Supabase:
`update verificador_usuarios set failed_attempts = 0, locked_until = null where username = 'NOMBRE';`

## Fuentes de precios

**Inventarios Excel.** En *Inventarios independientes* crea un inventario, sube el `.xlsx`
(columnas de código de barras, descripción y precio) y actívalo. Puede haber varios
inventarios, pero solo uno activo.

**Google Drive / Sheets.** En *Conexión Google Drive / Sheets* pulsa *Conectar con Google*,
pega el enlace del archivo, elige las columnas y activa. Se lee con caché de 30 segundos.

**SQL Server (Conector Windows).**
1. En el equipo Windows de la red del negocio, instala el **Microsoft ODBC Driver 18 for
   SQL Server** (x64).
2. En GitHub: *Actions > Construir conector Windows > Run workflow*. Descarga el artefacto
   e instala `ConectorConsultaPrecios` como administrador.
3. Edita `C:\ProgramData\ConsultaPrecios\bridge.env` (ver `installer/bridge.env.example`).
4. En la app: *Administración de Fuentes de Datos > Iniciar búsqueda en Windows*, elige
   servidor, credenciales y base. Luego en *Configurar Consulta* elige tabla y columnas.
5. Comprueba el conector en `http://IP-DEL-EQUIPO:8765/health`.

Recomendaciones: usa una cuenta SQL **de solo lectura** y no abras el puerto 8765 a Internet.
Subir cambios a GitHub no actualiza el conector ya instalado: hay que recompilarlo y
reinstalarlo.

## Consulta Móvil

Página pública para el celular del cliente: `https://TU-APP.streamlit.app/Escaner_Movil`
(o `?movil=1`). Lee el código con la cámara o con un lector Bluetooth. Solo funciona dentro
de la zona configurada en *Ubicación Consulta Móvil* (centro y radio de 10 a 10 000 m).

> El GPS lo informa el navegador y puede falsificarse: la zona evita el uso casual fuera
> de la tienda, pero no es una barrera de seguridad.

## Desarrollo local

```bash
pip install -r requirements.txt
mkdir -p .streamlit && cp .streamlit-secrets-EJEMPLO.toml .streamlit/secrets.toml  # y completar
streamlit run app.py
```
