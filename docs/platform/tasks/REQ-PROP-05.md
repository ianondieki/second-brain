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
  (`{tier2_llm_assistant: true, scope: "session", text_version, proposal_id}`) and a commit.
- `DELETE .../assistant/consent`: `withdraw_session_consent`, the same audit event with `false`, a commit.
- `POST .../assistant/suggestions`: 403 `consent_required` unless this session's opt-in is live, checked before
  anything is read or sent (so a Tier-1-only draft is gated too: the LLM layer's guard covers Tier-2 fields only).
  Reads the saved draft version (else the current version): the four Tier-1 teaser fields and the four Tier-2 text
  fields (never links or attachments), each an `InputField` owned by the owner, Tier 2 tagged. One call through the
  request's `RoutedLLMClient` (sanitiser, nonce framing, caps before the call, `llm_calls` row, D-37 rule on free
  slots). Returns `{demo_fallback, status, message, ai_drafted, version_id, teaser: {title, summary} | null,
  placement: [{field, move, reason}]}` and writes a `proposal.assistant_suggested` audit event (version, status,
  reason code, demo flag, trace id, the Tier-2 field names sent). It never writes the proposal: the editor applies a
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
with 422 `consent_session_only` (the whole body). `consents.yaml` 2026-09-29.1: "Let the writing assistant send my
proposal, including my confidential (Tier 2) text, to an AI model to suggest a clearer teaser. This lasts for this
sign-in only: it ends when I sign out or turn the assistant off." (`[[COPY-REVIEW]]`, D-39 item 6). The public
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

1. Signup still records a `tier2_llm_assistant` decision if a client sends one (`source = "signup"`; the guard never
   counts it and `GET /api/me/consents` no longer shows it). Refusing it in `auth/service.py` is a small change in
   security-reviewer territory.
2. docs/spec/09 says "Sync, streaming": the prototype answers in one response; streaming later.
3. No over-disclosure check of the suggested teaser against the Tier-2 text: the prompt forbids copying Tier 2 and the
   owner reviews before applying. The Haiku over-disclosure check (docs/spec/09) or a code overlap check with its
   threshold in YAML belongs with REQ-PROP-02's warn-only check.
4. No eval set covers the assistant (docs/spec/09 lists none); the injection behaviour is covered by the tests above.
5. The Tier-2 read for the assistant is audited as `proposal.assistant_suggested` (with the field names sent), not as a
   separate `proposal.tier2_read`.
6. Frontend P13-F: the editor panel (consent dialog from `GET .../assistant/consent`, "AI-drafted" and "demo fallback"
   labels, apply through the editor's PATCH), after P12-F.
7. Reviews: `reviewer` and one `security-reviewer` round (Tier-2 text to an LLM under per-session consent,
   `prototype-m2-plan.md` §5). The REQUIREMENTS row status is left to the orchestrator.
