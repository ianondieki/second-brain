# REQ-ADM-01

- Task: T2.6b, T2.3 (queue parts only; the full console is Phase 8) (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend, impl-frontend (F4)
- Files owned: `bridge/admin/{deps,router,claims,moderation}.py`, `frontend/app/(admin)/`
- Depends on: T2.1.

## Scope

Phase 2 part: the `/admin` console shell (separate from both portals) with the claim queue (2 BD SLA shown), the moderation queue and the D2 KYC review queue; the staff dependency (staff role + enrolled and verified TOTP; 404 for non-staff; Phase 1 follow-up 5); every decision audited. Impersonation, flags, refunds, research approval and the rest are Phase 8.

## Acceptance criteria and tests

Phase 2 tests: `integration/admin/test_moderation_queue.py`, `integration/directory/test_claims.py`. AC-ADM-3 is Phase 8.

## Notes (T2.6a, staff dependency)

- `bridge/admin/deps.py`: `staff_member(*roles)` (`StaffMember`, `StaffAdmin`, `StaffModerator`). 404 (the API's
  not-found body) when signed out, second factor pending, not staff, or staff without TOTP; 403 for enrolled staff
  lacking the route's role; 403 `step_up_required` when the second factor is older than `STEP_UP_MAX_AGE_HOURS`
  (these are enrolled staff, so the console's existence is not a secret to them).
- Routes so far: `GET /api/admin/me` (any staff; the console shell's access check), `GET /api/admin/niches` (staff
  admin; inactive niches included) and `POST /api/admin/niches` (staff admin; `app_add_niche` decides in SQL: 201,
  409 `niche_slug_taken`, 422 `parent_niche_not_top_level` / `parent_niche_not_found` or a malformed body; the
  database's own staff refusal answers 404 like the dependency; audited `directory.niche_added` as the staff actor,
  subject the niche, payload `parent_id` only). Tests: `integration/admin/test_staff_dependency.py`,
  `integration/admin/test_add_niche.py`, `unit/admin/test_niche_refusals.py`.
- Open: `/api/openapi.json` is served in every environment and lists the `/api/admin` paths; if the console must not
  be discoverable from the schema either, production needs the admin router excluded from the public document.

## Prototype P15-B (M2 queues, 2026-09-30): built

Branch `feat/REQ-ADM-01-queues`. Backend only; the screens are P15-F on P11-F's `/admin` shell.

- **Staff access**: the `staff_member` dependency above, unchanged. Sections by role (docs/spec/03): admin =
  moderation, claims, research, niches; moderator = moderation only; support = `GET /api/admin/me` only (403 on every
  queue). Non-staff get the console's 404 everywhere, stale staff 403 `step_up_required`.
- **Moderation queue** (REQ-MOD-01, `bridge/admin/moderation.py`): `GET /api/admin/moderation/cases[?decided=true]`
  now gives each case the subject's current Tier-1 text field by field (`fields`), the fields the pre-screen flagged
  (`flagged_fields`), the decisions the decision route accepts from the caller now (`actions`) and otherwise the code it
  answers (`blocked`: `already_decided`, `unsupported_subject`, `subject_gone`, `own_content`,
  `cannot_approve_vulnerability`), and `decided_at` / `decided_by`. Open cases oldest first; decided ones newest
  decision first (they were oldest first, so the latest decisions fell past the 200 cap). The decision still goes
  through `app_moderate_proposal` / `app_moderate_problem` (no new database function); since the review round it also
  answers 409 `subject_gone` when the subject no longer exists (it answered 403 `own_content` through the function's
  P0002), and refuses an unsupported subject before reading the subject.
- **Claims queue, read only** (REQ-DIR-03 queue, `bridge/admin/claims.py`, a sub-router): `GET
  /api/admin/claims?view=review|in_progress|closed` and `GET /api/admin/claims/{claim_id}`, staff admin only. Review =
  `pending_review` and `disputed`, oldest first, with the review SLA (`policy.yaml` `claims.review_sla_bd: 2`, Kenyan
  business days from the Nairobi day of `created_at`, due at the end of the day, on `app_clock_now()`); a dispute
  carries its open `claim_dispute` case instead. No decision: `app_decide_claim` is not called and no other method
  exists, so no security-reviewer round is needed (prototype plan §5).
- **Demo** (`bridge/seed/demo/queues.py`, P9 re-seed rules): staff moderator `moderator@staff.example` ("Staff
  Moderator (demo)", `data.STAFF`); Amina's P6 "Clear loan-fee statements for SACCO members", published through the API
  and held by the rules pre-screen (it names SACCO B (fixture) negatively), plus its new problem's open case; County
  Government of C (fixture)'s E2 claim, filed by its owner under RLS, awaiting review.

Tests: `integration/admin/test_claims_queue.py` (7), `integration/admin/test_moderation_queue.py` (+5: roles,
contents, subjects that cannot be decided here, order, the moderation function), `unit/admin/test_claims_policy.py`,
`unit/admin/test_moderation_options.py`, `integration/demo/test_demo_seed.py::test_each_staff_queue_has_an_item_for_the_demo_moderator_and_admin`.

Mutation sample. Round 1 reported "23 of 23 killed": true of my 23 mutants, but the sample missed what the reviewer
then found surviving (CHANGES_REQUIRED): the SLA counted from the UTC date instead of the Nairobi date (the boundary
test used a Friday night that is the same day in both), the KE holiday rows never reaching the SLA (another country's,
or none, passed), and a staff member's own problem not seen as own content. The fix round added
`unit/admin/test_claims_policy.py::test_the_submission_day_is_the_nairobi_date_not_the_utc_date`,
`integration/admin/test_claims_queue.py::test_the_review_sla_skips_kenyan_holidays_only` (a KE holiday inside a dated
claim's window moves its due day, a UG one does not; the rows are removed afterwards) and the own-problem case in
`test_own_gone_and_other_subjects_cannot_be_decided_from_this_queue`, plus mutants for each. Re-run: 30 of 30 killed
(the 23, the reviewer's three, two more holiday variants, and two on the decision's `subject_gone` and
`unsupported_subject` order).

Open items (P15-B):

1. An organisation staff cannot read under RLS (delisted, `pending`, `rejected`: the `organizations` policies admit
   members and listed organisations only) shows its id alone in the claims queue. Naming it needs a staff SELECT
   policy (db-migrations).
2. The SLA counts from `org_claims.created_at` (the database's `now()`): no column records when a claim entered
   review. The claim flow should record it (db-migrations) and the SLA count from it. After `make demo-clock` the SLA
   compares the moved clock with a real `created_at`, so a claim looks older by the offset.
3. The claim detail gives `document_count` only (storage keys stay server-side): E2 review needs a signed download
   route later.
4. `claim_dispute` cases show in the moderation queue as `unsupported_subject` (decided from the claims queue once
   claims can be decided); nothing files them in the prototype.
5. Other methods on the admin paths answer 405 to anyone, which, like the public `openapi.json` (open item above),
   shows the paths exist.
6. Both queues stop at 200 items with no paging; `flagged_fields` are the first filing's (a later version merged into
   an open case adds reasons only).
7. README "Demo logins" (P16, docs-writer) lists neither staff account: `admin@staff.example` (research, claims) and
   `moderator@staff.example` (moderation queue). Amina now has 3 active proposals, the free plan's cap: her next
   publication gets the 402 upgrade path.
