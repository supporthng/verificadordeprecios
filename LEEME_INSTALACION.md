# Consulta de Precios — Puente Windows ↔ Streamlit Cloud

Este paquete añade **descubrimiento de servidores en Windows** y permite recibir en Streamlit Cloud la IP, puerto y motor probable seleccionados. **No reemplaza** `app.py` ni `pages/1_Administracion.py`, y **no configura automáticamente las credenciales SQL ni activa un nuevo origen de precios**.

## 1. Supabase

En Supabase > SQL Editor, ejecuta `supabase_bridge.sql` **una sola vez**. La tabla tiene RLS habilitado y no concede acceso a `anon` ni `authenticated`. Solo los componentes de confianza usan `service_role`.

## 2. Streamlit Cloud

Sube **solo** `pages/2_Fuentes_de_datos.py` a tu repositorio (reemplaza la página informativa anterior). Usa los secretos ya configurados `ADMIN_PASSWORD`, `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY`. Nunca publiques esos secretos en GitHub.

Abre Fuentes de datos e inicia sesión con la contraseña de administración. Introduce la IP privada del equipo Windows que ejecutará el puente (no necesariamente la IP del servidor SQL).

## 3. Windows

Copia `windows_bridge` al equipo Windows de tu negocio. Instala Python 3. Copia `.env.example` como `.env` y configura `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `BRIDGE_PASSWORD` (mínimo 12 caracteres) y `ALLOWED_NETWORKS` con las redes autorizadas, por ejemplo `192.168.1.0/24`.

Ejecuta `INICIAR_WINDOWS.bat`. Permite TCP 8765 en el firewall **solo desde tu red local de confianza**. La API no debe exponerse directamente a internet. El puente requiere acceso saliente HTTPS a Supabase.

## 4. Búsqueda y devolución

1. En Streamlit, pulsa **1. Iniciar búsqueda en Windows**.
2. Pulsa **Abrir búsqueda en Windows** desde un navegador en la misma red. Inicia sesión con `BRIDGE_PASSWORD`.
3. Especifica una subred permitida (máximo 256 direcciones) y pulsa **Buscar servidores**.
4. Selecciona un resultado. Windows lo envía a la tabla privada de Supabase usando su propia clave de servicio.
5. Vuelve a Streamlit y pulsa **3. Recibir selección desde Windows**. Se rellenan IP, puerto y motor probable.

Las solicitudes vencen a los 10 minutos. El motor detectado es **probable**, inferido del puerto. La detección no accede a los datos de facturación ni intenta contraseñas.

## Limitaciones y seguridad

- **No se abre un programa de Windows automáticamente** desde Streamlit Cloud: el usuario abre el enlace al puente local desde un dispositivo que tenga acceso a la LAN.
- La aplicación Streamlit Cloud no puede conectarse directamente a `192.168.x.x`.
- Este paquete **solo descubre y devuelve servidores**; no implementa consultas SQL ni sincronización de precios. Para ello se utiliza el conector multibase local de la etapa anterior y se configura con permisos de solo lectura.
- El puente Windows necesita internet para enviar la selección a Supabase. La consulta de precios totalmente offline debe ejecutarse en un servicio local independiente.
- El puente sirve HTTP en LAN; úsalo solo en una red de confianza. Para redes compartidas, configura un proxy HTTPS y autenticación reforzada.
- Nunca compartas `.env`, claves de servicio ni contraseñas. No las pongas en URLs ni en campos de Streamlit.
- Se debe probar en tu Windows real; las pruebas realizadas aquí son de sintaxis, no de red.
