# REQ-PROP-05

- Task: T2.9 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-ai (backend), impl-frontend (opt-in dialog, F2)
- Files owned: `bridge/proposals/assistant.py`, `bridge/proposals/assistant_router.py`
- Depends on: T2.2, T2.3.

## Scope

The submission assistant (Sonnet 5 through `LLMClient`, fake/cassette in CI) suggests Tier-1 vs Tier-2 placement of the developer's own text. It runs only after an explicit per-use opt-in recorded as a `consents` row `tier2_llm_assistant` bound to the session (expires with it); it never auto-publishes or edits; output is labelled "AI-drafted".

## Acceptance criteria and tests

AC-SEC-6 (`unit/llm/test_no_tier2_in_llm_calls.py`, `unit/proposals/test_assistant_consent.py`).

## Prototype P13, backend (2026-09-29): built

Branch `feat/REQ-PROP-05-assistant` (impl-backend). No schema change, no new environment variable, no new model task
(`submission_assistant` in `backend/ai/models.yaml`: Sonnet 5 on Anthropic, free slots 1-3 on local runs, purpose
`tier2_llm_assistant`, no tools). Files: `bridge/proposals/assistant.py` (rules), `bridge/proposals/assistant_router.py`
(routes, registered in `main.py`), `bridge/profiles/{consents,router}.py`, `config/consents.yaml`,
`bridge/llm/guard.py` (`PER_SESSION` is now `consents.SESSION_ONLY`), `backend/openapi.json`,
`frontend/lib/api/schema.d.ts`.

**Routes** (owner only: 404 for anyone else's proposal or none, 409 `proposal_hidden` for a deleted one, first):

- `GET /api/me/proposals/{id}/assistant/consent`: `{purpose, granted, scope: "this_session", text, version}`; `granted`
  is true only while this login session holds the opt-in.
- `POST .../assistant/consent` `{version}`: 409 `consent_text_changed` unless it is the current `consents.yaml`
  version; then `grant_session_consent` (source `session:<session id>`), a `consent.changed` audit event
  (`{tier2_llm_assistant: true, scope: "session", text_version, from_proposal_id}`: the scope is the session, the proposal only where it was turned on) and a commit.
- `DELETE .../assistant/consent`: `withdraw_session_consent`, the same audit event with `false`, a commit; works from a deleted proposal too.
- `POST .../assistant/suggestions`: 403 `consent_required` unless this session's opt-in is live, checked before
  anything is read or sent (so a Tier-1-only draft is gated too: the LLM layer's guard covers Tier-2 fields only).
  Reads the saved draft version (else the current version): the four Tier-1 teaser fields and the four Tier-2 text
  fields (never links or attachments), each an `InputField` owned by the owner, Tier 2 tagged. One call through the
  request's `RoutedLLMClient` (sanitiser, nonce framing, caps before the call, `llm_calls` row, D-37 rule on free
  slots). Returns `{demo_fallback, status, message, ai_drafted, version_id, teaser: {title, summary} | null,
  placement: [{field, move, reason}]}` and writes a `proposal.assistant_suggested` audit event (version, status,
  reason code, demo flag, trace id, `tier2_fields_read`), also for a refusal after the confidential text was read (status `refused`). It never writes the proposal: the editor applies a
  suggestion through `PATCH /api/me/proposals/{id}`.

**Code decides** (`assistant.evaluate`): a demo fallback (`TeaserSuggestion.demo_fallback()`: no suggestion,
`injection_suspected=True`) is status `demo_fallback` with `demo_fallback: true` and no teaser; `injection_suspected`
is status `injection_suspected` with nothing shown; a suggested title and summary are kept only when the Tier-1
sanitiser accepts them (contact details, links, 120 characters, 150 words) and they change something; a placement hint
is kept once per field, only for a field with text, only away from its tier, with a plain-text reason (cut to 300
characters) carrying no contact details. A draft with neither a title nor a summary asks nothing.

**Errors** (`assistant.refusal`; fixed `[[COPY-REVIEW]]` messages, never the exception text): `ConsentRequired` 403
`consent_required`; `Tier2DemoOnly`/`NotDemoData` 403 `assistant_demo_only`; kill switch 503 `assistant_off`; tenant
budget 429 `assistant_budget`; global or total budget and a slot's request cap 503 `assistant_paused` (no figures:
T2.2 security MINOR 3); a provider that is down, unavailable or failing is 200 status `unavailable` (on local runs the
router has already answered with the labelled fallback). `LLMConfigError` and a Tier-1-only `Tier2NotAllowed` are code
mistakes and propagate.

