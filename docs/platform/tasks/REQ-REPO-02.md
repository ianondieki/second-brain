# REQ-REPO-02

- Task: T2.8 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (search), test-writer (Schemathesis); impl-frontend (Browse screen, F3)
- Files owned: `bridge/proposals/search.py`, search routes in `bridge/proposals/router.py`, `backend/tests/contract/`, `frontend/app/(app)/org/browse/`
- Depends on: T2.3 (published teasers exist).

## Scope

Browse repo on every org plan: Tier-1 keyword search (`proposals.search_tsv`, `simple` config) plus filters niche (incl. children of a parent niche), county, maturity, ask and linked Problem; cursor pagination; only `published`, not hidden, moderation `clear` teasers; the response model is the Tier-1 teaser schema only (no Tier-2 field, no embedding, no tag or grant data). Schemathesis contract tests over every list/search endpoint assert that no Tier-2 key and no vector ever appears.

## Acceptance criteria and tests

AC-REPO-5 (`integration/proposals/test_search.py`), AC-REPO-3 (`contract/test_search_schemathesis.py` plus the explicit test).

## Prototype P4 (T2.8 minimal, 2026-09-29): built

- `GET /api/proposals` (every signed-in user; Browse repo is on every org plan): `q` (1–200 chars, no NUL) through
  `websearch_to_tsquery('simple', q)` against `proposals.search_tsv` (title weight A, problem statement and summary
  B, impact claims C); filters `niche` (slugs, a parent includes its children), `county`, `maturity`, `ask` (each
  repeatable, at most 50 values: 422 `too_many_filter_values`) and `problem` (a Problem linked to the current version);
  only `status = 'published'` and `moderation_state = 'clear'`; ordered by `ts_rank` (float8) then newest first, keyset
  cursor over (rank, published_at, id) (400 `invalid_cursor` for anything this module did not write); `limit` 1–50.
- Items are `serializers.TeaserItem` (REQ-REPO-03): id, owner handle, cert id, version number, published_at and the
  Tier-1 teaser from the allow-list `TIER1_COLUMNS` of the registered version. No Tier-2 field, embedding, search
  vector, tag or grant data.
- Routes live in `bridge/proposals/pitch_router.py` and the service in `bridge/proposals/search.py` (not in `router.py`,
  to keep P3's concurrent edits of `router.py` conflict-free).
- Tests: `integration/proposals/test_search.py` (AC-REPO-5: keywords, every filter, drafts/held/hidden never found,
  relevance, paging; the explicit AC-REPO-3 test `test_results_are_tier1_only`; forged cursors; 422s and 401).

After prototype: the Schemathesis contract suite (`backend/tests/contract/`; schemathesis is not a dependency yet, a
new dev dependency needs the orchestrator), the Browse screen (F3), prefix matching (the `simple` query matches whole
words only).
