# Consulta de Precios — Android PWA

## Subir a GitHub Pages

1. Crear repositorio público `consulta-precios`.
2. Descomprimir `consulta-precios-android.zip` y subir **los archivos que contiene** a la raíz del repositorio (index.html, app.js, style.css, sw.js, manifest.webmanifest, icon.svg, supabase.sql, README.md). No subir la carpeta contenedora ni el ZIP.
3. Ir a Settings > Pages > Build and deployment > Deploy from a branch > main / (root) > Save.
4. Abrir el enlace HTTPS de Pages en Chrome Android y usar menú ⋮ > Añadir a pantalla de inicio / Instalar aplicación.
5. Abrir al menos una vez con internet para instalar el contenido offline. No borrar los datos del navegador o la aplicación: se perderá la copia local.

## Uso sin internet

- Abrir Administración, crear un PIN local de al menos 4 dígitos en el primer acceso.
- Ir a Cargar Excel, seleccionar `.xlsx` del Android, revisar cantidad de productos y tocar Guardar precios en Android.
- Buscar desde Consulta. Los datos se almacenan en IndexedDB y permanecen disponibles offline.
- El PIN local es una barrera básica de interfaz, no cifrado ni seguridad resistente a ataques físicos. Evitar datos sensibles.

## Uso en línea (opcional)

1. Crear proyecto en Supabase y ejecutar `supabase.sql` en SQL Editor.
2. Crear usuario administrador en Supabase Authentication > Users.
3. Insertar su UUID en `public.admin_users` según instrucción comentada en SQL.
4. En Configuración seleccionar modo En línea, pegar URL del proyecto y clave **pública** (anon/publishable), correo y contraseña del usuario administrador. Guardar configuración.
5. Iniciar sesión; el catálogo se descargará a IndexedDB. Para publicar un Excel nuevo, seleccionarlo en Cargar Excel, guardar localmente y tocar Publicar en línea.
6. Otros Android pueden usar la misma URL y clave pública y pulsar Actualizar desde la nube. Sin internet mantienen la última copia descargada.

**Limitaciones de esta primera versión:** la publicación en línea agrega/actualiza productos por código, pero no elimina productos antiguos ausentes del Excel. No hay sincronización automática ni control de versiones de inventario. En modo en línea la descarga requiere pulsar Actualizar desde la nube (o iniciar sesión); la app conserva el último catálogo local cuando está sin internet. No existe lector de cámara integrado; lectores Bluetooth/USB que escriben como teclado sí funcionan. No se almacena la contraseña de Supabase. El PIN local se guarda en almacenamiento del navegador y no debe reutilizarse como contraseña de otros servicios.

El lector integrado usa `DecompressionStream('deflate-raw')` y requiere Chrome Android moderno. Solo admite `.xlsx`, no `.xls`.
