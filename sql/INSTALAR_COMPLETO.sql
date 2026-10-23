-- =====================================================================
-- Consulta de Precios · Instalación completa de Supabase
-- Ejecutar en Supabase > SQL Editor. Es idempotente: puede ejecutarse
-- de nuevo sin borrar datos. Reemplaza a los SQL sueltos anteriores.
-- Todas las tablas son de uso exclusivo del servidor (service_role),
-- salvo la lectura del inventario activo (anon) para el verificador.
-- =====================================================================

-- 1. Usuarios del verificador ------------------------------------------
create table if not exists public.verificador_usuarios (
    id uuid primary key default gen_random_uuid(),
    username text not null unique,
    password_hash text not null,
    role text not null default 'usuario' check (role in ('admin', 'usuario')),
    permissions text[] not null default '{}',
    active boolean not null default true,
    must_change_password boolean not null default true,
    failed_attempts integer not null default 0,
    locked_until timestamptz,
    created_at timestamptz not null default now()
);
alter table public.verificador_usuarios
    add column if not exists failed_attempts integer not null default 0,
    add column if not exists locked_until timestamptz;
alter table public.verificador_usuarios enable row level security;
revoke all on public.verificador_usuarios from anon, authenticated;

-- 2. Fuente activa del verificador (una sola fila, id = 1) --------------
create table if not exists public.price_source_settings (
    id integer primary key check (id = 1),
    source_type text not null default 'local'
);
alter table public.price_source_settings
    drop constraint if exists price_source_settings_source_type_check;
alter table public.price_source_settings
    add constraint price_source_settings_source_type_check
    check (source_type in ('local', 'external', 'google'));
insert into public.price_source_settings (id, source_type)
values (1, 'local') on conflict (id) do nothing;
alter table public.price_source_settings enable row level security;
revoke all on public.price_source_settings from anon, authenticated;

-- 3. Inventarios independientes (Excel) --------------------------------
create table if not exists public.price_inventories (
    id bigint generated always as identity primary key,
    name text not null unique,
    is_active boolean not null default false
);
create unique index if not exists only_one_active_inventory
    on public.price_inventories (is_active) where is_active;
create table if not exists public.price_inventory_items (
    inventory_id bigint not null references public.price_inventories(id) on delete cascade,
    barcode text not null,
    name text not null,
    price numeric(14,2) not null check (price >= 0),
    primary key (inventory_id, barcode)
);
alter table public.price_inventories enable row level security;
alter table public.price_inventory_items enable row level security;
grant select on public.price_inventories, public.price_inventory_items to anon, authenticated;
drop policy if exists read_active_inventories on public.price_inventories;
create policy read_active_inventories on public.price_inventories
    for select to anon, authenticated using (is_active);
drop policy if exists read_active_inventory_items on public.price_inventory_items;
create policy read_active_inventory_items on public.price_inventory_items
    for select to anon, authenticated using (exists (
        select 1 from public.price_inventories i
        where i.id = inventory_id and i.is_active));

create or replace function public.activate_price_inventory(target_id bigint)
returns void language plpgsql security definer set search_path = public as $$
begin
    if not exists (select 1 from public.price_inventories where id = target_id) then
        raise exception 'Inventario no existe';
    end if;
    update public.price_inventories set is_active = false where is_active;
    update public.price_inventories set is_active = true where id = target_id;
end $$;

create or replace function public.replace_price_inventory(target_id bigint, new_items jsonb)
returns void language plpgsql security definer set search_path = public as $$
begin
    if not exists (select 1 from public.price_inventories where id = target_id) then
        raise exception 'Inventario no existe';
    end if;
    delete from public.price_inventory_items where inventory_id = target_id;
    insert into public.price_inventory_items (inventory_id, barcode, name, price)
    select target_id, x.barcode, x.name, x.price
    from jsonb_to_recordset(new_items) as x(barcode text, name text, price numeric);
end $$;
revoke all on function public.activate_price_inventory(bigint) from public, anon, authenticated;
revoke all on function public.replace_price_inventory(bigint, jsonb) from public, anon, authenticated;
grant execute on function public.activate_price_inventory(bigint) to service_role;
grant execute on function public.replace_price_inventory(bigint, jsonb) to service_role;

-- 4. Fuente Google Drive / Sheets (una sola fila, id = 1) ---------------
create table if not exists public.google_price_source (
    id integer primary key check (id = 1),
    refresh_token_encrypted text,
    kind text check (kind in ('excel', 'sheets')),
    file_id text,
    sheet_name text not null default '',
    code_column text,
    name_column text,
    price_column text
);
alter table public.google_price_source enable row level security;
revoke all on public.google_price_source from anon, authenticated;

-- 5. Fuentes externas SQL Server y colas del conector Windows -----------
create table if not exists public.external_price_sources (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    engine text not null default 'SQL Server',
    host text not null,
    port integer not null check (port between 1 and 65535),
    database text not null,
    schema_name text not null default 'dbo',
    table_name text not null,
    code_column text not null,
    description_column text not null,
    price_column text not null,
    enabled boolean not null default true,
    created_at timestamptz not null default now()
);
create table if not exists public.external_price_jobs (
    id uuid primary key default gen_random_uuid(),
    configuration_id uuid not null references public.external_price_sources(id),
    barcode text not null,
    status text not null default 'pending'
        check (status in ('pending', 'processing', 'done', 'error')),
    result jsonb,
    error_message text,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null default (now() + interval '2 minutes')
);
create index if not exists external_price_jobs_pending_idx
    on public.external_price_jobs (status, created_at);

