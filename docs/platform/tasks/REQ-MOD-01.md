# REQ-MOD-01

- Task: T2.3 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (queue), impl-ai (pre-screen task), impl-frontend (admin moderation, F4)
- Files owned: `bridge/admin/{moderation,router,deps}.py`, `bridge/proposals/prescreen.py`, `frontend/app/(admin)/moderation/`
- Depends on: T2.1, T2.2.

## Scope

Moderation queue (`moderation_cases`) with a Haiku 4.5 pre-screen on Tier-1 fields only (spam, defamation, false affiliation, third-party personal data, malicious links, `names_real_org_negative`, `security_vulnerability`); the last two and high-confidence spam are held pending review; the pre-screen and the over-disclosure check (warn only) run through `LLMClient` with fakes in tests. Staff console routes sit behind the staff dependency (staff role + enrolled and verified TOTP; 404 for non-staff; Phase 1 follow-up 5). Moderator approve/reject through definer functions; decisions audited.

## Acceptance criteria and tests

The AC-PROP-5 queue clause and AC-PROP-6 (`integration/admin/test_moderation_queue.py`, `integration/proposals/test_holds.py`).
