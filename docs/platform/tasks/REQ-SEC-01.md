# REQ-SEC-01

- Task: T2.5 (Tier-2 flag); the deals flag lands in Phase 3 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend
- Files owned: `bridge/config.py`, `bridge/proposals/access.py`
- Depends on: T2.5.

## Scope

`FEATURE_TIER2_ENABLED` (default false; production stays false until G2) gates every Tier-2 endpoint (reads, renders, attachments, NDA acceptance, grant requests and policy changes that release Tier 2): 403 `tier2_disabled` regardless of NDA state. The test enumerates Tier-2 routes from the OpenAPI document (tag `tier2`), so a new route cannot escape.

## Acceptance criteria and tests

AC-SEC-2 (`integration/test_feature_flags.py::test_tier2_flag`). AC-SEC-7 is Phase 3.

## Prototype P3 (T2.5 minimal, 2026-09-29): built

- `bridge/proposals/access.py::tier2_gate` is the router dependency of `tier2_router` (`bridge/proposals/router.py`),
  so every route added to that router is gated; `router.include_router(tier2_router)` is the router module's last
  line. Order: tenancy first, then the flag. A signed-in caller who is not an active member of the path's organisation
  gets 404 (`not_found`), as on every organisation route (AC-SEC-1: `integration/test_auth_security.py`
  sweeps every `{org_id}` path and expects 404 from non-members); everyone else gets 403 `tier2_disabled` while
  `FEATURE_TIER2_ENABLED` is off, members whatever their NDA state and anonymous callers alike. The gate runs before
  the other path parameters are validated. Both refusals write `tier2.access_denied` (condition `not_member` or
  `tier2_disabled`) when a user is signed in. `can_view_tier2` checks the flag again as its first condition.
- Routes tagged `tier2`: `GET|POST /api/orgs/{org_id}/proposals/{proposal_id}/nda`,
  `GET /api/orgs/{org_id}/proposals/{proposal_id}/tier2`, `GET /api/me/proposals/{proposal_id}/tier2` (the owner's
  preview render). Not gated: the owner's JSON reads of their own Tier 2 (REQ-PROV-01 card, human decision) and
  `GET /api/me/proposals/{id}/views` ("Who has seen this" releases no Tier 2; the owner keeps their access log).
- Tests: `integration/test_feature_flags.py::test_tier2_flag` (AC-SEC-2: the routes come from the OpenAPI document by
  tag; a viewer meeting every condition with the NDA accepted, the owner and anonymous callers get 403
  `tier2_disabled`, signed-in non-members 404 on organisation paths; nothing but the refusals is written),
  `integration/proposals/test_access.py::test_predicate_negatives[feature_disabled]`,
  `unit/proposals/test_access_rules.py`.

Deviation for the orchestrator: AC-SEC-2 reads "every Tier-2 endpoint returns 403". On an organisation path a
signed-in non-member gets 404 instead (tenancy before the flag), because AC-SEC-1 and docs/spec/08 require 404 from
every organisation route to a non-member and the existing sweep enforces it. Both deny; neither reveals anything. If
the flag must win everywhere, the organisation routes move off `/api/orgs/{org_id}` (for example an `org_id` query
parameter) instead.

## After prototype (rescheduled, not removed)

- `FEATURE_DEALS_ENABLED` and AC-SEC-7 (Phase 3, `bridge/engagements/guards.py`).
- The gate on the routes that do not exist yet: attachment downloads, the PDF render, raw download, grant requests and
  policy changes that release Tier 2 (each goes on `tier2_router`).
- REQ-LEG-01 (Phase 8): the flag stays false in production until G2; re-run AC-SEC-2 then.
