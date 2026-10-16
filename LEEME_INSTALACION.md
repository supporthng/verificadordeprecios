# Actualización 1.1 — instalación sin bloqueo del conector

Esta versión modifica el instalador Inno Setup para que **detenga y deshabilite temporalmente** la tarea `ConsultaPreciosConectorLAN` antes de reemplazar el ejecutable. Comprueba el proceso asociado al archivo instalado y lo detiene si es necesario; espera hasta 25 segundos. Tras copiar los archivos, vuelve a registrar y arrancar la tarea programada. También intenta detenerla al desinstalar. Conserva `%PROGRAMDATA%\ConsultaPrecios\bridge.env` y el asistente gráfico de contraseña.

## Cómo compilar

1. Descomprime este ZIP y reemplaza en tu repositorio de GitHub las carpetas `installer`, `windows_bridge` y el archivo `.github/workflows/windows-build.yml`.
2. Ejecuta **Actions → Construir conector Windows → Run workflow**.
3. En **Summary → Artifacts**, descarga el artefacto generado y extrae `Instalador_Conector_Consulta_Precios.exe`.
4. Ejecuta el instalador como administrador en Windows. La versión anterior se detendrá automáticamente y se iniciará de nuevo al terminar.
5. Si el instalador viejo está mostrando «Acceso denegado», pulsa **Cancel installation** en el instalador viejo antes de iniciar el nuevo.
6. Usa **Inicio → Consulta de Precios → Configurar con asistente** para gestionar la contraseña.

## Precauciones

- Durante la actualización, el verificador local quedará temporalmente sin servicio.
- El instalador **solo detiene el proceso cuya ruta coincide con** `C:\Program Files\ConsultaPreciosConector\ConectorConsultaPrecios.exe`; no termina otros procesos con ese nombre en otras carpetas.
- El script necesita permisos de administrador y Windows PowerShell; el instalador ya solicita elevación.
- Si el proceso está protegido por otra herramienta, el instalador mostrará un error en vez de omitir el ejecutable.
- La configuración existente se conserva mediante `onlyifdoesntexist`.
- Este paquete incluye **fuentes para compilar**, no un EXE ya compilado. La sintaxis Python y la integridad del ZIP se verificaron, pero la compilación Inno Setup y el comportamiento en Windows requieren prueba real.
- No publiques credenciales de Supabase ni `bridge.env` en GitHub. No expongas el puerto 8765 a internet.
