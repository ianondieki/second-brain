# REQ-DIR-01

- Task: T2.6a (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (API, seed), impl-frontend (Companies, F1)
- Files owned: `bridge/directory/{service,router,schemas}.py`, `bridge/seed/`, `frontend/app/(app)/dev/companies/`
- Depends on: T2.1.

## Scope

Niche taxonomy (two-level, ISIC-mapped, seeded in Phase 1) and org types; an admin can add a niche without a deploy (staff route) and it becomes selectable in the directory and the editor at once. Directory API and screen grouped by niche headings with org-type and county filters; cards show name, niche, org type, county and the verification badge, never a logo; the responsiveness score shows only for E2 with ≥10 eligible tags and 60 days after the claim (rules in code; values from fixtures until Phase 3).

## Acceptance criteria and tests

AC-DIR-5/a, AC-DIR-6 (`integration/directory/test_seed_and_browse.py`). AC-DIR-5/b is Phase 4.

## Notes (T2.6a backend, branch `feat/REQ-DIR-02-provisional-seed`)

- Routes: `GET /api/directory/orgs` (groups under `Parent › Child` headings; repeatable `kind`, `county` (ISO
  3166-2:KE), `niche` (a parent slug includes its children) filters, at most 50 values each; `q` name search; keyset
  `cursor` over (heading, organisation) pairs, `limit` ≤ 100), `GET /api/directory/orgs/{org_id}` (404 for unknown,
  unlisted or delisted ids), `GET /api/directory/niches` (active niches, two levels, labels, ISIC codes) and
  `GET /api/directory/filter-options` (org types with their docs/spec/03 labels, the 47 counties). Signed-in only.
- Listed = `unclaimed`/`e1`/`e2` and not delisted; the queries repeat the RLS rule, so a member never sees their own
  pending or delisted organisation in the directory. Organisations without a niche come last under a null heading.
  Inactive niches are left out of the picker; organisations keep showing under them until re-tagged.
- Badge copy: E0 and E1 exact from docs/spec/06 6.2. **E2 has no spec copy**: "Legal entity verified", tagged
  `[[COPY-REVIEW]]` in `bridge/directory/service.py`.
- Responsiveness: rules in `bridge/directory/responsiveness.py` (new file): E2, ≥ 10 eligible tags and ≥ 60 days after
  `organizations.e2_verified_at` (read as "after the claim" reached E2). Numbers from a `ResponsivenessSource` on
  `app.state.responsiveness`: none until Phase 3, `FixtureResponsiveness` in tests. The tag count is never exposed.
- **Deviation (schema):** the admin niche route `POST /api/admin/niches` is not built: `bridge_app` holds SELECT only
  on `niches`, and only `db-migrations` adds grants or functions. Needed: a SECURITY DEFINER
  `app_add_niche(p_slug text, p_name_en text, p_parent_slug text DEFAULT NULL, p_isic_code text DEFAULT NULL) RETURNS
  uuid` (pinned search_path, EXECUTE to `bridge_app` only; refuses unless `app_is_staff('{admin}')`; a parent must
  exist and be top level; unique slug). Until then `test_a_niche_added_at_run_time_is_selectable_at_once` proves the
  "without a deploy" half with a niche inserted while the app runs; it switches to the route when the function lands.
- `backend/pyproject.toml`: ruff `allowed-confusables = ["›"]` (the niche separator).
