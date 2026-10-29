# REQ-BIL-02

- Task: T2.3, T2.7 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend
- Files owned: `bridge/billing/entitlements.py` (helpers only), cap checks in `bridge/proposals/{service,tags}.py`
- Depends on: T2.3, T2.7.

## Scope

Plan caps from `plans.yaml`: `active_proposals` (Free 3) checked at publish; `tags_per_proposal` (Free 5, Pro 20) checked per tag; 402 with the upgrade path and nothing created. Tagging within caps is never gated behind NDA, tracker or messaging.

## Acceptance criteria and tests

AC-SUB-1 (`integration/billing/test_caps.py::test_fourth_proposal_402`), AC-PROP-2 (`::test_sixth_tag_402`).

## Prototype P4 (2026-09-29): tags per proposal built

- `entitlements.check_room(settings, ent, key, *, used, adding)`: 402 when `adding` more items would pass the cap, with
  the `check_count` body (`used` as it is, the upgrade path); `check_count` is `check_room` with one item.
- The Pitch (`bridge/proposals/tags.py`) asks for room for the whole batch under the per-developer lock, so a batch past
  `tags_per_proposal` creates nothing. A tag counts unless it was withdrawn or released before it reached the
  organisation. Tagging within the cap needs nothing else (no NDA, tracker or messaging gate, AC-SUB-5).
- Tests: `unit/billing/test_room.py`, `integration/billing/test_caps.py::test_sixth_tag_402` (AC-PROP-2),
  `::test_a_batch_past_the_cap_creates_nothing`, `::test_tags_never_paywalled` (AC-SUB-5, Phase 3 in the register,
  asserted early).
