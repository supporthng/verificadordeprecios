-- Ejecutar UNA vez en SQL Editor de Supabase (proyecto correcto).
create table if not exists public.lan_db_requests (
  id uuid primary key,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  status text not null default 'pending' check (status in ('pending','done','cancelled')),
  host inet not null,
  port integer not null check (port between 1 and 65535),
  engine text not null check (engine = 'SQL Server'),
  database_names jsonb not null default '[]'::jsonb
);
alter table public.lan_db_requests enable row level security;
-- Sin políticas para anon/authenticated: acceso solo a service_role.
revoke all on public.lan_db_requests from anon, authenticated;
grant all on public.lan_db_requests to service_role;