**Consents (REQ-LLM-01 carry-over).** `GET /api/me/consents` no longer lists `tier2_llm_assistant`; `PUT` refuses it
with 422 `consent_session_only` (the whole body). `consents.yaml` 2026-09-29.2: "During this sign-in only, let the
writing assistant send my proposals, including their confidential (Tier 2) text, to an AI model when I ask it to suggest
a clearer teaser. It ends when I sign out or turn the assistant off." (`[[COPY-REVIEW]]`, D-39 item 6). The public
`GET /api/consents` still lists every text.

**Tests.** `unit/proposals/test_assistant_consent.py` (per-session gate, nothing sent without it, framing and
sanitising, ledger without values), `unit/proposals/test_assistant.py` (owned and tagged fields, evaluation, fixed
refusals without figures, provider failures), `integration/proposals/test_assistant_consent_api.py` (nothing sent or
recorded without consent, for Tier-1-only drafts too; per session; ends at sign-out; audited grant and withdrawal;
stale wording; owner only; deleted proposal), `integration/proposals/test_assistant_suggestions_api.py` (D-37 refusal
and fallback for a non-demo owner with the fake adapter seeing zero requests, demo fallback labelled, global budget
message fixed on the Anthropic route, injection framed and refused, proposal unchanged, published proposal read from
its current version), `integration/profiles/test_session_only_consents.py`, `unit/test_consents.py`. AC-SEC-6 also
keeps running on every task in `unit/llm/test_no_tier2_in_llm_calls.py`.

**Mutation proofs** (each applied, the assistant tests run, the file restored with `git checkout`): (M1) the route's
consent pre-check removed: 3 red (both `test_nothing_is_sent_without_the_sessions_consent` cases, the sign-out test);
(M2) the guard stops comparing the grant's session: 1 red (sign-out and other-session test); (M3) the teaser fields
sent ownerless as public data: 1 red (unit); the D-37 user check still refuses a non-demo caller, so no API test can
tell; (M3b) the confidential fields sent untagged as Tier 1: 5 red; (M4) the `Tier2DemoOnly` raise removed from
`llm/demo_data.py`: 1 red (`test_a_non_demo_owners_confidential_text_never_reaches_a_free_provider`); (M5) a demo
fallback treated as an answer: 3 red; (M6) the global budget message carrying the error text: 4 red.

**Open (follow-ups, not built).**

1. **Done in P17** (`feat/REQ-AUTH-01-followups-7-8`, REQ-AUTH-01 card): signup refuses session-only purposes,
   whatever their value, with 422 `consent_session_only` on the email form (`_validate_signup`) and at both steps of an
   OAuth signup (`_check_consents` at start and callback), through `bridge.auth.service.refuse_session_only`. Was:
   signup recorded a `tier2_llm_assistant` decision if a client sent one (`source = "signup"`; the guard counted only
   `session:` rows). The THREAT_MODEL row moved from §2 to §1.
2. docs/spec/09 says "Sync, streaming": the prototype answers in one response; streaming later.
3. **Done in review round 1:** a code overlap check (`tier2_overlap_words`). Still open: a paraphrase or a shorter copy
   passes; the Haiku over-disclosure check (docs/spec/09) belongs with REQ-PROP-02's warn-only check.
4. No eval set covers the assistant (docs/spec/09 lists none); the injection behaviour is covered by the tests above.
5. The Tier-2 read for the assistant is audited as `proposal.assistant_suggested` (`tier2_fields_read`), not as a
   separate `proposal.tier2_read`.
