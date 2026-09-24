-- Prepare one Bridge database (run as a superuser while connected to it; idempotent).
-- Extensions need superuser (docs/spec/08: pgvector, citext, pgcrypto). The public schema belongs to bridge_owner
-- and nobody else may create objects in it.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
ALTER SCHEMA public OWNER TO bridge_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO bridge_app, aggregate_worker, audit_reader;
