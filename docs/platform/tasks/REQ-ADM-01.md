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

### P15-B re-review MINOR (2026-09-30; reviewer PASS round 2 on 935ec45)

- `admin/moderation.py:261`: nothing pins that `subject_gone` is checked before `case_changed`; the gone-case test should
  also send a stale non-null `subject_version_id` and expect `subject_gone`.

## Prototype P15-F (M2 queue screens, 2026-09-30): built

Branch `feat/REQ-ADM-01-fe` (from P15-B `05394b1`, with integration `c0a460a` merged for P11-F's `/admin` shell);
frontend only, against the frozen `backend/openapi.json` (unchanged).

| Area | Files |
|---|---|
| Navigation | `frontend/components/{AdminNav.tsx, AdminNav.test.tsx, admin-icons.tsx}` (Moderation: admin, moderator; Claims: admin), `frontend/lib/auth/routing.ts` (`CONSOLE_ROLES` admin, moderator; test in `validation.test.ts`), `app/(admin)/admin/page.tsx` (comment) |
| Console shared | `app/(admin)/admin/{load.ts, ViewTabs.tsx, strings.ts}` (research's server reads moved to `load.ts` unchanged; step-up strings trimmed to `adminResearch.stepUp` + `refusal.generic`) |
| Moderation | `app/(admin)/admin/moderation/{page.tsx, CaseRow.tsx, CaseDecision.tsx, moderation.ts, calls.ts, data.ts, strings.ts, cases/[id]/page.tsx}` + `moderation.test.ts`, `moderation-screens.test.tsx`, `case-page.test.tsx` |
| Claims | `app/(admin)/admin/claims/{page.tsx, ClaimRow.tsx, claims.ts, data.ts, [id]/page.tsx}` + `claims.test.ts`, `claims-page.test.tsx` |
| Strings | `frontend/locales/{en,sw}.json` (`admin.nav.moderation`, `admin.nav.claims`, `adminModeration.*`, `adminClaims.*` inserted after `adminResearch`; `_meta.reviewP15f` after `_meta.reviewP11f`), `lib/i18n/client-strings.ts` (`adminModeration`, mid-list) |
| E2E | `frontend/e2e/moderation.spec.ts`, `frontend/e2e/support/moderation-scene.ts`, `e2e/support/totp.ts` (`base32Encode`, `demoTotpSecret`; `test/demo-totp.test.ts`), `e2e/support/research-scene.ts` (`newStaffAdmin({ role })`), `e2e/research.spec.ts` (console paths; an admin has a tab bar now) |

**What it does.** A moderator's console home is Moderation (their one section, no tab bar on phones); a staff admin
has Research, Moderation and Claims (bottom tabs under 1024 px); support keeps the no-section home. `/admin/moderation`:
Open (oldest first) and Decided (newest decision first) as link tabs; "Review the oldest case" (the oldest case this
moderator can decide) is the one primary action; each row has the subject kind, its title, the start of its public
summary and at most two tags (visibility: hidden until decided, public while checked; or the outcome once decided; and
the first reason). `/admin/moderation/cases/{id}` (found in the open list, then the decided one): the reasons as fixed
sentences (routine ones with the info mark, flags with the warning mark), the Tier-1 text field by field in a panel
where a flagged field carries a margin rule, a warning mark and the word "Flagged" (never colour alone), and the
decision. Approve sends `subject_version_id`; Reject asks once more (the question group takes focus, Cancel returns it).
A stale second factor shows P11-F's `StepUp` in place of the buttons, then repeats the decision. `case_changed`
refreshes the page (the new version's text and choices) and the status line explains; `already_decided` refreshes to
show who decided; `not_found`, `own_content`, `unsupported_subject` and `forbidden` leave only "Back to Moderation";
`cannot_approve_vulnerability` leaves only Reject. The status line (`role="status"`) is always in the tree, is the same
node across refreshes and step-ups (the client component is keyed), and takes focus on every change. After a decision:
"Review the next case" (primary) and the way back. A case whose `blocked` leaves no action shows its fixed sentence and
no buttons. `/admin/claims` (staff admin): Review, In progress and Closed; one tag per claim (the review SLA as a mark
and words: "Due in N business days", "Due today", "Overdue" with the warning mark; else the status), what it asks for,
claimant, domain, date; no registration number, KRA PIN or address. `/admin/claims/{id}`: one sentence that deciding
claims is not in the prototype, the claim, claimant (address), checks, the E2 evidence (registration number, CR12 date,
KRA PIN, sector register, public entity, document count; "shown on this page only"), the organisation, other open
claims and moderation cases; no buttons. An organisation staff cannot read is "Organisation <id>" (short id in the list,
whole id on the page) with a plain note.

**Tests.** Vitest: `moderation.test.ts` (views, kinds, titles, reasons and tones, fields, visibility, outcomes, every
refusal mapped without the API's words, a 404 always "not found"), `moderation-screens.test.tsx` (approve with focus on
the status line and the next case, problem wording, Reject asked twice with focus, `case_changed` refresh then the new
version sent with the same status node, step-up then repeat, step-up cancel focus, `already_decided`, four back-only
refusals, vulnerability reject-only, generic, blocked without actions), `case-page.test.tsx` (server-rendered case page:
flagged field by mark and word, unknown reason, blocked, decided, gone, step-up, support; queue: two tags, the primary
action skips a case the moderator cannot decide, empty state, decided view), `claims.test.ts`, `claims-page.test.tsx`
(SLA mark and words, no personal data in the list, unnamed organisation, statuses, empty views, moderator refused,
step-up; detail evidence, read-only sentence, no buttons, gone), `AdminNav.test.tsx`, `validation.test.ts`,
`demo-totp.test.ts`. Playwright `moderation.spec.ts` (both projects; `checkScreen` on every screen): walkthrough step 6
on the demo seed (desktop: the demo moderator sees held P6 with its reason, the flagged problem statement, approves it,
the teaser goes from 404 to 200 for a developer, and the decided view names who approved; 360 px: the demo admin opens
Moderation from the tab bar and approves P6's new problem); a staff admin reads County C's claim (SLA mark and words, no
address in the list, the read-only sentence, no buttons, the Closed view); own scene: a moderator is refused Claims,
Reject is asked twice with focus, a new version plus a stale second factor gives the code form, then the "new version"
status with the new text, then approval publishes; vulnerability content offers Reject only and stays hidden.
`research.spec.ts`: the unknown-address check covers the four new paths. The whole suite (128 tests, both projects) passed on an
isolated stack with a fresh demo seed. JS (gzipped, `npm run budget`, signed in): `/admin/moderation` 144.0 KB, the case
page 146.7 KB, `/admin/claims` and a claim 144.0 KB, `/admin/research` 145.5 KB (budget 150 KB; the case page is 150.4
KB with response headers, D-28).

**Open items (P15-F).**

1. **Blocked cases with an action.** The brief asked for "no actions" when a case has `blocked`; the API gives
   `cannot_approve_vulnerability` with `actions: ["reject"]` (REQ-PROP-02: vulnerability content is rejected, never
   approved), so that case shows its fixed sentence and Reject only. Every other `blocked` shows the sentence and no
   buttons.
2. **Demo cases are single-use** (superseded in the fix round below: each run now puts its item back). Each demo case can be decided once and each demo login can sign in from one project
   at a time (the API refuses a reused TOTP code), so the walkthrough approves P6 on desktop (demo moderator) and P6's
   new problem at 360 px (demo admin); the claims test uses its own staff admin. A rerun, or a CI retry after the
   approval, needs a freshly seeded demo; `expectDemoQueues` (beforeAll) says so when the seed is missing.
3. **No single-case route.** The case page reads the open list, then the decided list (200 each);
   a decided case past the decided list's end reads as "not in the queue". A `GET /api/admin/moderation/cases/{id}`
   would remove both reads.
4. **Step-up strings are P11-F's** (`adminResearch.stepUp.*`, sent trimmed); a console-wide namespace would be cleaner
   when the Research strings next move.
5. **Claims SLA and names** inherit P15-B open items 1 and 2 (unlisted organisations by id; the SLA counts from
   `created_at`).
6. **Copy.** All new strings are `[[COPY-REVIEW]]` (`_meta.reviewP15f`); Swahili is a draft (`[[SW-REVIEW]]`).
   `adminModeration.reason.*` names the pre-screen's codes; the Haiku classes (spam, defamation, …) are ready for when
   it plugs in.
7. **Commit size.** `3201d8b` (moderation screens with their tests, +1137) and `18f7be2` (both locale files, +492) are
   over about 300 lines.
8. **`impeccable`** is not installed here; the polish pass was by hand against docs/spec/07 with screenshots at 375 and
   1440 px.

### P15-F fix round 1 (reviewer: 3 MAJORs, 2 MINORs; ux-reviewer: 1 MAJOR)

Integration merged first (`a9c7cd9`: P15-B `a5386ad`, P16-A `b5c344f`; the card's conflict kept both sections).

- **MAJOR 1, `subject_gone`** (`e25db0d`). The decision route's 409 `subject_gone` is a refusal of its own
  (`adminModeration.refusal.subject_gone`, en and sw, `[[COPY-REVIEW]]`): only "Back to Moderation" remains and the page
  is fetched again (`REFRESH_AFTER`: `already_decided`, `subject_gone`, `cannot_approve_vulnerability`).
  `refusal.own_content` no longer says "or it no longer exists". Tests: `refusalOf`/`refusalNext` cases, the screen's
  back-only table with the refresh asserted.
- **MAJOR 2, the repeated decision** (`a4a4c1a`). A stale second factor on Reject repeats Reject
  (`toHaveBeenNthCalledWith(1|2, CASE_ID, "reject", VERSION)`); the Approve test pins its second call. The mutant
  `onConfirmed={() => run("approve")}` is killed.
- **MAJOR 3, the walkthrough's order and retries** (`48f3eb0`). Each project puts back only the demo item it decides
  (`reopenDemoItem`, owner SQL: desktop P6 held, 360 px P6's problem clear and published; its case open with
  `decided_by`/`decided_at` cleared) in `beforeEach`, then `expectDemoQueues(item)` checks that case is unresolved; the
  360 run asserts only on its own problem case. A rerun also exposed that a retry in a new worker reused a demo TOTP
  window the API had accepted: demo staff codes now start after `users.totp_last_counter` (owner read). Both projects
  pass in either order and twice in a row (`--repeat-each 2`).
- **UX MAJOR, the decided header** (`0be13f2`). A decided case's header shows the outcome (Approved/Rejected, mark and
  word) instead of the visibility tag of a case being checked; vitest (and a mutant) and the E2E check the refreshed
  header.
- **MINORs** (`3409800`). `calls.test.ts` (path, CSRF, body `{decision, subject_version_id}`, null version, refusal by
  code, thrown fetch → generic); `data.test.ts` (no next case when the only other open case has `actions: []`, the
  oldest decidable other case, decided and unknown cases).

Checks: eslint, typecheck, vitest (74 files, 962 tests), `api:check`, copy lint, traceability; Playwright
`moderation.spec.ts` and `research.spec.ts` (16 tests, both projects) on an isolated stack, removed afterwards.

Left open: the demo reset writes the proposal's `moderation_state` and the cases as the database owner (test data
only); a re-approval of P6 writes another `proposal_published` signal and queues another `scouts.on_new` run, harmless
on a test stack.
