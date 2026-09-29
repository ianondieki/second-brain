# REQ-ADM-01

- Task: T2.6b, T2.3 (queue parts only; the full console is Phase 8) (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend, impl-frontend (F4)
- Files owned: `bridge/admin/{deps,router,claims,moderation}.py`, `frontend/app/(admin)/`
- Depends on: T2.1.

## Scope

Phase 2 part: the `/admin` console shell (separate from both portals) with the claim queue (2 BD SLA shown), the moderation queue and the D2 KYC review queue; the staff dependency (staff role + enrolled and verified TOTP; 404 for non-staff; Phase 1 follow-up 5); every decision audited. Impersonation, flags, refunds, research approval and the rest are Phase 8.

## Acceptance criteria and tests

Phase 2 tests: `integration/admin/test_moderation_queue.py`, `integration/directory/test_claims.py`. AC-ADM-3 is Phase 8.

## Notes (T2.6a, staff dependency)

- `bridge/admin/deps.py`: `staff_member(*roles)` (`StaffMember`, `StaffAdmin`, `StaffModerator`). 404 (the API's
  not-found body) when signed out, second factor pending, not staff, or staff without TOTP; 403 for enrolled staff
  lacking the route's role; 403 `step_up_required` when the second factor is older than `STEP_UP_MAX_AGE_HOURS`
  (these are enrolled staff, so the console's existence is not a secret to them).
- Routes so far: `GET /api/admin/me` (any staff; the console shell's access check), `GET /api/admin/niches` (staff
  admin; inactive niches included) and `POST /api/admin/niches` (staff admin; `app_add_niche` decides in SQL: 201,
  409 `niche_slug_taken`, 422 `parent_niche_not_top_level` / `parent_niche_not_found` or a malformed body; the
  database's own staff refusal answers 404 like the dependency; audited `directory.niche_added` as the staff actor,
  subject the niche, payload `parent_id` only). Tests: `integration/admin/test_staff_dependency.py`,
  `integration/admin/test_add_niche.py`, `unit/admin/test_niche_refusals.py`.
- Open: `/api/openapi.json` is served in every environment and lists the `/api/admin` paths; if the console must not
  be discoverable from the schema either, production needs the admin router excluded from the public document.
