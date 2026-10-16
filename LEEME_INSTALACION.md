# Conector Windows — Configuración fácil (portátil + instalador)

Este paquete es el **código fuente** y la automatización para compilar dos ejecutables del puente de descubrimiento LAN, y un asistente gráfico `ConfigurarConector.exe`. **No incluye ejecutables ya compilados.** No se requiere Python en el Windows donde se instalen los ejecutables compilados.

## Construir con GitHub Actions
1. En el repositorio GitHub donde tienes el workflow `Construir conector Windows`, reemplaza las carpetas `windows_bridge`, `installer` y `.github/workflows/windows-build.yml` con los archivos de este ZIP.
2. Ve a Actions → Construir conector Windows → Run workflow (rama main).
3. Al terminar en verde, abre **Summary** y descarga el artefacto `Conector-Windows-Portatil-e-Instalador`.
4. El artefacto contiene `Conector_Portatil_Windows.zip` y `Instalador_Conector_Consulta_Precios.exe`.

## Instalador con inicio automático
1. En Windows, ejecuta el instalador como administrador.
2. Al finalizar, se abre automáticamente el asistente **Configurar Conector Windows**.
3. Introduce la URL de Supabase, clave service_role y subred local autorizada. Pulsa **Generar contraseña segura** o escribe una de al menos 12 caracteres.
4. Pulsa **Guardar y reiniciar conector**. No envíes la clave ni la contraseña por chat ni las publiques en GitHub.
5. Abre `http://127.0.0.1:8765/health` y comprueba `{"ok":true}`. En `http://127.0.0.1:8765/login` introduce la contraseña configurada.
6. Si Windows Firewall bloquea el puerto 8765, autorízalo solo en la red privada y para dispositivos de confianza. No publiques este servicio en internet.
7. El conector se inicia con Windows mediante una **tarea programada** llamada `ConsultaPreciosConectorLAN`. No es un servicio nativo.

Para cambiar la contraseña: Menú Inicio → Consulta de Precios → **Configurar con asistente**. Genera otra contraseña y guarda; el asistente intentará reiniciar la tarea automáticamente.

## Portátil
1. Extrae `Conector_Portatil_Windows.zip`.
2. Ejecuta `ConfigurarConector.exe` para guardar la configuración en `%PROGRAMDATA%\ConsultaPrecios\bridge.env` (puede requerir permisos de administrador).
3. Ejecuta `ConectorConsultaPrecios.exe`. En modo portátil no hay inicio automático ni tarea programada, así que deja la ventana abierta.

## Seguridad y límites
- La contraseña y la clave service_role se almacenan en un archivo de configuración local **sin cifrar**. Restringe permisos de lectura de `%PROGRAMDATA%\ConsultaPrecios\bridge.env` a administradores y SYSTEM. Para mayor protección, se recomienda evolucionar a Windows Credential Manager o DPAPI.
- El acceso web local es HTTP; utiliza solo una red local de confianza. Para una red compartida o remota, implementa HTTPS y autenticación adecuada.
- El conector **descubre servicios de bases de datos** y devuelve selección a Streamlit; todavía no ejecuta consultas de precios en esos motores.
- Para la sincronización con Supabase debe existir `public.lan_discovery_requests` con RLS y permisos correctos.
- Algunos antivirus o SmartScreen pueden advertir sobre ejecutables nuevos sin firma digital.
- Compilación Windows y funcionamiento real **no probados aquí**; solo se comprobó la sintaxis Python y el contenido del ZIP.
