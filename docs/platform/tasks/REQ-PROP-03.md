# REQ-PROP-03

- Task: T2.7 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (API), impl-integrations (EM1), impl-frontend (picker, F2)
- Files owned: `bridge/proposals/tags.py`, tag routes, `frontend/app/(app)/dev/ideas/[id]/pitch/`
- Depends on: T2.3, T2.6 (directory, E0/E1/E2).

## Scope

"Pitch to company": a directory picker grouped by niche showing E0/E1/E2; multi-tag within the plan cap (`tags_per_proposal`); E2 → `delivered` tag (the `SUBMITTED` engagement is derived in Phase 3, AC-PROP-1/b); E0 → `held_unclaimed` with the spec sentence and zero emails; E1 → `held_pending_verification` (the org sees only a count). One open engagement or held tag per (developer, org): 409 with the reason and nothing created; 30-day cooldown after a decline (engagement fixture). EM1 lists sent and saved groups. Tagging within caps is never gated behind NDA, tracker or messaging (AC-SUB-5 is Phase 3).

## Acceptance criteria and tests

AC-PROP-1/a (`integration/proposals/test_tags.py::test_mixed_tags`), AC-PROP-2 (`integration/billing/test_caps.py::test_sixth_tag_402`), AC-PROP-7 (`integration/proposals/test_tags.py::test_duplicate_org_409`), AC-DIR-1 (`integration/directory/test_held_tags.py`).