6. **Built in P13-F** (below): the editor panel (consent dialog from `GET .../assistant/consent`, "AI-drafted" and
   "demo fallback" labels, apply through the editor's PATCH). **P13-F must never apply a suggestion automatically**:
   the owner applies it (reviewer note, review round 1).
7. Reviews: `reviewer` and one `security-reviewer` round (Tier-2 text to an LLM under per-session consent,
   `prototype-m2-plan.md` §5). The REQUIREMENTS row status is left to the orchestrator.

## Review round 1 (2026-09-29): reviewer and security-reviewer CHANGES_REQUIRED, fixed

- **MAJOR 1 (reviewer):** the owner-only test used a draft, which RLS hides anyway; removing `AND owner_id = :user`
  from `assistant.owned` left every test green while a stranger's call sent a published teaser under the owner's id.
  `integration/proposals/test_assistant_consent_api.py::test_the_assistant_is_the_owners_only` now runs on a published
  and a draft proposal, the stranger holding a live opt-in of their own (a demo account), and asserts 404 on every
  route with no provider request (`0e07294`). Mutation: the filter removed turns the published case red.
- **MAJOR 2 (security):** no per-user limit; a 12-call burst sent 12 requests. Now, before the confidential text is
  read: one suggestion in flight per user (`assistant.InFlight` on `app.state`, 429 `assistant_busy`) and a daily limit
  of the user's `submission_assistant` ledger rows since the UTC day start (429 `assistant_rate_limited`), both in
  `policy.yaml` `assistant` (`bridge/proposals/assistant_policy.py`, strict loader). The in-flight count is per API
  process: **several workers need a ledger reservation row** (a row written before the call and settled after it)
  instead. Tests: `integration/proposals/test_assistant_limits_api.py` (a held 12-request burst: exactly one provider
  request, eleven 429 with no ledger row; the daily limit per user). Mutations: the claim ignored (burst red), the
  daily check removed (daily test red).
- (a) Refusals after the confidential text was read (403 `assistant_demo_only`, 429 `assistant_budget`, 503) write
  `proposal.assistant_suggested` with status `refused` and the code, commit, and re-raise.
- (b) The audit key is `tier2_fields_read` (names read for the call; `llm_calls` shows what left).
- (c) Per session, not per proposal: new wording (2026-09-29.2), `from_proposal_id` in the grant's audit, withdrawal
  from a deleted proposal.
- (d) `test_on_the_anthropic_route_a_consenting_owners_tier2_goes_through_once` (and nothing without consent).
- (e) `rejected:tier2_overlap`: a suggested title or summary sharing `tier2_overlap_words` (8) consecutive words (plain,
  case-folded) with a confidential field that was sent is not shown; an injection inside Tier 2 is tested. Mutation:
  the check disabled turns the unit and the API test red. THREAT_MODEL §6 has the new row.
- (f) The two `POST` routes carry the `tier2` tag and `access.tier2_gate` (403 `tier2_disabled` while
  `FEATURE_TIER2_ENABLED` is off; refusals audited with purpose `assistant`); `test_feature_flags.py::EXPECTED` lists
  them. `GET` and `DELETE .../assistant/consent` stay open (turning the assistant off always works).
- THREAT_MODEL: §1 (signup residual), §2 (one user starves others), §5 (flag), §6 (cost loops; tier crossing).

## Round 2 (reviewer PASS and security-reviewer PASS at `b43822c`, 2026-09-29): MINOR follow-ups

- The daily limit counts `llm_calls` rows, but a demo-fallback answer (the fake provider, or a non-demo owner's
  Tier-1-only draft on a free slot) writes none, so fallbacks are uncounted (no provider cost; each still decrypts
  Tier 2 and appends an audit event). Count today's `proposal.assistant_suggested` events instead, or write a
  zero-cost ledger row for a fallback.
- `shingles()` folds case and compatibility forms but not confusable scripts (Cyrillic or Greek lookalikes pass the
  overlap check): run `sanitise.detection_skeleton()` on both sides before `casefold()` and add the Cyrillic case.
- No test asserts that assistant refusals are audited with purpose `assistant` (mutation "always RENDER" survives):
  assert each refusal's purpose in `test_feature_flags.py`.
- The signup-residual THREAT_MODEL row sits in the §2 tenancy table, not §1 as this card says: move it or fix the note.

## Prototype P13-F, frontend (2026-09-30): built

Branch `feat/REQ-PROP-05-screens` (impl-frontend). No backend change; the API is used as frozen in `backend/openapi.json`
(typed through `frontend/lib/api/schema.d.ts`).

**Files.** `frontend/app/(app)/dev/ideas/assistant.ts` (the four calls, refusal codes, `statusKey`),
`frontend/app/(app)/dev/ideas/editor/AssistantPanel.tsx` (the panel and its consent dialog), `editor/Editor.tsx` (the
"Writing assistant" section on step 1 with a secondary "Suggest a clearer teaser" button; the panel loads through
`lib/preloadable` only when pressed), `editor/EditorScreen.tsx` and `lib/i18n/client-strings.ts` (the `ideaAssistant`
namespace, server-formatted), `ideas/save.ts` (re-exports the typed client so the assistant's calls share the save
chunk instead of bundling a copy), `locales/en.json` and `locales/sw.json` (`ideaEditor.assistant*`, `ideaAssistant.*`,
identical keys; `_meta.reviewP13`), `scripts/js-budget.mjs` (`--press=<button name>`).

**Behaviour.** Opening the panel saves what is typed (the assistant reads the saved draft; a refused save asks nothing)
and asks at once. Without a live opt-in for this sign-in, a native `<dialog>` shows the API's consent wording verbatim
(never restated) with "Not now" focused; "Turn on and ask" sends back the `version` it showed, then asks once. "Not
now" or Escape closes the panel with nothing sent and focus back on the button. A 409 `consent_text_changed` shows the
new wording and sends its version next time; a 403 `consent_required` from the suggestion (opt-in ended elsewhere)
reopens the dialog. The answer puts the suggested title and summary beside the current ones (stacked at 375 px),
labelled "AI-drafted" when `ai_drafted` and "Demo fallback" when `demo_fallback` (at most two chips), with the
placement hints (field, direction, the AI-drafted reason). **"Use this" is the only way a suggestion reaches the
fields**, through the editor's own `update`, so its autosave `PATCH` saves it; nothing is applied on arrival. "Turn off
the assistant for this sign-in" sends `DELETE .../consent`, clears the last answer and focuses the notice. Focus goes to
the answer's heading when it arrives and to the notice that replaces a pressed button. Every refusal has a fixed
`[[COPY-REVIEW]]` sentence (`ideaAssistant.problem.<code>` for `consent_required`, `consent_text_changed`,
`assistant_busy`, `assistant_rate_limited`, `assistant_budget`, `assistant_paused`, `assistant_off`,
`assistant_demo_only`, `tier2_disabled`, plus 401/404/409 `proposal_hidden`/429/503/offline/other); statuses
`unavailable`, `no_suggestion`, `injection_suspected`, `demo_fallback` have theirs (`ideaAssistant.status.*`). The API's
`message` is never shown.

**`rejected:tier2_overlap`.** The API does not return the reason code (only `status: no_suggestion` and a generic
message), so the screen cannot tell an overlap from "nothing to improve". The fixed `no_suggestion` sentence covers it:
"Suggestions that copy wording from your full details are held back." A distinct sentence needs a `reason` field in
`AssistantSuggestionOut` (backend follow-up, open question 1 below).

**Tests.** Vitest `editor/assistant.test.tsx` (34): closed = one secondary button and no call; the dialog shows the API
wording, focuses "Not now", sends nothing before "Turn on"; the version sent back; "Not now" and Escape; changed wording;
already on; `consent_required` reopens; the HTTP sequence (GET, POST version, POST suggestions); the comparison, labels,
hints and focus; **no apply without the click** (fields and `saveState` untouched for longer than the autosave delay,
then "Use this" saves through the editor); demo fallback; hints only; no text; a refused save; a table of every refusal
over a fake network (real calls, real client) and every status; turning off and closing. Mutation checks: applying on
arrival turns 3 red; sending a fixed version instead of the shown one turns 1 red. Playwright `e2e/assistant.spec.ts`
(fake LLM, `FEATURE_TIER2_ENABLED=true`; requires `E2E_DATABASE_OWNER_URL`, no skip): the opt-in walked end to end
with the `consents` rows (`session:` source, the shown version) and `consent.changed` / `proposal.assistant_suggested`
audit rows checked as the owner, nothing recorded before "Turn on", the labelled demo fallback, the idea unchanged,
withdrawal and the dialog again; a new idea without text sends nothing; a stubbed suggestion (the fake never writes
one; only that response is stubbed) reaches the idea only through "Use this" and the editor's `PATCH`. `checkScreen`
(axe serious/critical, one `[data-primary]`, no horizontal scroll) with the panel closed, the dialog open, the answer,
the suggestion, applied and turned off, at 360, 375 and 1440 px. 6/6 green.

**Screenshots** (375 and 1440 px, `E2E_SHOTS_DIR`), in [`screenshots/REQ-PROP-05/`](screenshots/REQ-PROP-05/):
`assistant-closed`, `assistant-consent`, `assistant-answer` (demo fallback), `assistant-suggestion`,
`assistant-applied`, `assistant-off`, each `-375.jpg` and `-1440.jpg`.

**JS budget** (`node frontend/scripts/js-budget.mjs`, production build, signed-in test developer, 360 px; bytes of
gzipped JS, budget 150,000):

| `/dev/ideas/<id>/edit` | before P13-F (`c6bb896`) | P13-F |
|---|---|---|
| page load (panel closed) | 145,814 | 146,078 |
| through the first edit | 147,810 | 148,115 |
| after pressing "Suggest a clearer teaser" (with or without an edit first) | n/a | **150,926 (over by 926)** |

The closed panel costs 264 B. Open, the panel's chunk is about 2.8 KB (from 4.3 KB: it shares the save chunk's typed
client and carries no mapping tables); the typed client itself is the save chunk the first edit loads anyway. Open item
2 below.

