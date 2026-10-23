-- Ejecutar UNA VEZ en Supabase > SQL Editor.
-- Estado de los equipos sin internet: cada verificador avisa, cuando tiene internet,
-- que está encendido y qué versión de precios tiene. Una fila por equipo.
-- Los equipos NO pueden leer la tabla: solo llaman a equipo_reporta(), que valida los datos.
create table if not exists public.device_status (
    device_id text primary key,
    nombre text not null,
    tipo text not null default 'verificador',
    app_version text,
    precios_version text,
    productos integer,
    pendientes integer,
    navegador text,
    primera_vez timestamptz not null default now(),
    ultima_vez timestamptz not null default now()
);
alter table public.device_status enable row level security;
revoke all on public.device_status from anon, authenticated;

create or replace function public.equipo_reporta(
    p_id text, p_nombre text, p_tipo text, p_app text, p_precios text,
    p_productos integer, p_pendientes integer, p_navegador text)
returns void language plpgsql security definer set search_path = public as $$
declare
    v_nombre text := left(coalesce(nullif(trim(p_nombre), ''), 'Equipo'), 40);
begin
    if p_id is null or p_id !~ '^[A-Za-z0-9-]{8,64}$' then
        raise exception 'identificador inválido';
    end if;
    -- Freno simple: como máximo un reporte por minuto (salvo que cambie el nombre).
    if exists (select 1 from device_status where device_id = p_id and nombre = v_nombre
               and ultima_vez > now() - interval '1 minute') then
        return;
    end if;
    if (select count(*) from device_status) >= 200
       and not exists (select 1 from device_status where device_id = p_id) then
        raise exception 'demasiados equipos';
    end if;
    insert into device_status as d (device_id, nombre, tipo, app_version, precios_version, productos, pendientes, navegador)
    values (p_id, v_nombre,
            case when p_tipo in ('verificador', 'movil') then p_tipo else 'verificador' end,
            left(p_app, 20), left(p_precios, 40), greatest(p_productos, 0), greatest(p_pendientes, 0),
            left(p_navegador, 160))
    on conflict (device_id) do update set
        nombre = excluded.nombre, tipo = excluded.tipo, app_version = excluded.app_version,
        precios_version = excluded.precios_version, productos = excluded.productos,
        pendientes = excluded.pendientes, navegador = excluded.navegador, ultima_vez = now();
end $$;
revoke all on function public.equipo_reporta(text, text, text, text, text, integer, integer, text) from public;
grant execute on function public.equipo_reporta(text, text, text, text, text, integer, integer, text) to anon, authenticated, service_role;
