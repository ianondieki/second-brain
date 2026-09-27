# REQ-BIL-03

- Task: T2.5 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend; security-reviewer (Fable) (billing)
- Files owned: `bridge/proposals/grants.py`, `bridge/billing/entitlements.py` (unlock counter)
- Depends on: T2.5.

## Scope

A full unlock is the first Tier-2 `disclosure_grant` on an untagged proposal to an org in a billing month, checked when the grant is created (402 over `full_unlocks_per_month`; grants on proposals tagged to that org never count). The count is per org per billing month (`billing_month`), under a lock so concurrent grants cannot exceed the cap.

## Acceptance criteria and tests

AC-SUB-7 (`integration/billing/test_unlocks.py::test_sixth_unlock_402_tagged_ok`).
