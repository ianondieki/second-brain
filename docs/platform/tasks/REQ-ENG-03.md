# REQ-ENG-03

- Task: P8 (tracker screens); P5 built the data the screens read. `docs/platform/PLAN.md` §8.
- Agent: impl-frontend (P8), impl-backend (P5 data).

## Scope built in P5 (data only)

`GET /api/engagements/{id}` gives each screen what 6.9 Rendering needs: `state`, `stage_label`, `stage_group` (the
5-group stepper), `whose_turn`, `awaiting` (what moves the engagement on, per party), `actions` (the caller's buttons
only), `due` (business days left, overdue), the current stage's endorsements (name, role, time, method, for the
dual-endorsement rows), agreements, milestones, signatures and payments; the History tab reads `.../history`. Labels
are `[[COPY-REVIEW]]` (`state_machine.STAGE_LABELS`).

## Built in P8 part 5 (prototype, `feat/REQ-ENG-03-tracker-screens`)

Screens (server components; client JS only for the buttons, their forms and the step-up):

- `frontend/components/tracker/`: `model.ts` (the view model: stepper groups from `stage_group`, chips, whose turn,
  the caller's buttons from `actions` only, each command's request with `lock_version`; the paths are checked against
  the frozen OpenAPI at compile time), `Stepper` (an `<ol>` with `aria-current="step"`, vertical below 1024 px, a
  horizontal spine from 1024 px), `Chip` (✓ ● ○ ⏸ ⚠ ✕ as drawn mark + words + colour), `WhoseTurn` ("Awaiting:
  <party>", the next steps from `awaiting`, the business-day countdown), `Endorsements` (Endorsement by Developer /
  by Enterprise: status, name, role, time in EAT, method), `Deal` (agreement versions with IP terms and milestones
  incl. `review_due_on`, signatures with fingerprints, payments, the contact person), `HistoryList` (events in EAT
  with actor and role, and whether the hash chain checked out), `Actions` + `CommandForm` (approve, decline, propose
  terms, record and confirm payment; loaded on demand) + `StepUp` (403 `step_up_required` → authenticator code inline →
  the step runs once more; ADR-002) + `ContactReveal` (the named contact only; `GET .../contact`), `calls.ts` (through
  the CSRF-aware typed client), `data.ts` (server reads), `EngagementScreen` (the tracker both parties see, with
  Tracker, Documents and History tabs as plain links).
- Pages: `/dev/engagements`, `/dev/engagements/[id]`, `/org/engagements`, `/org/engagements/[id]` (the org pages use
  P8 part 3's `orgContext`/`pickMembership`: `?org=` naming another organisation is refused, never switched; `?org=`
  stays on every link); the developer Home (`/dev`): "Needs you", up to five other engagements, three ideas, "New
  proposal" as the one primary action, an empty state pointing to My ideas, the two-step sign-in status.
- Navigation (REQ-UX-01): Engagements in the developer nav (Home, My ideas, Engagements, Companies) and the
  organisation nav (Home, Inbox, Engagements). The org Inbox's stage chip links to the tracker; the idea page's
  Pitches rows link to the tracker once the pitch opened an engagement.
- Refusals: 409 (`stale` or any other conflict) and 404 refresh the page and say so; 403 codes are worded
  (`d2_required`, `deals_disabled`, `sign_outside_platform`, not your step); 422 keeps the form open with the reason.
- Copy: `tracker.*`, `trackerActions.*` (server-formatted client strings), `devHome.*`, `nav.engagements`,
  `ideaPitches.tracker`, tagged `[[COPY-REVIEW]]` in `_meta.reviewP8e`; Swahili is a draft (`[[SW-REVIEW]]`).

Screenshots (375 px and 1440 px, taken by `e2e/tracker.spec.ts` with `E2E_SHOTS_DIR`), in
[`screenshots/REQ-ENG-03/`](screenshots/REQ-ENG-03/): Home (`dev-home-375.jpg`, `dev-home-1440.jpg`), the lists
(`dev-list-*`, `org-list-*`), the tracker in implementation (vertical stepper `dev-tracker-implementation-375.jpg`,
horizontal `dev-tracker-implementation-1440.jpg`), the inline step-up (`org-step-up-*`) and a closed engagement
(`dev-tracker-closed-*`).

