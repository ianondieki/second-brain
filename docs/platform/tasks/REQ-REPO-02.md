# REQ-REPO-02

- Task: T2.8 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (search), test-writer (Schemathesis); impl-frontend (Browse screen, F3)
- Files owned: `bridge/proposals/search.py`, search routes in `bridge/proposals/router.py`, `backend/tests/contract/`, `frontend/app/(app)/org/browse/`
- Depends on: T2.3 (published teasers exist).

## Scope

Browse repo on every org plan: Tier-1 keyword search (`proposals.search_tsv`, `simple` config) plus filters niche (incl. children of a parent niche), county, maturity, ask and linked Problem; cursor pagination; only `published`, not hidden, moderation `clear` teasers; the response model is the Tier-1 teaser schema only (no Tier-2 field, no embedding, no tag or grant data). Schemathesis contract tests over every list/search endpoint assert that no Tier-2 key and no vector ever appears.

## Acceptance criteria and tests

AC-REPO-5 (`integration/proposals/test_search.py`), AC-REPO-3 (`contract/test_search_schemathesis.py` plus the explicit test).
