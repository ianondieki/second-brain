# REQ-PROP-03

- Task: T2.7 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (API), impl-integrations (EM1), impl-frontend (picker, F2)
- Files owned: `bridge/proposals/tags.py`, tag routes, `frontend/app/(app)/dev/ideas/[id]/pitch/`
- Depends on: T2.3, T2.6 (directory, E0/E1/E2), T2.10a (D1: `require_d1` / `D1Developer`).

## Scope

"Pitch to company": a directory picker grouped by niche showing E0/E1/E2; multi-tag within the plan cap (`tags_per_proposal`); E2 → `delivered` tag (the `SUBMITTED` engagement is derived in Phase 3, AC-PROP-1/b); E0 → `held_unclaimed` with the spec sentence and zero emails; E1 → `held_pending_verification` (the org sees only a count). One open engagement or held tag per (developer, org): 409 with the reason and nothing created; 30-day cooldown after a decline (engagement fixture). EM1 lists sent and saved groups. Tagging within caps is never gated behind NDA, tracker or messaging (AC-SUB-5 is Phase 3). Tagging requires D1 (docs/spec/06 6.4 item 8, AC-IP-5): the tag route takes `profile: D1Developer` (`bridge.profiles.verification`), so a D0 developer, or an account without a developer profile, gets 403 `d1_required` and nothing is created.

## Acceptance criteria and tests

AC-PROP-1/a (`integration/proposals/test_tags.py::test_mixed_tags`), AC-PROP-2 (`integration/billing/test_caps.py::test_sixth_tag_402`), AC-PROP-7 (`integration/proposals/test_tags.py::test_duplicate_org_409`), AC-DIR-1 (`integration/directory/test_held_tags.py`), AC-IP-5 on the real tag route (`integration/proposals/test_tags.py::test_tag_requires_d1`: 403 `d1_required` below D1, nothing created; allowed after D1).

## Prototype P4 (T2.7 minimal, 2026-09-29): built

API only (the picker screen is P8). Branch `feat/REQ-PROP-03-pitch`.

- Routes (signed in; a proposal that is not the caller's answers 404):
  - `GET /api/me/proposals/{id}/pitch/orgs`: the picker. The directory grouped by niche exactly as the Companies page
    reads it (`directory.service.list_directory`: org type, county, niche and keyword filters, the same cursor), each
    organisation with its card (E0/E1/E2 badge), the `outcome` a tag would have (`delivered`, `held_pending_verification`,
    `held_unclaimed`), `available`, a `reason` code and a message (why not, or why a tag would be held), plus the plan
    cap (`used`, `limit`, `plan`) and `proposal_public`.
  - `GET /api/me/proposals/{id}/tags`: the proposal's tags (status, open, organisation card or null once unlisted,
    engagement id, the held sentence) and the cap.
  - `POST /api/me/proposals/{id}/tags` `{"org_ids": [...]}` (1–20, repeats ignored): the Pitch. `D1Developer` (403
    `d1_required`, AC-IP-5). One transaction or nothing: the proposal published and clear (409
    `proposal_not_public`); every organisation listed (404 with `org_ids`); no conflict (409 `tag_conflict`, message
    of the first and `conflicts: [{org_id, reason, message}]` in request order; reasons `own_organisation`, `tagged`,
    `open_elsewhere`, `already_pitched`, `cooldown`, `unavailable`); room for the whole batch in `tags_per_proposal`
    (402, REQ-BIL-02). Then per organisation: E2 → `delivered` + `TagHooks.open_engagement` + `TagHooks.grant_on_tag`;
    E1 → `held_pending_verification`; E0 → `held_unclaimed` (held tags reach nobody: no engagement, grant, email,
    in-app row or invitation). One `proposal.pitched` audit event (tag ids, counts, engagement ids). When at least one
    tag was delivered: the developer's in-app row (`pitch_sent`) and EM1 after the response (REQ-NOT-02). 201 with the
    created tags, `sent_count`, `saved_count`, `email_sent` and the cap.
  - `POST /api/me/proposals/{id}/tags/{tag_id}/withdraw`: withdraw an open held tag (409 `tag_closed`, 409
    `tag_delivered`: a delivered one is withdrawn on the tracker, P5).
  - `GET /api/orgs/{org_id}/inbox` (`OrgMember`; non-members 404): the organisation's delivered tags newest first as
    Tier-1 teasers (`serializers.TeaserItem`) with the engagement (id, state, deadline) or null, a keyset cursor,
    `held_count` (`app_held_tag_count`: all an E1 organisation sees) and `verification` for the empty state. A proposal
    hidden or held after it was pitched drops out.
- Conflicts (`tags.conflicts`, shared by the picker and the Pitch): a membership of the organisation (revision 0003
  refuses the engagement anyway); an open tag or open engagement of the developer with it (`tagged` for this proposal,
  else `open_elsewhere`: AC-PROP-7, also `uq_tags_open_developer_org`); an engagement of this proposal with it
  (`already_pitched`: one engagement per proposal and organisation); a DECLINED engagement that ended less than 30 days
  ago on the shared clock `app_clock_now()` (`cooldown`); a suspended E2 organisation (`unavailable`).
