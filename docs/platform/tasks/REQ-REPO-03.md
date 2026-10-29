# REQ-REPO-03

- Task: T2.7 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend
- Files owned: `bridge/proposals/serializers.py`, `bridge/proposals/tags.py` (with REQ-PROP-03)
- Depends on: T2.3, T2.6.

## Scope

Tag privacy: tagged org names or ids never appear in a Tier-1 GET, search results, another org's inbox, scout inputs (Phase 4) or trending badges (Phase 5). Teaser serializers take an allow-list of Tier-1 fields; tags are readable only by the owner and, for `delivered` tags, by that org.

## Acceptance criteria and tests

AC-REPO-6/a (`integration/proposals/test_tag_privacy.py`): a proposal tagged to Safaricom, Airtel and Telkom; a Tier-1 GET, search and another org's inbox contain none of their names or ids. AC-REPO-6/b is Phase 5.

## Prototype P4 (2026-09-29): built

- `bridge/proposals/serializers.py`: `TeaserItem` and `teaser_items()` build list items (Browse repo, the Inbox) from
  the allow-list `TIER1_COLUMNS` of the current registered version plus the owner handle and cert id; published and
  clear proposals only. The Tier-1 GET (`/api/proposals/{id}`, P2) carries no tag data either.
- Tags are read only as the developer's own (`bridge/proposals/tags.py`) or, for the Inbox, as the organisation's own
  delivered tags (RLS: members see `status = 'delivered'` rows of their organisation; `app.org_id` narrows to the one
  in the path). An E1 organisation sees only `app_held_tag_count`.
- Tests: `integration/proposals/test_tag_privacy.py` (AC-REPO-6/a: a Tier-1 GET by another organisation and by another
  developer, search, another organisation's Inbox, and a tagged organisation's own Inbox name none of the tagged
  organisations, their slugs, ids or the other engagements; RLS shows each member only their own delivered tag;
  `test_the_inbox_is_members_only`), and `integration/directory/test_held_tags.py` (an E1 Inbox holds the count only).

AC-REPO-6/b (trending badges) stays Phase 5.
