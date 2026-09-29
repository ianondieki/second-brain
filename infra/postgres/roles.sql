-- Database roles for Bridge (REQ-TEN-01, REQ-REPO-01; docs/spec/08 Tenancy; docs/spec/06 6.1; ADR-002).
-- Run as a superuser, once per cluster; idempotent (re-run it on an existing cluster after pulling new roles: the
-- revision that first grants to a role refuses to run until the role exists). Used by the dev compose init script
-- and the test harness (Terraform in Phase 8). Roles are created NOLOGIN here; environments that log in as them add
-- LOGIN + PASSWORD.
--   bridge_owner        owns every table; migrations and the seed run as it. Never used by the API or workers.
--   bridge_app          API and worker role: DML only where granted, RLS applies (no BYPASSRLS, owns nothing).
--   aggregate_worker    reads only signal_events; no grant on any tenant table.
--   audit_reader        reads the whole audit chain (and its anchors) for the nightly verifier; no other grants.
-- Tier-2 roles (docs/spec/06 6.1). bridge_app is a member of each WITH INHERIT FALSE, SET TRUE: it holds none of their
-- privileges (has_table_privilege('bridge_app', 'proposal_confidential', 'SELECT') is false) and can only switch to
-- one with SET LOCAL ROLE (bridge.db.as_role) after the application check passes; RLS still applies to each.
--   tier2_reader        request path after can_view_tier2() passes: the owner's drafts and granted Tier-2 renders.
--   provenance_worker   registration jobs: reads the owner's Tier-2 for the manifest, writes provenance records.
--   tier2_embed_worker  embeds the owner's Tier-2 text into proposal_confidential_embeddings.
--   tier2_moderation    staff-only Tier-2 similarity job and evidence packs.
--   dsr_exporter        data-subject exports of the subject's own Tier-2 rows.
DO $$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY[
    'bridge_owner', 'bridge_app', 'aggregate_worker', 'audit_reader',
    'tier2_reader', 'provenance_worker', 'tier2_embed_worker', 'tier2_moderation', 'dsr_exporter'
  ] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', r);
    END IF;
  END LOOP;
  FOREACH r IN ARRAY ARRAY['tier2_reader', 'provenance_worker', 'tier2_embed_worker', 'tier2_moderation', 'dsr_exporter']
  LOOP
    -- PostgreSQL 16 membership options. Re-granting sets the options again, so an existing membership is corrected.
    IF NOT EXISTS (
      SELECT 1 FROM pg_auth_members m
       WHERE m.roleid = r::regrole AND m.member = 'bridge_app'::regrole
         AND NOT m.inherit_option AND m.set_option AND NOT m.admin_option
    ) THEN
      EXECUTE format('GRANT %I TO bridge_app WITH INHERIT FALSE, SET TRUE, ADMIN FALSE', r);
    END IF;
  END LOOP;
END
$$;
