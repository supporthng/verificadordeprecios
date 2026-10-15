# Consulta de precios — Streamlit + Android PWA

Incluye **dos aplicaciones** en un repositorio:

- `app.py` + `requirements.txt`: aplicación Streamlit (internet obligatorio).
- `android/`: PWA Android (importación local de Excel y consultas sin internet una vez instalada/cargada).
- `supabase.sql`: esquema de base de datos compartida.

## 1. Subir a GitHub desde Windows

Descomprime el ZIP. En el repositorio `consulta-precios`, elige **Add file > Upload files** y arrastra el contenido de esta carpeta, conservando la carpeta `android/`. El archivo `app.py` debe estar en la raíz. **Nunca publiques secretos reales en GitHub.**

## 2. Crear Supabase

En https://supabase.com/dashboard crea un proyecto. En **SQL Editor**, ejecuta `supabase.sql`. En **Project Settings > API** (o sección de claves del proyecto), copia la URL, la clave pública y la clave de servicio secreta. La clave secreta **solo** va en Streamlit Secrets, nunca en la PWA ni en GitHub.

## 3. Publicar Streamlit

En https://share.streamlit.io inicia sesión con GitHub y selecciona **Create app** > tu repositorio `consulta-precios`, rama `main`, archivo `app.py`. Antes de utilizar la aplicación, configura **App settings > Secrets** con los nombres del archivo `.streamlit-secrets-EJEMPLO.toml` y tus valores reales. No cargues el archivo de ejemplo con secretos reales al repositorio. Reinicia la app si es necesario.

En Streamlit, abre **Administración**, introduce la contraseña definida en Secrets, selecciona tu Excel `.xlsx`, revisa la vista previa y confirma **Publicar en Supabase**. Streamlit procesa el archivo en memoria y envía los registros; no guarda el archivo Excel original en GitHub.

## 4. Publicar PWA Android

En GitHub > Settings > Pages, elige **Deploy from a branch**, rama `main`, carpeta `/(root)`, guarda. Cuando se publique, abre `https://TU-USUARIO.github.io/consulta-precios/android/` desde Chrome Android. Menú de Chrome > **Añadir a pantalla de inicio** o **Instalar aplicación**. Abre la app con internet una primera vez para almacenar sus archivos. Luego podrás usar la consulta local sin internet.

En la PWA, abre **Administración**, crea un PIN local (mínimo 4 dígitos) y usa **Cargar Excel** para guardar precios en el dispositivo. En **Configuración** selecciona modo **local** o **en línea**. En línea, introduce la URL y la clave **pública** de Supabase; nunca la clave secreta. Para publicar desde Android, además necesitas un usuario de Supabase Authentication incluido en `admin_users` según el comentario SQL.

## Consideraciones importantes

- El modo sin internet es **solo la PWA**, no Streamlit. En Android los precios permanecen en el almacenamiento del navegador; borrar los datos del sitio puede borrarlos.
- La PWA permite cargar localmente y luego publicar manualmente en línea. No hay cola automática de sincronización en segundo plano.
- Streamlit y PWA usan el mismo catálogo en línea, pero no comparten automáticamente los datos locales hasta que se publiquen.
- Las publicaciones son **upsert** por código: actualizan o agregan, pero no eliminan productos ausentes del Excel.
- El PIN local es una barrera de interfaz, no un mecanismo de seguridad fuerte; la publicación en nube se protege con autenticación y políticas Supabase.
- GitHub Pages sirve el contenido del repositorio de manera pública. No publiques datos privados en los archivos.
