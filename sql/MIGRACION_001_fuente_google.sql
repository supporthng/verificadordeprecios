-- Ejecutar UNA VEZ en Supabase > SQL Editor si tu base ya estaba instalada.
-- Corrige el error que impedía activar Google Drive / Sheets como fuente:
-- la restricción anterior aceptaba 'cloud', pero la aplicación guarda 'google'.

-- Quitar cualquier CHECK previo sobre source_type, sin importar su nombre.
do $$
declare r record;
begin
  for r in select conname from pg_constraint
           where conrelid = 'public.price_source_settings'::regclass and contype = 'c'
             and pg_get_constraintdef(oid) ilike '%source_type%'
  loop
    execute format('alter table public.price_source_settings drop constraint %I', r.conname);
  end loop;
end $$;

-- Si alguna fila quedó con el valor antiguo, convertirla.
update public.price_source_settings set source_type = 'google' where source_type = 'cloud';

alter table public.price_source_settings
  add constraint price_source_settings_source_type_check
  check (source_type in ('local', 'external', 'google'));

-- Tabla que usa la app para la conexión Google (la anterior cloud_price_sources no se usa).
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

-- Opcional: eliminar la tabla sin uso creada por INSTALAR_GOOGLE_DRIVE.sql
-- drop table if exists public.cloud_price_sources;