create table if not exists public.external_metadata_jobs (
    id uuid primary key default gen_random_uuid(),
    kind text not null,
    host text not null,
    port integer not null check (port between 1 and 65535),
    database text, schema_name text, table_name text,
    status text not null default 'pending'
        check (status in ('pending', 'processing', 'done', 'error')),
    result jsonb,
    error_message text,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null default (now() + interval '2 minutes')
);
alter table public.external_metadata_jobs
    drop constraint if exists external_metadata_jobs_kind_check;
alter table public.external_metadata_jobs
    add constraint external_metadata_jobs_kind_check
    check (kind in ('databases', 'tables', 'columns', 'connection'));
create index if not exists external_metadata_jobs_pending_idx
    on public.external_metadata_jobs (status, created_at);

create table if not exists public.external_catalog_jobs (
    id uuid primary key default gen_random_uuid(),
    configuration_id uuid not null references public.external_price_sources(id),
    page_number integer not null check (page_number >= 1),
    page_size integer not null check (page_size between 1 and 100),
    search_term text not null default '',
    status text not null default 'pending'
        check (status in ('pending', 'processing', 'done', 'error')),
    result jsonb,
    error_message text,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null default (now() + interval '3 minutes')
);
create index if not exists external_catalog_jobs_pending_idx
    on public.external_catalog_jobs (status, created_at);

create table if not exists public.lan_discovery_requests (
    id uuid primary key,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    status text not null default 'pending'
        check (status in ('pending', 'selected', 'cancelled')),
    selected_engine text,
    selected_host text,
    selected_port integer,
    selected_database text
);
alter table public.lan_discovery_requests add column if not exists selected_database text;
create index if not exists lan_discovery_requests_expires_idx
    on public.lan_discovery_requests (expires_at);

create table if not exists public.lan_db_requests (
    id uuid primary key,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    status text not null default 'pending'
        check (status in ('pending', 'done', 'cancelled')),
    host inet not null,
    port integer not null check (port between 1 and 65535),
    engine text not null check (engine = 'SQL Server'),
    database_names jsonb not null default '[]'::jsonb
);

alter table public.external_price_sources enable row level security;
alter table public.external_price_jobs enable row level security;
alter table public.external_metadata_jobs enable row level security;
alter table public.external_catalog_jobs enable row level security;
alter table public.lan_discovery_requests enable row level security;
alter table public.lan_db_requests enable row level security;
revoke all on public.external_price_sources, public.external_price_jobs,
    public.external_metadata_jobs, public.external_catalog_jobs,
    public.lan_discovery_requests, public.lan_db_requests from anon, authenticated;

-- 6. Zona autorizada de Consulta Móvil (una sola fila, id = 1) ----------
create table if not exists public.mobile_geo_settings (
    id integer primary key check (id = 1),
    enabled boolean not null default true,
    latitude double precision not null default 0 check (latitude between -90 and 90),
    longitude double precision not null default 0 check (longitude between -180 and 180),
    radius_m integer not null default 100
);
alter table public.mobile_geo_settings
    drop constraint if exists mobile_geo_settings_radius_m_check;
alter table public.mobile_geo_settings
    add constraint mobile_geo_settings_radius_m_check
    check (radius_m between 10 and 10000);
insert into public.mobile_geo_settings (id, enabled, latitude, longitude, radius_m)
values (1, true, 0, 0, 100) on conflict (id) do nothing;
alter table public.mobile_geo_settings enable row level security;
revoke all on public.mobile_geo_settings from anon, authenticated;
-- 0,0 no es la ubicación del negocio: configúrala desde la app.

-- 6b. Registro de consultas (códigos buscados y no encontrados) -----
create table if not exists public.price_lookup_log (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    barcode text not null,
    found boolean not null,
    product_name text,
    price numeric(14,2),
    source text,     -- local (Excel) | google | external (SQL Server)
    channel text     -- verificador | movil-camara | movil-manual | movil-foto
);
create index if not exists price_lookup_log_fecha_idx on public.price_lookup_log (created_at desc);
create index if not exists price_lookup_log_no_encontrados_idx
    on public.price_lookup_log (barcode, created_at desc) where not found;
alter table public.price_lookup_log enable row level security;
revoke all on public.price_lookup_log from anon, authenticated;

-- 7. Almacenamiento privado del logo y el QR ----------------------------
insert into storage.buckets (id, name, public)
values ('logo-negocio', 'logo-negocio', false)
on conflict (id) do nothing;

-- Limpieza opcional de trabajos vencidos (ejecutar cuando se desee):
-- delete from public.external_price_jobs    where expires_at < now() - interval '1 day';
-- delete from public.external_metadata_jobs where expires_at < now() - interval '1 day';
-- delete from public.external_catalog_jobs  where expires_at < now() - interval '1 day';
-- delete from public.lan_discovery_requests where expires_at < now() - interval '1 day';

-- ===== Equipos sin internet (MIGRACION_004) =====
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
