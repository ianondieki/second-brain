# REQ-BD-01

- Task: P5 (business-day deadlines). Agent: impl-backend. Calendar module: `bridge/engagements/calendar.py` (Phase 2
  groundwork).

## Scope built in the prototype

Every tracker deadline comes from `backend/config/policy.yaml` in Kenyan business days, counted by
`calendar.add_business_days` over the `holidays` table (observed dates) from the Nairobi date of `app_clock_now()`,
and falls at 23:59:59 EAT of the due day (`state_machine.stage_deadline`); the detail view shows the business days
left (`state_machine.due`). The policy file is validated fail-closed (`bridge/engagements/policy.py`).

## Tests

`tests/unit/engagements/test_business_days.py`, `test_state_machine.py` (weekend, holiday, Saturday entry, UTC/EAT
day boundary), `test_policy.py`; `tests/integration/test_testclock_excluded.py::test_deadlines_skip_weekends_and_gazetted_holidays`.

## After the prototype

The admin screen for holidays (`bridge/admin/holidays.py`), AC-REM-4/b with the reminders (P6).
