-- Ejecutar una vez en Supabase SQL Editor.
-- No altera la tabla products ni el verificador original.
CREATE TABLE IF NOT EXISTS public.external_price_sources (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 name text NOT NULL UNIQUE,
 engine text NOT NULL DEFAULT 'SQL Server',
 host text NOT NULL, port integer NOT NULL CHECK (port BETWEEN 1 AND 65535),
 database text NOT NULL,
 schema_name text NOT NULL DEFAULT 'dbo', table_name text NOT NULL,
 code_column text NOT NULL, description_column text NOT NULL, price_column text NOT NULL,
 enabled boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.external_price_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 configuration_id uuid NOT NULL REFERENCES public.external_price_sources(id),
 barcode text NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','done','error')),
 result jsonb, error_message text,
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL DEFAULT (now() + interval '2 minutes')
);
CREATE INDEX IF NOT EXISTS external_price_jobs_pending_idx
 ON public.external_price_jobs (status, created_at);
ALTER TABLE public.external_price_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.external_price_jobs ENABLE ROW LEVEL SECURITY;
-- Solo el backend con service_role puede leer/escribir estas tablas.


-- Solicitudes de descubrimiento de metadatos. Solo service_role.
CREATE TABLE IF NOT EXISTS public.external_metadata_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 kind text NOT NULL CHECK (kind IN ('databases','tables','columns')),
 host text NOT NULL, port integer NOT NULL CHECK (port BETWEEN 1 AND 65535),
 database text, schema_name text, table_name text,
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','done','error')),
 result jsonb, error_message text,
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL DEFAULT (now()+interval '2 minutes')
);
CREATE INDEX IF NOT EXISTS external_metadata_jobs_pending_idx
 ON public.external_metadata_jobs(status,created_at);
ALTER TABLE public.external_metadata_jobs ENABLE ROW LEVEL SECURITY;
