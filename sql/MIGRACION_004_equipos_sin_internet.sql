-- Ejecutar UNA VEZ en Supabase > SQL Editor.
-- Equipos sin internet: al recuperar la conexión suben las consultas que hicieron
-- sin red. Con la clave pública SOLO pueden AGREGAR filas marcadas 'offline-*':
-- no pueden leer, cambiar ni borrar el registro.
grant insert (created_at, barcode, found, product_name, price, source, channel)
    on public.price_lookup_log to anon;
drop policy if exists equipos_agregan_consultas on public.price_lookup_log;
create policy equipos_agregan_consultas on public.price_lookup_log
    for insert to anon
    with check (
        channel in ('offline-verificador', 'offline-movil')
        and length(barcode) between 1 and 64
        and coalesce(length(product_name), 0) <= 200
        and coalesce(length(source), 0) <= 20
        and created_at between now() - interval '60 days' and now() + interval '10 minutes'
    );
