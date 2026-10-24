-- =====================================================================
-- MIGRACION_007 · Equipos sin internet por sucursal
-- Ejecutar en Supabase > SQL Editor DESPUÉS de MIGRACION_006. Idempotente.
-- Los equipos informan a qué sucursal pertenecen (solo se acepta una sucursal existente).
-- La versión anterior de equipo_reporta (8 datos) se reemplaza por esta (9, el último opcional):
-- los equipos con la app anterior siguen reportando igual.
-- =====================================================================

drop function if exists public.equipo_reporta(text, text, text, text, text, integer, integer, text);

create or replace function public.equipo_reporta(
    p_id text, p_nombre text, p_tipo text, p_app text, p_precios text,
    p_productos integer, p_pendientes integer, p_navegador text, p_sucursal text default null)
returns void language plpgsql security definer set search_path = public as $$
declare
    v_nombre text := left(coalesce(nullif(trim(p_nombre), ''), 'Equipo'), 40);
    v_sucursal text := (select codigo from sucursales where codigo = p_sucursal limit 1);
begin
    if p_id is null or p_id !~ '^[A-Za-z0-9-]{8,64}$' then
        raise exception 'identificador inválido';
    end if;
    -- Freno simple: como máximo un reporte por minuto (salvo que cambie el nombre o la sucursal).
    if exists (select 1 from device_status where device_id = p_id and nombre = v_nombre
               and coalesce(sucursal, '') = coalesce(v_sucursal, '')
               and ultima_vez > now() - interval '1 minute') then
        return;
    end if;
    if (select count(*) from device_status) >= 200
       and not exists (select 1 from device_status where device_id = p_id) then
        raise exception 'demasiados equipos';
    end if;
    insert into device_status as d (device_id, nombre, tipo, app_version, precios_version, productos,
                                    pendientes, navegador, sucursal)
    values (p_id, v_nombre,
            case when p_tipo in ('verificador', 'movil') then p_tipo else 'verificador' end,
            left(p_app, 20), left(p_precios, 40), greatest(p_productos, 0), greatest(p_pendientes, 0),
            left(p_navegador, 160), v_sucursal)
    on conflict (device_id) do update set
        nombre = excluded.nombre, tipo = excluded.tipo, app_version = excluded.app_version,
        precios_version = excluded.precios_version, productos = excluded.productos,
        pendientes = excluded.pendientes, navegador = excluded.navegador, sucursal = excluded.sucursal,
        ultima_vez = now();
end $$;
revoke all on function public.equipo_reporta(text, text, text, text, text, integer, integer, text, text) from public;
grant execute on function public.equipo_reporta(text, text, text, text, text, integer, integer, text, text)
    to anon, authenticated, service_role;
