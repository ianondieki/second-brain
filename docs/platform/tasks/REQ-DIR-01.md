# REQ-DIR-01

- Task: T2.6a (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (API, seed), impl-frontend (Companies, F1)
- Files owned: `bridge/directory/{service,router,schemas}.py`, `bridge/seed/`, `frontend/app/(app)/dev/companies/`
- Depends on: T2.1.

## Scope

Niche taxonomy (two-level, ISIC-mapped, seeded in Phase 1) and org types; an admin can add a niche without a deploy (staff route) and it becomes selectable in the directory and the editor at once. Directory API and screen grouped by niche headings with org-type and county filters; cards show name, niche, org type, county and the verification badge, never a logo; the responsiveness score shows only for E2 with ≥10 eligible tags and 60 days after the claim (rules in code; values from fixtures until Phase 3).

## Acceptance criteria and tests

AC-DIR-5/a, AC-DIR-6 (`integration/directory/test_seed_and_browse.py`). AC-DIR-5/b is Phase 4.
