# REQ-REPO-03

- Task: T2.7 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend
- Files owned: `bridge/proposals/serializers.py`, `bridge/proposals/tags.py` (with REQ-PROP-03)
- Depends on: T2.3, T2.6.

## Scope

Tag privacy: tagged org names or ids never appear in a Tier-1 GET, search results, another org's inbox, scout inputs (Phase 4) or trending badges (Phase 5). Teaser serializers take an allow-list of Tier-1 fields; tags are readable only by the owner and, for `delivered` tags, by that org.

## Acceptance criteria and tests

AC-REPO-6/a (`integration/proposals/test_tag_privacy.py`): a proposal tagged to Safaricom, Airtel and Telkom; a Tier-1 GET, search and another org's inbox contain none of their names or ids. AC-REPO-6/b is Phase 5.
