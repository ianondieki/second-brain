# REQ-PROP-01

- Task: T2.3 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (API), impl-frontend (wizard, F2)
- Files owned: `bridge/proposals/{editor,router,schemas,service}.py`, `bridge/problems/{service,router}.py`, `frontend/app/(app)/dev/ideas/`
- Depends on: T2.1, T2.2 (moderation pre-screen through `LLMClient`).

## Scope

3-step wizard (Problem & teaser → Full details → Review, attest & publish). Drafts are Tier 0 (owner only: a draft `proposal_versions` row plus its Tier-2 draft in `proposal_confidential` through `tier2_reader`). Linked Problem picker (published problems, filter by niche) or "Describe a new problem" (creates a Problem with `source=developer`, labelled "Developer-reported", published at once and queued for moderation without blocking). Niche label (`Parent › Child`), maturity, ask. Publishing validates (≥1 linked Problem, `niche_id`, Tier-1 sanitiser, summary ≤150 words), requires D1 (AC-IP-5), checks the active-proposal cap (AC-SUB-1: 402, nothing created), records the three ownership attestations, registers the version (enqueues the T2.4 pipeline; `proposal.version_registered`), writes `signal_events` and the audit event. Publishing is the screen's one primary action.

## Acceptance criteria and tests

AC-REPO-4/a (`unit/proposals/test_publish_validation.py`, `frontend/e2e/proposal-wizard.spec.ts`), AC-PROP-5 (`integration/proposals/test_new_problem_flow.py`), AC-SUB-1 (`integration/billing/test_caps.py::test_fourth_proposal_402`).