**Open (P13-F).**

1. `rejected:tier2_overlap` has no sentence of its own: the API does not expose the reason (see above).
2. With the panel open the editor route is 926 B over the 150,000 B budget. The panel's chunk is already lean; fitting
   needs about 1 KB out of the editor's own first-load code (P8), or a decision that an optional, on-demand panel
   counts outside the route's load budget (docs/spec/07 item 5 / AC-UX-3 measure page load).
3. The impeccable skill is not installed in this container; the polish pass was done by hand against docs/spec/07 and
   the screenshots (frontend-design skill used for the layout).
4. Swahili strings are drafts (`[[SW-REVIEW]]`).

## P13-F review round 1 (2026-09-30): reviewer PASS; ux-reviewer CHANGES_REQUIRED, fixed

- **MAJOR 1 (focus lost):** a new ask focuses the panel heading (the editor's button is gone and "Ask again" hides while
  the request runs); every refusal moves focus to its sentence (`fail()` in `AssistantPanel.tsx`). Tests: the first
  ask refused, and "Ask again" with focus on the button, then refused (mutation: the heading focus removed turns 1 red;
  the refusal focus removed turns 15 red).
- **MAJOR 2 (text beside itself after "Use this"):** the owner's previous title and summary stay in the left column as
  "Before", and an "Undo" link-button puts them back through the editor's `update` (so its autosave). Vitest and e2e
  (the API's draft holds the suggestion after "Use this" and the owner's words again after "Undo").
