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
| `apariencia.py` | Apariencia de la pantalla lectora: nombre del negocio, estilo, color, textos, logo, QR, cuadro |
| `imagenes_negocio.py` | Logo, código QR y fotos de productos (almacenamiento privado de Supabase) |
| `fotos_productos.py` | Fotos de productos que se alimentan solas: al primer consulta se buscan por código de barras en Open Food Facts, se guardan y se publican para los equipos |
| `vista_previa.py` | Vista previa de la pantalla lectora a la resolución de cada equipo (usa los archivos de `docs/`) |
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
| Apariencia | Todo lo de la pantalla lectora en un lugar: nombre del negocio, 5 estilos (Claro, Noche, Color del negocio, Etiqueta de góndola, Panel lateral), color, textos, logo, código QR y fotos de productos, con vista previa en 1024×600, 800×480, 1280×800, Full HD y vertical |
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
   se pone desde su menú ⚙.
7. Si cambias precios directamente en Google, crea el secreto `STREAMLIT_SECRETS` en GitHub
   (Settings > Secrets and variables > Actions) con el contenido de los Secrets de Streamlit:
   `.github/workflows/publicar-equipos.yml` revisa cada 30 minutos y publica solo si cambió.
8. Para dejarlo fijo como quiosco con FreeKiosk (gratis) o Fully Kiosk, sigue la guía de la misma página.

Al cambiar cualquier archivo de `docs/`, sube la versión en los TRES lugares: `APP_VERSION` en `docs/app.js`,
`VERSION` en `docs/sw.js` y `docs/version.txt`. Los equipos ven `version.txt` y se actualizan solos
(si no lo logran en 2 minutos, se reinstalan sin borrar los precios).
La carpeta `pwa_offline/` es el prototipo anterior y ya no se usa: puedes borrarla.

## Conector de Windows (SQL Server) — versión 6

- v6: atiende también las configuraciones de SQL Server que eligen las **sucursales** (no solo la habilitada
  de la Principal) y envía sus tablas a `logo-negocio/catalogo-externo-<configuración>.json` para sus equipos.

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

## Apps propias: Android (APK) y Windows (.exe)

- `apps/android`: app "Consulta de Precios" (WebView) a pantalla completa, pantalla de inicio de Android,
  arranca al encender, sin botón Atrás; bloqueo total opcional (Device Owner:
  `adb shell dpm set-device-owner com.supporthng.consultaprecios/.AdminReceiver`).
  Workflow *Construir app Android*. Secretos: `ANDROID_KEYSTORE_B64` y `ANDROID_KEYSTORE_PASSWORD`
  (siempre la misma llave, para que cada APK se instale encima del anterior).
  Descarga fija: `https://github.com/supporthng/verificadordeprecios/releases/download/android/ConsultaPrecios.apk`
- `apps/windows`: app WebView2 a pantalla completa, siempre encima, bloquea Alt+Tab / Windows / Alt+F4,
  arranca con Windows. Workflow *Construir app Windows*.
  Descarga fija: `https://github.com/supporthng/verificadordeprecios/releases/download/windows/Instalador_Consulta_de_Precios.exe`
- En las dos: ⚙ abre la configuración y ✕ cierra la app, ambos con la clave de salida del verificador.
- Android: la app vuelve sola al frente si alguien abre Recientes, notificaciones u otra app (permiso *Mostrar sobre otras apps*, desde ⚙). Windows: oculta la barra de tareas y bloquea Ctrl+Shift+Esc mientras está abierta.

### Publicar una versión nueva del marco de las apps (APK / instalador)

Solo cuando cambia el código de `apps/` (las funciones del verificador viven en `docs/` y se actualizan solas):
1. Sube la versión en `apps/android/app/build.gradle` (`versionName`), `apps/windows/kiosco.py` (`VERSION`)
   y `apps/windows/ConsultaPrecios.iss` (`MyAppVersion`).
2. Ejecuta los workflows *Construir app Android* / *Construir app Windows* y espera a que publiquen.
3. **Después**, sube la misma versión en `docs/apps.json` (nunca antes: el equipo instalaría la versión
   vieja creyendo que es la nueva). Los equipos se actualizan solos:
   - **Windows**: al abrir la app, y con la app abierta cuando el equipo está libre; siempre en silencio.
     Registro en `%LOCALAPPDATA%\ConsultaPrecios\actualizacion.log`.
   - **Android**: al abrir la app. En silencio con bloqueo total, o en Android 12+ desde la 1.2.0
     (la primera vez Android pregunta); si no, Android muestra «¿Actualizar?» una vez por apertura.
   - También a mano: menú ⚙ › «📲 Buscar actualización de la app»

