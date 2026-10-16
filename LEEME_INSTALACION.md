# Conector Windows para Consulta de Precios

Este paquete contiene **código fuente y automatización de compilación** para generar dos distribuciones Windows sin necesidad de instalar Python en la computadora del negocio:

- **Portátil**: `Conector_Portatil_Windows.zip`, con `ConectorConsultaPrecios.exe`.
- **Instalador**: `Instalador_Conector_Consulta_Precios.exe`, que registra una tarea de Windows al arrancar.

**Los archivos .exe NO están incluidos en este ZIP**. Deben compilarse en Windows (o usando GitHub Actions). No se ha probado la ejecución en una computadora Windows real.

## Compilar las dos versiones sin instalar Python en el equipo de facturación

1. Crea un repositorio **privado** en GitHub y sube el contenido de esta carpeta, conservando `.github/workflows/windows-build.yml`.
2. En GitHub entra a **Actions → Construir conector Windows → Run workflow**.
3. Espera a que termine y descarga el artefacto `Conector-Windows-Portatil-e-Instalador`.
4. Encontrarás el ZIP portátil y el instalador `.exe`.
5. **No subas credenciales reales al repositorio.**

GitHub Actions usa Python para **compilar**, pero el equipo donde se ejecuta el EXE no necesita instalarlo.

## Instalar en el Windows del negocio

1. Ejecuta `Instalador_Conector_Consulta_Precios.exe` como administrador.
2. Abre desde el menú Inicio **Consulta de Precios → Configurar conexión**.
3. Edita `%PROGRAMDATA%\ConsultaPrecios\bridge.env` y configura:
   - `SUPABASE_URL` (URL de tu proyecto)
   - `SUPABASE_SERVICE_ROLE_KEY` (solo en el servidor Windows, nunca en el navegador)
   - `BRIDGE_PASSWORD` (contraseña fuerte de 12 o más caracteres)
   - `ALLOWED_NETWORKS` (subred real, p. ej. `10.0.0.0/24`)
4. Guarda el archivo y reinicia la tarea **ConsultaPreciosConectorLAN** desde el Programador de tareas o reinicia Windows.
5. En Windows abre `http://127.0.0.1:8765/health` y comprueba que devuelve `{"ok":true}`.
6. Para acceder desde Android/otro PC de la LAN, permite el puerto TCP 8765 **solo en el perfil privado y subred autorizada** del firewall. No abras ese puerto a internet.
7. En Streamlit, usa la IP del Windows y el puerto 8765 para abrir el buscador. Los resultados se transmiten a Supabase mediante la tabla `lan_discovery_requests`.

## Ejecutable portátil

Extrae `Conector_Portatil_Windows.zip`, copia `bridge.env.example` como `bridge.env` junto al EXE, configura los mismos valores y ejecuta el EXE con doble clic. No se registra inicio automático.

## Seguridad y limitaciones

- El conector es un **buscador de servicios de bases de datos**: detecta puertos habituales, pero no autentica ni consulta precios directamente.
- El enlace HTTP en LAN y la cookie de sesión no ofrecen cifrado de transporte. Utilízalo solo en una red local de confianza; para redes compartidas o acceso remoto, agrega HTTPS mediante proxy seguro.
- No expongas el puerto 8765 a internet.
- No copies `bridge.env` ni claves de Supabase a GitHub.
- El instalador crea una **tarea programada al inicio de Windows**, no un servicio Windows nativo.
- La configuración debe completarse antes de que el proceso pueda arrancar correctamente.
- Los motores SQL/ODBC pueden requerir drivers adicionales para la posterior consulta real de precios.
- El nombre de tabla `public.lan_discovery_requests` y su política RLS deben existir en Supabase.
- Para actualizar o desinstalar, utiliza el instalador de Windows. La configuración en ProgramData puede permanecer para evitar perder credenciales.

## Estructura

`windows_bridge/bridge.py`: servicio FastAPI LAN existente con búsqueda de puertos.
`windows_bridge/build_windows.ps1`: genera EXE usando PyInstaller.
`installer/ConectorConsultaPrecios.iss`: proyecto Inno Setup.
`installer/RegistrarInicioAutomatico.ps1`: registra tarea de inicio automático.
`.github/workflows/windows-build.yml`: compila ambas variantes en Windows.

**Nota:** si usas una versión previa de `bridge.py`, verifica la compatibilidad con tu página Streamlit. Esta distribución mantiene los endpoints `/login`, `/scan`, `/select` y `/health` del puente anterior.
