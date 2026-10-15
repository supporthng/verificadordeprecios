-- Ejecutar en Supabase > SQL Editor. La clave service_role NUNCA debe ir en GitHub.
create table if not exists public.products (
  barcode text primary key,
  name text not null,
  price numeric(14,2) not null check(price >= 0),
  updated_at timestamptz not null default now()
);
create table if not exists public.admin_users (
  user_id uuid primary key references auth.users(id) on delete cascade
);
alter table public.products enable row level security;
alter table public.admin_users enable row level security;
drop policy if exists "Public catalog read" on public.products;
drop policy if exists "Admin insert" on public.products;
drop policy if exists "Admin update" on public.products;
create policy "Public catalog read" on public.products for select to anon, authenticated using (true);
create policy "Admin insert" on public.products for insert to authenticated
with check (exists(select 1 from public.admin_users a where a.user_id = (select auth.uid())));
create policy "Admin update" on public.products for update to authenticated
using (exists(select 1 from public.admin_users a where a.user_id = (select auth.uid())))
with check (exists(select 1 from public.admin_users a where a.user_id = (select auth.uid())));
-- Para permitir publicar desde Android PWA, crear usuario en Authentication > Users
-- y ejecutar después, sustituyendo el UUID por el identificador real:
-- insert into public.admin_users(user_id) values ('UUID-DEL-USUARIO');
