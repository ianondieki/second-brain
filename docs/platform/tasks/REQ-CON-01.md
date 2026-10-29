# REQ-CON-01

- Task: T1.4, T1.5 (`docs/platform/PLAN.md` Phase 1)
- Agent: orchestrator (B)
- Files owned: `bridge/profiles/consents.py`, `backend/config/consents.yaml`
- Depends on: T1.4.

## Scope

Consents with versioned text (`backend/config/consents.yaml`, text hash recorded) and separate purposes: marketing, reminders, whatsapp, profiling, github_import, tier2_llm_assistant, tier2_llm_moderation. Append-only history; current state = latest row per purpose.

## Acceptance criteria and tests

Unit: `backend/tests/unit/test_consents.py`. AC-SEC-6 closes in Phase 2 (LLM layer).

## Notes

Consent wording is `[[COPY-REVIEW]]` draft text for G2 review.
