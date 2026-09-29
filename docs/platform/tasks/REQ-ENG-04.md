# REQ-ENG-04

- Task: P10 Scout agent, stage 0 (`docs/platform/PLAN.md` §8; `docs/platform/prototype-m2-plan.md` §1 P10, §3, M2
  walkthrough step 1). Stage-0 transitions (`accept_interest` with step-up, `decline_interest`) and EM2 from stage 0
  were built in P5 (`tasks/REQ-ENG-02.md`); this card adds how an organisation enters stage 0 and the developer's
  manual Tier-2 share.
- Agent: impl-backend (xhigh). Reviews: security-reviewer (`bridge/engagements/`), reviewer.
- Branch `feat/REQ-SCOUT-02-scouts` (with REQ-SCOUT-01..03; `tasks/REQ-SCOUT-02.md`).
- Files owned: `bridge/engagements/interest.py`, `bridge/engagements/interest_router.py`, `bridge/notifications/n17.py`,
  `bridge/notifications/templates/n17.*.j2`, `InterestBody` and `Tier2ShareOut` in `bridge/engagements/schemas.py`, the
  N17 part of `bridge/engagements/notify.py`, `tests/integration/engagements/test_stage0.py`, `test_share_tier2.py`,
  `tests/integration/matching/test_stage0_from_digest.py`, `tests/unit/notifications/test_n17.py`.
- Depends on: revision 0003 (the `ORG_INTEREST` INSERT policy for a signatory of an E2 organisation, the genesis event,
  `engagements_members`), revision 0005 (`agent_matches`), P5 (the state machine's stage 0, `notify`, EM2), P3
  (`disclosure_grants`, `can_view_tier2`).

## Scope (docs/spec/06 6.9 stage 0; REQUIREMENTS.md §5 N17)

**Express interest: `POST /api/orgs/{org_id}/interest`** with `{proposal_id, origin (org_agent_match | org_browse),
match_id?, contact_user_id, channel, contact_by}` (201, the engagement as the signatory now sees it). Refusals in
order: a non-member 404 (the organisation dependency); not a signatory 403 `role_required` (a reviewer, an owner or an
admin without the signatory role; AC-TRACK-8); no second factor within 12 h 403 `step_up_required` (ADR-002); the
organisation not E2 403 `org_not_e2` (AC-SCOUT-8: until E2), suspended or delisted 403 `org_unavailable`;
`org_agent_match` without `match_id` 422 `match_required`, `org_browse` with one 422 `unexpected_match`; a match that is
not the organisation's or not of that proposal 404; a proposal that is not published and clear 404; the developer a
member of the organisation 409 `own_organisation`; an engagement for the pair 409 `engagement_exists`; a contact-by date
outside today to 5 BD 422 `invalid_contact_by`; a contact who is not an active member 422 `invalid_contact`. Then one
transaction: the engagement (`ORG_INTEREST`, the current registered version, the named contact, the stage's 5 BD
deadline) whose genesis event names the signatory, its N17 notification job, an `org_interest` signal and the
`engagement.interest_expressed` audit event. The database's revision 0003 policy (signatory of an E2 organisation,
current version of a published, clear proposal) and `engagements_members` are the backstop.

**N17.** The genesis of an `ORG_INTEREST` engagement by an organisation member is told to the developer: in-app
("{org} is interested in "{title}". Accept or decline on your tracker.") and by a fixed-template email (who, which
proposal, found by the scout or by browsing, the date to answer by, "not a contract or a commitment to buy", the full
proposal stays private unless they share it), mutable (the `n17` email preference, default on), once per engagement
(`n17:<engagement>`). Accepting then sends EM2 exactly once (P5), whose Tier-2 sentence follows the grants.

**Share Tier 2: `POST /api/engagements/{id}/share-tier2`** (and `GET` for both parties). The engagement's developer
only (403 `not_your_action`; a non-party 404), with a fresh second factor (403 `step_up_required`), on an
organisation-origin engagement (409 `share_not_applicable` for a tagged one: its disclosure policy applies) that has not
ended (409 `engagement_ended`), for a published, clear proposal of theirs. Idempotent: a live grant is returned as it
is; an organisation's pending request is activated (keeping its source); else an active tier-2 grant with source
`org_interest`, `counts_as_unlock` true unless the developer tagged the organisation, `billing_month` the Nairobi month
(REQ-BIL-03 counts it later). Audited (`tier2.grant_created` / `tier2.grant_activated` with the engagement); the
organisation's people on the engagement (the signatory who expressed interest and the named contact) are told in-app.
The grant opens nothing on its own: `can_view_tier2` still needs every other condition, the Evaluation NDA included.

## Acceptance criteria and tests

- AC-TRACK-8/a: `integration/engagements/test_stage0.py::test_a_signatory_expresses_interest_from_a_scout_match_and_the_developer_accepts`
  (scout match; reviewer and owner 403; N17 in-app and email; accept with step-up; the developer's endorsement of stage
  0; EM2 exactly once; the signal and audit event), `::test_the_same_flow_from_a_browse_teaser` (origin `org_browse`,
  decline: no EM2), `::test_refusals`, `::test_an_e1_organisation_gets_403_until_e2` (AC-SCOUT-8),
  `::test_the_developer_may_not_be_a_member`.
- AC-TRACK-8/b: `integration/matching/test_stage0_from_digest.py::test_stage_0_from_a_real_digest` (from the EM3 link).
- The share: `integration/engagements/test_share_tier2.py` (grant, idempotence, `app_tier2_granted` opens only after
  it, the in-app notice, EM2's sentence; developer only; step-up; tagged and ended engagements; an organisation's
  request activated).
- N17: `unit/notifications/test_n17.py`, `unit/engagements/test_notify.py::test_an_organisations_interest_tells_the_developer_n17`.

Mutation proofs E1-E11: `tasks/REQ-SCOUT-02.md`.

## Follow-ups

1. The named contact's role in the stage-0 events stays `member` (P5's rule: the developer cannot read the roster);
   EM2 says "Member".
2. Stage 0's expiry (`EXPIRED`, `NO_DEV_RESPONSE` at 5 BD) and the org's status email on the developer's answer come
   with the side states after the prototype (REQUIREMENTS.md §7).
3. Revoking a manual grant (the owner) comes after the prototype, as for P3's grants.
