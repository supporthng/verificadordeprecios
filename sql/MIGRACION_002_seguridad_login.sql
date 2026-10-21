-- Ejecutar UNA VEZ en Supabase > SQL Editor si tu base ya estaba instalada.
-- 1) Bloqueo de cuentas por intentos fallidos guardado en la base
--    (antes bastaba con recargar la página para reiniciar el contador).
alter table public.verificador_usuarios
  add column if not exists failed_attempts integer not null default 0,
  add column if not exists locked_until timestamptz;

-- 2) La cuenta de verificador ya no depende del nombre 'consulta':
--    se marca con el permiso 'solo_consulta' (Modo verificador / kiosko).
update public.verificador_usuarios
   set permissions = array_append(permissions, 'solo_consulta')
 where lower(username) = 'consulta'
   and role <> 'admin'
   and not ('solo_consulta' = any(permissions));

-- Desbloquear manualmente una cuenta si hiciera falta:
-- update public.verificador_usuarios set failed_attempts = 0, locked_until = null where username = 'NOMBRE';
