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
| `apariencia.py` | Qué se ve en la pantalla de consulta (logo, QR, cuadro) |
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
| `SUPABASE_PUBLISHABLE_KEY` (o `SUPABASE_ANON_KEY`) | Sí | Clave pública (lectura del inventario activo) |
| `SUPABASE_SECRET_KEY` (o `SUPABASE_SERVICE_ROLE_KEY`) | Sí | Clave privada del servidor. **Nunca en GitHub** |
| `SESSION_COOKIE_KEY` | Sí | Firma de la cookie "Recordar mi acceso" |
| `ADMIN_INITIAL_PASSWORD` | Primera vez | Crea el usuario `admin` si no hay usuarios |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_TOKEN_ENCRYPTION_KEY` | Solo para Google | Conexión a Drive / Sheets |

> **Claves de Supabase:** la app acepta las claves nuevas (`sb_publishable_...`,
> `sb_secret_...`) y las legacy (`anon` / `service_role`, que empiezan con `eyJ`).
> Supabase retira las legacy a fines de 2026: conviene usar las nuevas. Todo el
> manejo de claves está en `supabase_cliente.py`.

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
| Logo del Negocio | Logo y código QR, y **Apariencia**: mostrar u ocultar logo, QR y cuadro del código |
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

## Equipos sin internet

La app del verificador sin internet está en la carpeta `docs/` y se publica con GitHub Pages.

1. Ejecuta `sql/MIGRACION_004_equipos_sin_internet.sql` en Supabase > SQL Editor.
2. En GitHub: **Settings > Pages > Build and deployment > Deploy from a branch > `main` / `/docs` > Save**.
   GitHub muestra la dirección (por ejemplo `https://tuusuario.github.io/verificadordeprecios/`).
3. En la app en línea, **Configuración > Equipos sin internet**:
   - define la **clave de salida del verificador** (distinta de tu contraseña);
   - pulsa **Publicar precios a los equipos**;
   - pega la dirección de GitHub Pages y guárdala: aparece el **enlace de instalación** con su QR.
4. En cada equipo, abre ese enlace **una vez con internet**. Descarga los precios y queda vinculado.
   En Chrome para Android: menú ⋮ > **Instalar aplicación**.
5. Desde ese momento, activar o publicar el inventario activo, o cambiar el logo, el QR o la apariencia,
   actualiza solo a los equipos. Revisan cada minuto con internet y descargan el catálogo solo si cambió.
   La fuente puede ser el Excel o Google Drive / Sheets (SQL Server todavía no).

6. Ejecuta `sql/MIGRACION_005_estado_equipos.sql`: cada equipo reporta (con internet) que está encendido y
   qué precios tiene; se ve en **Equipos sin internet > Estado de los equipos**. El nombre de cada equipo
   se pone desde su menú ✕.
7. Si cambias precios directamente en Google, crea el secreto `STREAMLIT_SECRETS` en GitHub
   (Settings > Secrets and variables > Actions) con el contenido de los Secrets de Streamlit:
   `.github/workflows/publicar-equipos.yml` revisa cada 30 minutos y publica solo si cambió.
8. Para dejarlo fijo como quiosco con FreeKiosk (gratis) o Fully Kiosk, sigue la guía de la misma página.

Al cambiar cualquier archivo de `docs/`, sube la versión en los TRES lugares: `APP_VERSION` en `docs/app.js`,
`VERSION` en `docs/sw.js` y `docs/version.txt`. Los equipos ven `version.txt` y se actualizan solos
(si no lo logran en 2 minutos, se reinstalan sin borrar los precios).
La carpeta `pwa_offline/` es el prototipo anterior y ya no se usa: puedes borrarla.

## Conector de Windows (SQL Server) — versión 5

- Busca cada código con **todas sus formas equivalentes** (UPC-E impreso, UPC-A, EAN-13, sin ceros),
  igual que el Excel y Google (`codigos_barras.py`, compartido con la app).
- Si la fuente activa es **SQL Server**, cada `SYNC_MINUTES` minutos (15 por defecto, en `bridge.env`)
  lee la tabla completa y la publica para los **equipos sin internet**, solo si cambió.
- Actualizar: GitHub > **Actions** > *Construir conector Windows* > descargar el artefacto e instalarlo
  en la PC de la tienda (reemplaza al anterior). Estado: `http://localhost:8765/health`.

## Acceso a la Consulta de Precios por ubicación

En **Equipos y pantallas > Ubicación y acceso** se elige cómo entran los verificadores a la app en línea:
con usuario, por la ubicación del local (sin usuario, dentro de la zona autorizada) o cualquiera de los dos.
Con acceso por ubicación, el personal entra con su usuario en `/?personal=1`. Salir del verificador sigue
pidiendo la clave de un administrador.