- MINORs: a new ask clears the last answer (a refused "Ask again" never shows the old suggestion; mutation: 1 red); a
  local error boundary (`PanelBoundary` in `Editor.tsx`) turns a failed chunk load into `problem.network` beside the
  button with focus on it, and the next press loads the module afresh (preloadable keeps a rejected load); the Suspense
  fallback is `role="status"`; `editor/assistant-load.test.tsx` fails when `Editor.tsx` imports the panel or the
  assistant's calls statically, and walks a failed load and the retry (mutation: no fresh load turns 1 red); after 409
  `consent_text_changed` with a failed re-read, the outdated wording goes, the problem shows and "Turn on and ask" is
  `aria-disabled` and inert until the panel reads the wording again; HTTP rows for a refused `GET /consent` on open
  (503, 401, 409 `proposal_hidden`, offline), 401 `mfa_required`, a plain 429 and a refused `DELETE`.
- Copy (`[[COPY-REVIEW]]`): `status.demo_fallback` "This demo has no AI model connected, so there is no suggestion.";
  the panel heading is "Writing assistant's answer" unless a teaser is suggested ("Suggestion"); after turning off, the
  footer action reads "Turn on and ask"; new `before`, `undo`, `undone`, `headingAnswer`.
- Left as they are (orchestrator): the "(Tier 2)" consent wording (D-39 item 6, backend); the budget pass rule (D-28
  addendum records the page-load reading).
- Screenshots re-taken for the states that changed: `assistant-answer`, `assistant-applied` (Before and Undo),
  `assistant-off` ("Turn on and ask"), each at 375 and 1440 px.
- JS budget after the round (same method as above): page load (panel closed) **146,247** (+433 over `c6bb896`; the
  error boundary is 169 of it), through the first edit **148,284**, after pressing "Suggest a clearer teaser" **151,227**
  (panel chunk 2,943 B).


### P13-F round-2 review MINORs (2026-09-30; reviewer PASS, ux-reviewer PASS on 414eb8e) — follow-ups

1. **Undo overwrites later edits** (`AssistantPanel.tsx:279`): after "Use this", Undo stays offered once the owner has
   edited the applied text and silently puts the Before words back. Hide or re-label Undo once the title or summary
   differ from the applied teaser.
2. **The panel's error boundary treats every error as offline** (`Editor.tsx:84`): show `problem.network` only for a
   chunk-load error, and `problem.failed` otherwise.
3. **A consent wording that cannot be re-read** (`AssistantPanel.tsx:145-151, 344`): the message says "try again" while
   "Turn on and ask" is inert, and the disabled button looks busy. Use a dialog-specific sentence ("Close this and open
   the assistant again to read the wording") and style the button as unavailable.
4. A bare side-effect import of the panel slips past the static-import guard's regex (too minor to act on).