- Cap: a tag counts unless it was withdrawn or released before it reached the organisation (open, or delivered or
  expired, or with an engagement). A per-developer advisory lock (`tags:<developer>`) serialises one developer's
  Pitches and withdrawals, so the cap and conflict checks cannot both pass for two concurrent requests; an
  IntegrityError at the unique index is a 409 backstop.
- Seams for the parallel tasks (`bridge/proposals/tag_hooks.py`, installed on `app.state.tag_hooks`, default
  `default_hooks()`): both called in the developer's transaction, tenant bound, right after the delivered tag row is
  inserted, first the engagement then the grant; neither commits; an exception rolls the Pitch back.
  - P5 plugs `open_engagement_for_tag` into `default_hooks()` as `open_engagement(db, *, developer_id, proposal_id,
    version_id, org_id, tag_id) -> UUID` (the engagement id) and deletes `interim_open_engagement` (today: a plain
    INSERT of the `SUBMITTED`/`tagged` row, genesis by the database, no deadline). P5's function on
    `feat/REQ-ENG-02-tracker` is `commands.open_engagement_for_tag(db, tag_id) -> Engagement` raising `OpenRefused`,
    so the plug is a small adapter in `tag_hooks.py`:
    `async def open_engagement(db, *, developer_id, proposal_id, version_id, org_id, tag_id): try: return (await
    commands.open_engagement_for_tag(db, tag_id)).id` / `except commands.OpenRefused as exc: raise ApiError(409,
    "tag_conflict", exc.message) from exc` (the Pitch's own checks make `engagement_exists` a lost race only).
  - P3 plugs `bridge.proposals.grants.grant_on_tag` (same signature: `(db, *, owner_id, proposal_id, org_id) -> UUID |
    None`) into `default_hooks()` and deletes `grant_nothing_until_p3` (today: no grant, fail closed).
- Tests: `integration/proposals/test_tags.py` (`test_mixed_tags` AC-PROP-1/a with the EM1 clause,
  `test_a_second_pitch_sends_its_own_em1`, `test_duplicate_org_409` AC-PROP-7, `test_tag_requires_d1` AC-IP-5,
  `test_what_cannot_be_pitched`, `test_a_held_tag_can_be_withdrawn_and_a_delivered_one_cannot`,
  `test_a_failing_hook_rolls_the_pitch_back`, `test_a_decline_holds_the_organisation_back_for_30_days`,
  `test_concurrent_pitches_to_one_organisation_create_one_tag`, `test_the_picker_groups_by_niche_with_levels_and_availability`,
  `test_signed_out_callers_get_401`, `test_a_lost_race_at_the_unique_index_answers_409_and_creates_nothing`),
  `integration/proposals/test_inbox.py`, `integration/directory/test_held_tags.py` (AC-DIR-1),
  `integration/directory/test_keyword_search.py` (the picker's directory search), fixtures in
  `integration/proposals/pitch_helpers.py` (registered in `integration/conftest.py`).

Choices the spec leaves open (prototype defaults): a Pitch is a batch refused whole on any conflict, cap or unknown
organisation; EM1 is per Pitch (dedupe key `em1:<proposal>:<first delivered tag>`) and lists that Pitch's groups; the
developer's own organisation and a suspended E2 organisation are refused with a reason; the fixture organisations are
"Safcell", "Airwave", "Telmark" (their rows stay in the session database).

Deviation from the P4 brief (for the orchestrator): the brief sent EM1 "to the org's reviewers/signatory". EM1 is the
developer's receipt in docs/spec/06 6.10 (subject "Your proposal … is registered and sent to N organisations") and
`REQUIREMENTS.md` §5 N01 (developer: email + in-app; organisation: in-app + the EM7 digest line), so EM1 goes to the
developer only. The organisation's side is its Inbox. An in-app row or an email for an organisation's members cannot be
written from the developer's request today (see "Schema needs").

## Schema needs (for db-migrations; nothing was changed)

1. N01's organisation side (REQ-NOT-03): `in_app_notifications` INSERT is `user_id = app_user_id()` and bridge_app,
   acting as the developer, cannot read the organisation's roster or its members' addresses. A SECURITY DEFINER
   function, e.g. `app_notify_tag_delivered(p_tag uuid)`, callable by the tag's developer for their open delivered
   tag once, inserting one row per active member holding reviewer, signatory, admin or owner (title and link only, no
   Tier-2), would give the organisation its in-app line without exposing the roster. Not needed for M1 (the Inbox is
   the organisation's surface); wanted before REQ-NOT-03.
2. Optional, later: an index on `tags (org_id, created_at DESC, id DESC) WHERE status = 'delivered'` for the Inbox
   keyset once an organisation has many tags.

## After prototype (rescheduled, not removed)

- AC-PROP-1/b (P5 and REQ-DIR-03): a held tag delivered on E2 approval gets its `SUBMITTED` engagement (today the
  Inbox shows it with `engagement: null`); `tags.sla_due_at` and the engagement deadline from `policy.yaml` (P5).
- The picker screen (P8, `frontend/app/(app)/dev/ideas/[id]/pitch/`), the Inbox screen, and N01's organisation in-app
  line and digest (REQ-NOT-03, EM7).
- Invitations for E0 organisations (REQ-DIR-04) and delisting's notice to the developer.
- The cooldown length and the batch size (20) as `policy.yaml` values.
