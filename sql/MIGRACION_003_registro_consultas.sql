-- Ejecutar UNA VEZ en Supabase > SQL Editor.
-- Registro de consultas de precios: qué códigos se buscan y cuáles NO se encuentran.
-- Solo el servidor (clave secreta) puede leer y escribir: los clientes no lo ven.
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

-- Limpieza manual de registros antiguos (la página Registro de consultas también lo hace):
-- delete from public.price_lookup_log where created_at < now() - interval '90 days';