Tests: vitest `components/tracker/model.test.ts` (stepper groups incl. ended and on hold, chips, whose turn, actions
→ buttons → requests, documents, links, formatting), `tracker.test.tsx` (chips, stepper `<ol>`/`aria-current`, banner,
dual-endorsement rows, deal records, History, list row ≤2 chips), `actions.test.tsx` (buttons only from `actions`,
one primary, confirmations, milestone buttons, step-up retry once, wrong code, not enrolled, 409/404 refresh, 403,
refusal codes, the five forms' request bodies, CSRF header through the typed client, contact reveal); updated
`DevNav.test.tsx`, `OrgNav.test.tsx`, `org.test.ts`, `org-screens.test.tsx`, `pitch-screens.test.tsx`. Playwright
`e2e/tracker.spec.ts` (both projects, 360 px and 1440 px): both parties in their own browsers walk SUBMITTED → CLOSED
through the buttons and forms (inline step-up on an old second factor, Documents tab, identical History for both
parties: AC-TRACK-3), plus a decline with a reason and a withdrawal; axe, one primary action and no horizontal scroll
on each screen. Skips without `E2E_DATABASE_OWNER_URL` like the other specs (`e2e/support/tracker-scene.ts`).

Checks on `cc4acc1`+ (the copy fix): eslint clean; `tsc` clean; `npm run api:check` clean; vitest 37 files, 522
tests; `next build` with `API_ORIGIN` ok; the whole Playwright suite on a local stack (API 8090, web 3090,
`FEATURE_DEALS_ENABLED=true`, `FEATURE_TIER2_ENABLED=true`): 84 passed, 2 skipped (the known `E2E_VERIFY_CERT_ID`
skip); copy lint PASS; traceability PASS (0 errors). JS budget (`scripts/js-budget.mjs`, gzipped, 1 KB = 1,000 B):
`/dev` 140,096; `/dev/engagements` 140,096; `/dev/engagements/[id]` 144,852 (+3,529 when a form opens: 148,381);
`/org/engagements` 140,096; `/org/engagements/[id]` 144,852.

## Review fix round (code review CHANGES_REQUIRED, ux-review CHANGES_REQUIRED on `8f0bb60`)

- MAJOR 1: `components/tracker/state-machine-parity.test.ts` reads `backend/src/bridge/engagements/state_machine.py`
  and fails when the frontend's copies of `STAGE_GROUPS`, `MILESTONE_STEPS` or `CONTACT_REVEALED` differ, and pins
  `DUAL_ENDORSEMENT_STATES` (MINOR g). Mutations checked to fail it: `NDA_SIGNED: "agreement"`; `submit_milestone`
  from `PLANNED` too; `start_milestone` without `CHANGES_REQUESTED`; `SIGN_OFF` dropped from the dual-endorsement
  stages; `CLOSED` dropped from the reveal stages. It also reads `policy.yaml` `contact_by_max_bd` and checks the number
  the en and sw copy states (MINOR f).
- MAJOR 2 (decline attestation): kept as a `[[COPY-REVIEW]]` draft; `_meta.reviewP8e` references D-39 item 7.
- UX MAJOR (focus, WCAG 2.4.3): a form or confirmation takes focus on its heading, the step-up on its code field;
  Cancel returns focus to the opening button; removing a milestone focuses "Add a milestone"; "Done" sits outside the
  actions section and keeps focus when the step leaves no buttons (vitest for each move).
- MINORs: step-up Cancel inert while the code is checked and no retry after Cancel or unmount (a); the contact reveal
  only for the named contact in the revealed stages (b); the Home "Needs you" split is `homeGroups`, tested with the
  org's-turn mutation (c); the org tracker's links from `detail.org_id` (d/m); the approve form says when the members
  could not be read (e); developer tab labels on one line at 360 px (h); field errors clear on change (i); idea rows
  are h3 on Home (j); dates "23 Sep 2026" from one shared formatter (k); plainer copy for the history check,
  "deemed acceptance" and D2 (l).
- Checks after the round: eslint clean; tsc clean; api:check clean; vitest 39 files, 541 tests; `next build` ok; copy
  lint PASS; traceability PASS; `e2e/tracker.spec.ts` 8 passed (360 px and 1440 px). JS: `/dev/engagements/[id]` and
  `/org/engagements/[id]` 145,042 B; with the Decline form open 148,720 B (budget 150,000): anything new on the
  tracker must load lazily.

## Follow-ups (MINOR, after M1)

1. Reminders: P6 exposes no in-app route yet, so Home has no reminder summary (docs/spec/07 item 1). Trending
   problems on Home come with P12.
2. The API's `documents` names the current stage's document only; the Documents tab adds signed documents and a final
   agreement itself. Milestone confirmations have no document route. A backend `documents` covering every stage would
   remove the client-side union.
3. An ended engagement has `stage_group: null`; the stepper finds the group it ended in from the history's last event
   and a copy of `state_machine.STAGE_GROUPS` (`model.ts`). An `ended_in_group` field would remove the copy.
4. Sub-stages of the current group are not listed (only the stage's label); side states (`ON_HOLD`, `DISPUTED`, …)
   render as chips only (after the prototype). Visual regression snapshots at 360/1280 (AC-TRACK-4) and the other
   paths (expiry, on hold, dispute, ORG_INTEREST) wait for the test clock walk and M2.
5. The copy lint's non-binding rule covers `tracker.*` but not `trackerActions.*` (the approve button carries the
   qualifier anyway): add `trackerActions.` to `copy/banned_claims.txt` namespaces.
6. `trackerActions.decline.attest` is attestation wording (the D-39 family); the approve form's "five business days"
   mirrors `policy.yaml` `contact_by_max_bd`.
7. Engagements are not grouped by proposal (docs/spec/07: grouped by proposal → one row per org); the org list is a
   list, not a board. Internal notes and the Messages tab come later.
8. The whose-turn banner is at the top of the tracker, not pinned (sticky bars must not hide focus; Phase 7).
9. Once P9 merges, the e2e can use the demo seed instead of its own fixtures.
10. Six commits of this branch are over the ~300-line guide (the copy, the display and actions with their tests, the
    e2e, and the two review-round commits with tests); no history rewrite.
11. API fields to replace the pinned copies (items 2 and 3): `ended_in_group` (or the stage an ended engagement left)
    and, per milestone command, the milestones it can take now; then the parity test's copies go.
12. Keep a form's draft across a 409 `stale` refresh (`Actions.tsx` `run`): today the refreshed list replaces it.
13. Backend (REQ-ENG-05): send the attestation text's version with the decline, so the stored boolean names the
    wording the organisation confirmed (D-39 item 7).
14. The stage label "Agreement signed: implementation" is the backend's `STAGE_LABELS` copy: change it there.

## After the prototype

Phase 7 polish of the stepper, chips and banner; visual snapshots; the remaining side states.
