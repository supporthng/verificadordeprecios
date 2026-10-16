-- Ejecutar una vez en Supabase SQL Editor. Conserva las tablas y los datos.
ALTER TABLE public.external_metadata_jobs
  DROP CONSTRAINT IF EXISTS external_metadata_jobs_kind_check;
ALTER TABLE public.external_metadata_jobs
  ADD CONSTRAINT external_metadata_jobs_kind_check
  CHECK (kind IN ('databases', 'tables', 'columns', 'connection'));
