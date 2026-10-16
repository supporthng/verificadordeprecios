-- Ejecutar una sola vez en Supabase SQL Editor.
-- Almacena únicamente el nombre de la base seleccionada, nunca credenciales.
ALTER TABLE public.lan_discovery_requests
ADD COLUMN IF NOT EXISTS selected_database text;
