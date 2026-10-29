# REQ-BIL-01

- Task: T1.6 (`docs/platform/PLAN.md` Phase 1)
- Agent: impl-backend
- Files owned: `backend/config/plans.yaml`, `bridge/billing/`
- Depends on: T1.4.

## Scope

`backend/config/plans.yaml` placeholders (the eight plans from docs/spec/05, KES minor units, limits incl. `llm_monthly_cap_usd`, scout frequencies, digest cadence); server-side entitlement dependency returning 402 with the upgrade path; free subscription rows at signup.

## Acceptance criteria and tests

Unit: `backend/tests/unit/billing/test_entitlements.py`. AC-SUB-1 closes in Phase 2 (needs proposals).

## Notes

Prices are placeholders until G3.
