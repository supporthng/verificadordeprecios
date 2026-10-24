-- =====================================================================
-- MIGRACION_006 · Sucursales
-- Ejecutar en Supabase > SQL Editor. Es idempotente (se puede repetir).
--
-- - sucursales:          cada tienda, con su ubicación para el acceso por ubicación.
-- - sucursal_precios:    EXCEPCIONES de precio de cada sucursal. El catálogo general
--                        (la fuente activa) vale para todas; lo que esté aquí manda
--                        en esa sucursal. name vacío = se usa el nombre del general.
-- - verificador_usuarios.sucursal_id: vacío = usuario general (ve todo); no se puede borrar
--                        una sucursal con usuarios (no pasan a ser generales sin querer);
--                        con valor = encargado que solo ve su sucursal.
-- - price_lookup_log.sucursal y device_status.sucursal: informes y equipos por sucursal.
-- =====================================================================

create table if not exists public.sucursales (
    id uuid primary key default gen_random_uuid(),
    codigo text not null unique check (codigo ~ '^[a-z0-9][a-z0-9-]{1,29}$'),
    nombre text not null check (length(nombre) between 1 and 80),
    activa boolean not null default true,
    geo_enabled boolean not null default false,
    latitude double precision check (latitude between -90 and 90),
    longitude double precision check (longitude between -180 and 180),
    radius_m integer not null default 100 check (radius_m between 10 and 10000),
    excepciones_fuente text not null default 'excel'
        check (excepciones_fuente in ('excel', 'google', 'external')),
    excepciones_config jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
alter table public.sucursales enable row level security;
revoke all on public.sucursales from anon, authenticated;

create table if not exists public.sucursal_precios (
    sucursal_id uuid not null references public.sucursales(id) on delete cascade,
    barcode text not null check (length(barcode) between 1 and 64),
    name text check (length(name) <= 200),
    price numeric(14,2) not null check (price >= 0),
    primary key (sucursal_id, barcode)
);
alter table public.sucursal_precios enable row level security;
revoke all on public.sucursal_precios from anon, authenticated;

alter table public.verificador_usuarios
    add column if not exists sucursal_id uuid references public.sucursales(id) on delete restrict;

alter table public.price_lookup_log add column if not exists sucursal text;
create index if not exists price_lookup_log_sucursal_idx
    on public.price_lookup_log (sucursal, created_at desc);
-- Los equipos sin internet podrán anotar su sucursal al subir sus consultas.
grant insert (created_at, barcode, found, product_name, price, source, channel, sucursal)
    on public.price_lookup_log to anon;

alter table public.device_status add column if not exists sucursal text;
