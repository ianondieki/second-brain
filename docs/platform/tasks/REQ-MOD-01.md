# REQ-MOD-01

- Task: T2.3 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (queue), impl-ai (pre-screen task), impl-frontend (admin moderation, F4)
- Files owned: `bridge/admin/{moderation,router,deps}.py`, `bridge/proposals/prescreen.py`, `frontend/app/(admin)/moderation/`
- Depends on: T2.1, T2.2.

## Scope

Moderation queue (`moderation_cases`) with a Haiku 4.5 pre-screen on Tier-1 fields only (spam, defamation, false affiliation, third-party personal data, malicious links, `names_real_org_negative`, `security_vulnerability`); the last two and high-confidence spam are held pending review; the pre-screen and the over-disclosure check (warn only) run through `LLMClient` with fakes in tests. Staff console routes sit behind the staff dependency (staff role + enrolled and verified TOTP; 404 for non-staff; Phase 1 follow-up 5). Moderator approve/reject through definer functions; decisions audited.

## Acceptance criteria and tests

The AC-PROP-5 queue clause and AC-PROP-6 (`integration/admin/test_moderation_queue.py`, `integration/proposals/test_holds.py`).

## Prototype P2 (T2.3 minimal, 2026-09-29): built

- The rules pre-screen (`bridge/proposals/prescreen.py`: `PreScreen` interface, `RulesPreScreen`, `merge`) on Tier-1
  fields only; T2.2 was not merged, so no LLM call is made: the Haiku screen plugs in behind `PreScreen` later and can
  only add reasons. Rule holds and developer problems are filed through `app_open_moderation_case` with source `regex`
  (one unresolved case per subject and source; reasons merge), classifier output holds labels and field names only.
  A new version of a held or rejected proposal is filed again (`new_version_of_moderated_proposal`) and stays private.
- Staff queue (`bridge/admin/moderation.py`, `bridge/admin/router.py`; staff dependency: 404 non-staff, 403 without
  the moderator role): `GET /api/admin/moderation/cases[?decided=true]` (unresolved cases first in, first out, with a
  Tier-1 preview and the subject's state) and `POST /api/admin/moderation/cases/{case_id}/decision` (`approve` or
  `reject`) through `app_moderate_proposal` / `app_moderate_problem`; the case records `decided_by`/`decided_at`;
  409 `already_decided`; 403 `own_content` for a moderator's own content; audited `moderation.case_decided` on the
  staff chain; approving a held proposal writes its `proposal_published` signal.
- Tests: `integration/admin/test_moderation_queue.py`, `integration/proposals/test_holds.py`,
  `integration/proposals/test_new_problem_flow.py` (the AC-PROP-5 queue clause), `unit/proposals/test_prescreen.py`.

## After prototype (rescheduled, not removed)

- The Haiku 4.5 pre-screen and the over-disclosure warning through `LLMClient` with fakes (T2.2/P7), its classes (spam,
  defamation, false affiliation, third-party personal data, malicious links), high-confidence spam holds.
- The admin moderation screens (F4, P15), reports (report button), assignment and escalation, claims and research
  queues (P15), Tier-2 moderation with the `tier2_llm_moderation` consent.

## Prototype P15-B (2026-09-30): the queue for the screens

The queue items carry what a moderator needs to decide (the Tier-1 text field by field, the flagged fields, the open
decisions and the refusal code otherwise, who decided and when); decided cases are newest first. The demo seeds a
staff moderator and a held proposal. Details and open items: `REQ-ADM-01.md`, "Prototype P15-B".
