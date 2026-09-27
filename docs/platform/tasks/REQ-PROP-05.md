# REQ-PROP-05

- Task: T2.9 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-ai (backend), impl-frontend (opt-in dialog, F2)
- Files owned: `bridge/proposals/assistant.py`
- Depends on: T2.2, T2.3.

## Scope

The submission assistant (Sonnet 5 through `LLMClient`, fake/cassette in CI) suggests Tier-1 vs Tier-2 placement of the developer's own text. It runs only after an explicit per-use opt-in recorded as a `consents` row `tier2_llm_assistant` bound to the session (expires with it); it never auto-publishes or edits; output is labelled "AI-drafted".

## Acceptance criteria and tests

AC-SEC-6 (`unit/llm/test_no_tier2_in_llm_calls.py`, `unit/proposals/test_assistant_consent.py`).
