# REQ-REM-01

- Task: T3.9 (`docs/platform/PLAN.md` Phase 3); prototype track P6 (`PLAN.md` §8)
- Agent: impl-backend
- Files owned: `bridge/reminders/{health,facts,nudge,wording,render,dispatch,__main__}.py`,
  `bridge/reminders/templates/em7_*.j2`, `bridge/jobs/reminders.py`, the `reminder_nudge` task in `backend/ai/models.yaml`,
  `backend/tests/unit/reminders/`, `backend/tests/integration/reminders/`
- Depends on: REQ-REM-00 (T1.8), REQ-NOT-01 (T1.7), REQ-LLM-01 (T2.2 and P7), schema v3 (P1). Parallel with P5
  (`feat/REQ-ENG-02-tracker`): reads the tracker's rows only, never P5's code.

## Scope

Developer daily reminder EM7/N23 (`docs/spec/06` 6.10, 6.11; `REQUIREMENTS.md` §5 N23): `reminders.dispatch` every 15
minutes, sent at most once per user and Nairobi day, from `send_after` 07:30 EAT, on the shared clock
(`app_clock_now()`, so the test clock drives it). Health is computed by code only (`at_risk`: an item due within 2 BD
with no action, a milestone overdue, a stage past its deadline while a party is awaited, the repo-cold rule only with a
linked repo, never on a weekend; `off_track`: anything overdue more than 7 days or a rework loop of 2 or more), against
the signed agreement's milestones. Sections: Needs you, Waiting on the other party, Health with one-line reasons, drafts
not published, one featured next step. The LLM (task `reminder_nudge`) rewords the headline and the next step from
code-computed fact tuples only; a demo fallback, a failed call, a refused call or a reply that adds a fact answers with
fixed fallback text, marked. In-app always; email with the `reminders` consent, the `em7`/email preference not switched
off, a verified address and no suppression. Trending line: off until Phase 5.

## Acceptance criteria and tests

AC-REM-1 and AC-REM-4/b (`unit/reminders/test_health_rules.py`, frozen Africa/Nairobi dates), AC-REM-3
(`integration/reminders/test_health_agreement.py`), AC-MAIL-3 with REQ-NOT-06
(`integration/notifications/test_daily_uniqueness.py`), the dispatcher (`integration/reminders/test_dispatch.py`), the
wording and its fallback (`unit/reminders/test_wording.py`), the email (`unit/reminders/test_nudge.py`), the jobs and
CLI (`unit/reminders/test_jobs_and_cli.py`).
