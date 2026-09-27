# REQ-BIL-02

- Task: T2.3, T2.7 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend
- Files owned: `bridge/billing/entitlements.py` (helpers only), cap checks in `bridge/proposals/{service,tags}.py`
- Depends on: T2.3, T2.7.

## Scope

Plan caps from `plans.yaml`: `active_proposals` (Free 3) checked at publish; `tags_per_proposal` (Free 5, Pro 20) checked per tag; 402 with the upgrade path and nothing created. Tagging within caps is never gated behind NDA, tracker or messaging.

## Acceptance criteria and tests

AC-SUB-1 (`integration/billing/test_caps.py::test_fourth_proposal_402`), AC-PROP-2 (`::test_sixth_tag_402`).
