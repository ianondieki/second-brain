# REQ-DIR-05

- Task: T2.6d (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend, impl-frontend (org Problems, F4)
- Files owned: `bridge/problems/briefs.py`, `frontend/app/(app)/org/problems/`
- Depends on: T2.1, T2.6b (E2 orgs).

## Scope

Problem Briefs by verified (E2) orgs: public or invited-only, optional budget band and deadline, the ProblemCard fields with `source=org_brief`, moderated (pre-screen + queue) before publication; plan cap `problem_briefs` (402). E1 orgs cannot publish Briefs.

## Acceptance criteria and tests

`integration/problems/test_briefs.py` (AC-PERS-7 closes in Phase 5).
