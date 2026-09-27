# REQ-PROP-02

- Task: T2.3 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend
- Files owned: `bridge/proposals/sanitise.py`, `bridge/admin/moderation.py`, `bridge/admin/router.py` (moderation queue routes)
- Depends on: T2.1, T2.2.

## Scope

The Tier-1 sanitiser rejects (422 with the field and a plain reason) URLs, bare domains, email addresses, phone numbers (E.164, 07xx/01xx, spaced and dotted variants) and till/paybill patterns. A teaser naming a directory org negatively or describing a security vulnerability is held (`moderation_state=held`, a `moderation_cases` row) and returned by no public, list or search endpoint until a moderator approves it; vulnerability content is never made public. Regex and heuristics decide holds; the Haiku pre-screen (REQ-MOD-01) can add reasons but never releases a hold.

## Acceptance criteria and tests

AC-PROP-6 (`unit/proposals/test_sanitise.py`, `integration/proposals/test_holds.py`).
