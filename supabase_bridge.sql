-- Ejecutar una vez en Supabase SQL Editor.
-- Solo el service_role puede leer/escribir esta tabla. Nunca habilitar políticas anon.
create table if not exists public.lan_discovery_requests (
 id uuid primary key,
 created_at timestamptz not null default now(),
 expires_at timestamptz not null,
 status text not null default 'pending' check (status in ('pending','selected','cancelled')),
 selected_engine text,
 selected_host text,
 selected_port integer
);
alter table public.lan_discovery_requests enable row level security;
revoke all on public.lan_discovery_requests from anon, authenticated;
create index if not exists lan_discovery_requests_expires_idx on public.lan_discovery_requests(expires_at);
-- Opcional, limpiar solicitudes vencidas periódicamente:
-- delete from public.lan_discovery_requests where expires_at < now() - interval '1 day';
