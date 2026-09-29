# REQ-NOT-06

- Task: T3.4 (`docs/platform/PLAN.md` Phase 3); prototype track P6 (`PLAN.md` §8)
- Agent: impl-backend
- Files owned: `bridge/notifications/deliveries.py` (daily keys and the attempt budget), `bridge/notifications/in_app.py`,
  `bridge/notifications/preferences.py`, `backend/tests/unit/notifications/test_daily.py`,
  `backend/tests/integration/notifications/test_daily_uniqueness.py`
- Depends on: REQ-NOT-01.

## Scope

At most one EM7 per user, kind, Nairobi date and channel (`notification_deliveries(user_id, kind, local_date,
channel)`): the dedupe key of a daily message is built from exactly that tuple (`daily_key`) and is unique in the
table. Retries at most 3 per message across runs, with the transient/permanent classification of REQ-NOT-01; a
permanent failure ends the row `failed` at once and a message whose 3 attempts are spent ends `failed` (dead letter),
never resent. In-app notifications written once per dedupe key with their ledger row; email preferences read from
`notification_preferences` (no row = on).

## Acceptance criteria and tests

AC-MAIL-3 (`integration/notifications/test_daily_uniqueness.py`; unit: `unit/notifications/test_daily.py`).