## Fotos de productos automáticas

1. Cuando un producto **encontrado** se consulta y no tiene foto, se busca por su código de barras en las bases
   abiertas de Open Food Facts (alimentos, belleza, mascotas y otros productos). Se prueban sus formas
   equivalentes (UPC-E, UPC-A, EAN-13, sin ceros iniciales).
2. Si aparece, se guarda una copia reducida (máx. 480 px) en `imagenes-productos/internet/`. Si no, se anota y se
   vuelve a intentar a los 30 días.
3. **Cuándo se busca:** al instante en la Consulta en línea (en segundo plano, sin demorar al cliente) y cada
   30 minutos con GitHub Actions para lo consultado en los equipos sin internet. También con el botón
   «Buscar fotos ahora» en Apariencia › Fotos de productos.
4. La foto subida a mano siempre gana. Desde Apariencia se puede quitar una foto equivocada (no se vuelve a buscar)
   o pedir que se busque otra vez.
5. Los equipos sin internet descargan las fotos nuevas solos (`equipos/fotos.json`) y las guardan en el equipo:
   se ven aunque no haya conexión. «Foto del producto junto al precio» se enciende o apaga en Apariencia.

## Sucursales (fase 1)

Requiere ejecutar **sql/MIGRACION_006_sucursales.sql** en Supabase (también incluido en `INSTALAR_COMPLETO.sql`).
Mientras no haya sucursales, todo funciona como una sola tienda.

- **Precios:** todos los inventarios se crean, se cargan y se identifican en **Precios › Inventarios (Excel)**
  (la tabla muestra quién usa cada uno). La Principal usa la fuente activa. Cada sucursal **elige su fuente** en
  Administración › Sucursales › Fuente de precios: igual que la Principal, uno de los inventarios, Google Drive /
  Sheets o SQL Server (se guarda en `sucursales.excepciones_config.fuente`, sin migración nueva). No se mezclan:
  la sucursal consulta solo su fuente. Un inventario que usa una sucursal no se puede borrar.
- **Usuarios:** sin sucursal = usuario general (ve y administra todo). Con sucursal = encargado: solo ve su
  sucursal (su fuente de precios, sus usuarios, su registro de consultas y su Inicio) y no ve la configuración común.
  Una sucursal con usuarios no se puede borrar (para que no pasen a ser generales).
- **Consulta en línea:** la cuenta del verificador de una sucursal muestra sus precios. Con el acceso por ubicación,
  el equipo queda en la sucursal en cuya zona está (cada sucursal con su punto y su radio).
- **Informes:** cada consulta queda anotada con su sucursal; el registro se puede ver por sucursal.

### Fase 2: equipos sin internet por sucursal

Requiere **sql/MIGRACION_007_equipos_por_sucursal.sql** (después de la 006).

- Al publicar, además de `estado.json` (Principal) se publica `estado-<sucursal>.json` por sucursal. Si usa la misma
  fuente que la Principal, comparte su catálogo; si no, apunta al `catalogo-<huella>.json` de su propia fuente.
  Si su fuente no tiene datos (p. ej. Google sin configurar), el equipo conserva lo último que tenía.
- Vincular un equipo a una sucursal: enlace propio en Equipos sin internet › Equipos de una sucursal, o desde el menú
  ⚙ del equipo › **Cambiar sucursal** (lista publicada en `sucursales.json`, solo sucursales activas).
- El equipo reporta su sucursal (tabla de equipos) y sus consultas se suben con ella. Si falta la migración 007,
  reporta igual sin la sucursal.

Pendiente: un SQL Server distinto por sucursal (hoy hay un solo conector y una sola configuración de Google).

## Respaldo y restauración

Administración › **Respaldo** (solo el administrador general):
- **Crear respaldo:** descarga un `.zip` con inventarios y productos, sucursales, usuarios, fuentes de precios
  (Google, SQL Server), ubicación, apariencia, logo, QR y fotos (opcional: registro de consultas).
  Puede guardar también una copia en la nube privada `respaldos` de Supabase.
- **Automáticos:** la revisión de GitHub (`publicar_automatico.py`) guarda uno por día y conserva los últimos 14.
- **Restaurar:** desde un archivo o desde la nube; se eligen las partes. Antes se guarda una copia del estado
  actual (`antes-de-restaurar-…zip`). Escribe encima (lo que no está en el respaldo se deja como está); los
  inventarios se emparejan por nombre y se ajustan las sucursales que los usan.
- El respaldo contiene datos sensibles (usuarios con sus claves cifradas y la conexión a Google): guardarlo seguro.
