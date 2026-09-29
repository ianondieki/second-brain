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

## Prototype P6 (2026-09-29): built

- `bridge/reminders/org_digest.py` (no LLM import; a test checks): `compose_digest(OrgFacts)` per active engagement:
  stage, health with the same `assess` as the developer's reminder and its reasons from the organisation's side,
  open milestones due within 14 days not already named by a reason, "No update from {developer} since {date}" after
  5 quiet days (the developer's latest event, non-automatic endorsement or signature; the engagement's start if none),
  never a percentage. Sections: Needs us (the organisation's action, or each submitted milestone to review), New tagged
  proposals (tagged, `SUBMITTED`, created within the period), Overdue (every overdue reason), Engagements (worst
  first). Kind `em7_org`; subject "{org}: progress digest, {date}" or "…weekly progress digest, week of {Monday}".
- Dispatch (`run_org_digests`, from 08:30 EAT): each active member who holds the `reminders` consent, per organisation
  (bound to the member and the organisation), cadence from the organisation's plan (`progress_digest`: `daily`, else
  weekly = one per ISO week dated its Monday), keys `daily_key("em7_org", channel, user, period, org_id=org)`; in-app
  always for them, email with a verified address and the `em7_org`/email preference on. Removed members and quiet
  organisations get nothing.

Tests: `unit/reminders/test_org_digest.py` (AC-REM-2; the full text is the fixed layout filled with the facts; AC-MAIL-5
on this digest: a bare domain, an email and a Kenyan phone number are never auto-linkable; health agreement),
`integration/reminders/test_org_dispatch.py`, `integration/reminders/test_health_agreement.py` (AC-REM-3).

**Open.** N23 says "org members opted in to the progress digest"; no separate digest opt-in exists, so the prototype
uses the `reminders` consent ("Send me reminders about my proposals and engagements by email") as the opt-in, for
every role. A dedicated opt-in (a consent purpose or a default-off preference) is a product decision.

**Review round 1 (2026-09-29).** Developer text in the digest is defanged with the Tier-1 sanitiser's own phone
patterns (`proposals.sanitise.PHONES`), which now include Kenyan landlines (020 2345678, 0203 123456,
(020) 234-5678); the AC-MAIL-5 fixture carries a landline (`unit/reminders/test_org_digest.py`), and the P2 sanitiser
tests gained landline and date-and-time cases (`unit/proposals/test_sanitise.py`).
