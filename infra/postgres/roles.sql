-- Database roles for Bridge (REQ-TEN-01, docs/spec/08 Tenancy; ADR-002).
-- Run as a superuser, once per cluster; idempotent. Used by the dev compose init script and the test harness
-- (Terraform in Phase 8). Roles are created NOLOGIN here; environments that log in as them add LOGIN + PASSWORD.
--   bridge_owner      owns every table; migrations and the seed run as it. Never used by the API or workers.
--   bridge_app        API and worker role: DML only where granted, RLS applies (no BYPASSRLS, owns nothing).
--   aggregate_worker  reads only signal_events (Phase 2); no grant on any tenant table.
--   audit_reader      reads the whole audit chain for the nightly verifier; no other grants.
DO $$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['bridge_owner', 'bridge_app', 'aggregate_worker', 'audit_reader'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', r);
    END IF;
  END LOOP;
END
$$;
