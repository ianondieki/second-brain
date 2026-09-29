# REQ-REM-02

- Task: T3.9 (`docs/platform/PLAN.md` Phase 3); prototype track P6 (`PLAN.md` §8)
- Agent: impl-backend
- Files owned: `bridge/reminders/org_digest.py`, `bridge/reminders/templates/em7_org.html.j2`,
  `backend/tests/unit/reminders/test_org_digest.py`
- Depends on: REQ-REM-01 (health rules and the dispatcher), REQ-BIL-01 (`progress_digest` per plan).

## Scope

Enterprise progress digest (org version of EM7, `reminders.org_digest`, from 08:30 EAT, daily or weekly per the
organisation's plan): for each organisation member who opted in (the `reminders` consent), per engagement On track / At
risk / Off track with the code-computed reason, milestones due, what awaits the organisation, new tagged proposals in
the period, overdue items, and "No update from {developer} since {date}" when the developer has been quiet. Rendered by
code from fact tuples only: no LLM. Developer-authored text (proposal titles, milestone deliverables) appears only
quoted, attributed and defanged; no link leaves the platform.

## Acceptance criteria and tests

AC-REM-2 (`unit/reminders/test_org_digest.py`), AC-REM-3 (`integration/reminders/test_health_agreement.py`), the
AC-MAIL-5 checks on this digest (escaped, defanged, platform links only) in `unit/reminders/test_org_digest.py`.
