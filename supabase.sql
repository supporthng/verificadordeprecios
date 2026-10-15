-- Ejecutar en Supabase SQL Editor. No incluir claves secretas en GitHub.
create table if not exists public.products (
  barcode text primary key,
  name text not null,
  price numeric(14,2) not null check(price>=0),
  updated_at timestamptz not null default now()
);
create table if not exists public.admin_users (
  user_id uuid primary key references auth.users(id) on delete cascade
);
alter table public.products enable row level security;
alter table public.admin_users enable row level security;
create policy "Public catalog read" on public.products for select to anon, authenticated using (true);
create policy "Admin insert" on public.products for insert to authenticated with check (exists(select 1 from public.admin_users a where a.user_id=(select auth.uid())));
create policy "Admin update" on public.products for update to authenticated using (exists(select 1 from public.admin_users a where a.user_id=(select auth.uid()))) with check (exists(select 1 from public.admin_users a where a.user_id=(select auth.uid())));
-- Tras crear usuario en Authentication, reemplazar el UUID y ejecutar SOLO en SQL Editor:
-- insert into public.admin_users(user_id) values ('UUID-DEL-USUARIO');
