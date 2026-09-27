# REQ-TEN-01

- Task: T1.4, T1.5 (`docs/platform/PLAN.md` Phase 1)
- Agent: db-migrations (revisions); orchestrator / impl-backend (models, dependencies, tests); security-reviewer (Fable) review
- Files owned: `backend/alembic/versions/`, `bridge/tenancy/`, `bridge/db.py`, `backend/tests/integration/test_rls.py`
- Depends on: T1.3.

## Scope

Organisations, memberships (roles array), invitations; RLS on every tenant-scoped table via `set_config` of `app.user_id` / `app.org_id` per transaction; `app_is_member()` SECURITY DEFINER helper; `require_role`; `aggregate_worker` role (no grants on tenant tables); 404 for non-members, 403 for members lacking a role; RLS test generated from table metadata (every table classified).

## Acceptance criteria and tests

AC-SEC-1/a: `backend/tests/integration/test_rls.py` (parametrised over tenant tables from metadata; cross-tenant API returns 404).

## Notes

Only `db-migrations` writes Alembic revisions. Roles: `bridge_owner` (migrations), `bridge_app` (API and worker; no BYPASSRLS, no ownership), `aggregate_worker`, `audit_reader`.

## Phase 2 (T2.1)

AC-SEC-1/b: the full parametrised RLS test over every tenant table of schema v2 (org, user, org_or_user, published drafts, staff tables), developer A reads 0 of developer B's drafts and Tier-2 rows, an org without a grant reads 0 `proposal_confidential` rows, `aggregate_worker` reads 0 rows of every tenant table, cross-tenant API access returns 404. Schema design in `REQ-REPO-01.md` (T2.1 section).
