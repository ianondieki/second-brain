# REQ-SEC-01

- Task: T2.5 (Tier-2 flag); the deals flag lands in Phase 3 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend
- Files owned: `bridge/config.py`, `bridge/proposals/access.py`
- Depends on: T2.5.

## Scope

`FEATURE_TIER2_ENABLED` (default false; production stays false until G2) gates every Tier-2 endpoint (reads, renders, attachments, NDA acceptance, grant requests and policy changes that release Tier 2): 403 `tier2_disabled` regardless of NDA state. The test enumerates Tier-2 routes from the OpenAPI document (tag `tier2`), so a new route cannot escape.

## Acceptance criteria and tests

AC-SEC-2 (`integration/test_feature_flags.py::test_tier2_flag`). AC-SEC-7 is Phase 3.
