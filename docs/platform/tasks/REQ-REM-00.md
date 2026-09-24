# REQ-REM-00

- Task: T1.8 (`docs/platform/PLAN.md` Phase 1)
- Agent: impl-backend, test-writer
- Files owned: `bridge/reminders/`, `bridge/engagements/calendar.py`, `scripts/gen_reminder_parity_fixtures.py`, `backend/tests/fixtures/reminder_parity/`
- Depends on: T1.3.

## Scope

Port `classify`, `pick_featured`, `fallback_text`, `_record` + `MAX_ATTEMPTS`, `compose_email`, `template_notices` into `bridge/reminders/{policy,compose}.py` with parity tests against fixtures generated from `reminder/` (the backend never imports `reminder/`); Kenyan business-day helper over the `holidays` table.

## Acceptance criteria and tests

AC-REM-4/a (legacy suite unchanged and green); parity: `backend/tests/unit/reminders/test_parity.py`; `backend/tests/unit/engagements/test_business_days.py`.
