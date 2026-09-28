-- Prepare one Bridge database (run as a superuser while connected to it; idempotent).
-- Extensions need superuser (docs/spec/08: pgvector, citext, pgcrypto). The public schema belongs to bridge_owner
-- and nobody else may create objects in it.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
ALTER SCHEMA public OWNER TO bridge_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO bridge_app, aggregate_worker, audit_reader;
-- The Tier-2 roles (roles.sql) resolve public.proposal_confidential after bridge_app switches to them.
GRANT USAGE ON SCHEMA public TO tier2_reader, provenance_worker, tier2_embed_worker, tier2_moderation, dsr_exporter;
-- No temporary objects for anyone but the owner: a temporary domain or table could shadow names that functions
-- resolve (defence in depth; every function also pins search_path with pg_temp last).
DO $$
BEGIN
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
END
$$;
