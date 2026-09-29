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

## Prototype P6 (2026-09-29): built

- `deliveries.daily_key(kind, channel, user_id, local_date, *, org_id=None)` → `kind:channel:user[:org]:YYYY-MM-DD`
  (kind a code without ":"); the unique `dedupe_key` then allows one row per tuple.
- `send_email(..., attempt_limit=3)`: at most `attempt_limit` attempts per row across calls; a row whose attempts are
  spent on transient errors ends `failed` (`email.dead_letter`), a queued row already at its limit ends there without a
  send, a permanent error is final at once. The dispatcher makes one attempt per run (`max_attempts=1`), so the
  15-minute runs space the three attempts. Without a limit, REQ-NOT-01 behaviour is unchanged.
- `bridge/notifications/in_app.py` `post_in_app` (ledger row `in_app`/`sent` + notification, once per key, platform
  links only, title 1-200 characters); `bridge/notifications/preferences.py` `channel_enabled` (no row = on).

Tests: `unit/notifications/test_daily.py`, `integration/notifications/test_daily_uniqueness.py` (one row and email per
user, day and channel, also racing; three attempts across runs; permanent failure final; the database refuses a second
row for the key; in-app once; preferences), plus the dispatcher's runs in `integration/reminders/test_dispatch.py`.

**Open.** (1) Uniqueness rests on `daily_key` being the only way EM7 rows are keyed; a partial unique index on
`notification_deliveries (user_id, org_id, kind, local_date, channel) WHERE local_date IS NOT NULL` (NULLS NOT
DISTINCT) would enforce the tuple in the database as well: optional, for db-migrations. (2) The at-least-once window of
REQ-NOT-01 stays: if the COMMIT fails after a successful send, the next run sends again (bounded by the three
attempts only if each attempt is committed before the provider call; not built).
