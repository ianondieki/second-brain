# REQ-LLM-01

- Task: T2.2 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-ai
- Files owned: `bridge/llm/` (except `models.py`, owned by T2.1), `backend/ai/models.yaml`, `backend/tests/unit/llm/`, `backend/tests/fixtures/cassettes/`
- Depends on: Parallel with T2.1; the SQL ledger store after T2.1 merges.

## Scope

`LLMClient.complete(task, messages, schema, tools=None, effort=None, cache_breakpoints=None) -> Result{parsed, stop_reason, usage, citations}` and `batch_submit/poll`; `AnthropicAdapter` on the official SDK (never reached in tests: the egress guard plus fakes); `ai/models.yaml` maps task → model, effort, max_tokens, batchable, confidential (default true) and purpose; no model id elsewhere. Structured output via JSON schema or `tool_choice: auto` + `strict: true`, never forced. Refusal → log + human queue + at most one retry on the next allowed model; `max_tokens` → one retry at 2×; schema failure → one retry with the error, then dead-letter. Ledger `llm_calls` for every call (sanitised inputs); pre-call budget check: per-tenant monthly cap from `plans.limits.llm_monthly_cap_usd`, a global daily cap (`LLM_GLOBAL_DAILY_CAP_USD`), `LLM_KILL_SWITCH=1`. Sanitiser (strip HTML and markdown links, zero-width and bidi controls, base64 runs >200 chars, length caps) and `<submission nonce=…>` framing; `injection_suspected` in every schema. Tier-2 guard: a task whose purpose needs a consent refuses Tier-2 input without a live `tier2_llm_assistant`/`tier2_llm_moderation` consent. Fakes: `FakeLLMClient` and synthetic cassettes (D-18: no paid calls; cassettes are hand-written and marked `synthetic: true`).

## Acceptance criteria and tests

AC-SEC-6 (`unit/llm/test_no_tier2_in_llm_calls.py`; against the stored `llm_calls` rows in `integration/llm/test_sql_caps_and_tier2.py`), unit tests for retries, caps, the kill switch and the sanitiser; the SQL ledger, tenant isolation, staff-only `inputs` and the caps read from SQL in `integration/llm/`. AC-SCOUT-4 is Phase 4.

## Notes and deferrals (T2.2 review)

- **ModelPool and TokenPacer: deferred to T4.3** (scout pipeline, the first high-volume caller). The companion's `ModelPool` rotates across several models, which the one-model-per-task allocation of `docs/spec/09` does not allow (refusal fallbacks are D-29); its cooldown and the `TokenPacer` per-minute pacing are ported with T4.3, when concurrent batch and synchronous scout calls first meet provider rate limits. Until then the SDK's own retries (`transport.max_retries`) handle 429s.
- **Citations and structured outputs:** the task registry key `json_schema_format` (default `true`) lets a task drop `output_config.format` and carry the schema in the system prompt instead, for citation calls (Phase 5 research). Whether citations and native JSON-schema output can be combined, and how each behaves on the registered models, **must be verified against the current provider documentation before any live call** (D-18: no paid calls until then); the cassettes are synthetic and prove only our parsing.
- **SQL ledger (`bridge/llm/sql_ledger.py`) and the default wiring (`bridge/llm/deps.py`).** `LLMDep` gives each request `LLMService` over `SqlLedger`, `EntitlementsCaps` and `SessionConsentChecker`, all as the request's bound tenant; jobs call `sql_service` after `bind_tenant`; `FakeLLMClient` stays for unit tests. Ledger rows are committed in their own transaction (they survive the request's rollback; the ledger holds a second pooled connection for a moment). `check_subject` refuses, before anything is sent, a call whose user or organisation the bound tenant could not record or sum, and a call with no subject from a session bound to a tenant (a platform call runs unbound). The per-session `tier2_llm_assistant` opt-in also needs the call's session to be a live login session of the owner (`bridge.auth.sessions.is_live`). Blocked rows name the task's model (`llm_calls.model` is NOT NULL); `purpose` is stored only for consent-covered tasks. The table's CHECKs (T2.1 round 4: `cost_usd` 0..100, tokens and latency ≥ 0) are met by **clamping** with an error log (`llm.ledger_clamped`), never by refusing, since the row follows a paid attempt. `llm_calls` has no column for the entry's `attempt`, `error` or non-confidential `output`: they go to the log, the exception and the dead-letter queue only (every task is confidential today); a later revision may add them.
- **Batch reservations and settle-once (review round 1, M2 and m3; revision 0002 item G).** Right after `batch_create`, `batch_submit` writes one `batch_reserved` row per item (`batch_id`, `custom_id`, the item's batch-price estimate, clamped into the row CHECK) in one transaction, so the tenant's monthly sum and `app_llm_spend_usd()` (both read the `llm_spend` view) count a batch in flight: with room for about 1.5 batches the second submission is refused until the first settles. If writing the reservations fails, `llm.batch_unreserved` names the batch for an operator. `batch_poll` settles each item once (through `app_llm_settle_batch_item`, `ON CONFLICT DO NOTHING` on the partial unique index; `false` = settled before): only newly settled items are dead-lettered, queued for a human (refusals) and fed to the soft cap, whose spend is read after settling; a repeat poll returns every outcome again (a repeated failure carries no dead letter id). Settlements carry the handle's organisation and user, which are the reservation's. An item missing from the provider's results is **not** settled (a change from round 1's zero-cost `provider_error` row): its reservation keeps counting, since the results may have been cut short and the item billed, and every poll reports it as a transient `LLMProviderError` until one finds it; a resubmitted item is counted twice until the month ends (fail closed). `InMemoryLedger` keeps the same rules, including the tenant rules below. Tests: `unit/llm/test_batch.py`, `unit/llm/test_ledger_and_sinks.py`, `integration/llm/test_sql_batches.py`.
- **Batch tenant and ownership (schema v2 rounds 5 and 6, merged here).** A batch is the tenant's (organisation and user) of its **earliest reservation** (`created_at` is set by the database, so a backdated row cannot take a batch). `batch_poll` refuses a handle naming another tenant's batch, or one with no reservation, with `LLMBatchNotOwned` (`llm_batch_not_owned`, logged as `llm.batch_not_owned`) **before** reading the batch's state or results: `SqlLedger.batch_owned` asks `app_llm_batch_owned()` and, for a tenant's handle, that a reservation names exactly the handle's organisation and user (so the soft cap and the outcome budget read the subject the settlements are written for). Every settlement goes through `app_llm_settle_batch_item()`, which writes it with the batch tenant's organisation and user for that tenant or the platform job (nothing bound) and refuses anybody else (`insufficient_privilege`, raised as `LLMBatchNotOwned`); `false` = settled before. Another tenant's later reservation of one of the batch's items coexists, counts against that tenant only (it never settles: fail closed) and takes nothing. Tests: `unit/llm/test_batch.py`, `unit/llm/test_ledger_and_sinks.py`, `integration/llm/test_sql_batches.py` (`test_another_tenant_cannot_settle_or_cancel_an_items_reservation`, `test_a_later_reservation_of_another_tenant_does_not_take_the_batch`, `test_a_platform_job_settles_an_items_row_with_the_batch_tenant`, and `test_an_item_missing_from_the_results_keeps_its_reservation`, which polls twice without the item and then finds it). **Open for Phase 4:** the definer lets the platform job settle a batch whose user has since left the organisation, but `batch_poll` checks the handle's subject against the bound session first (`check_subject`), so a job cannot yet poll such a handle; the scout pipeline (T4.x) decides how a job polls a tenant's batch.
- **Open, carried to Phase 4 (scouts, T4.x):** the `llm_calls` insert policy lets a row name an organisation only when the bound user is an active member of it, so an organisation job must bind a member (or a revision must add a definer for system rows of an organisation). Dead letters, the human refusal queue and the soft-cap listener are still the logging in-memory sinks (their tables and the soft-cap email are T2.3 and Phase 4).
- **Carries to T2.9 (submission assistant, REQ-PROP-05):**
  - The settings API still offers `tier2_llm_assistant`: `GET /api/me/consents` lists it and `PUT /api/me/consents` records it with `source = "settings"`, which the guard never counts; after a per-session grant, `GET` shows it as granted although it is live only in that session. T2.9 removes it from the settings API and page (or shows it as "this session only") and records the opt-in only through `grant_session_consent` from the assistant.
  - The consent wording (`config/consents.yaml`: "Let the writing assistant read my confidential (Tier 2) text to suggest improvements.") does not say the opt-in lasts one login session and ends at sign-out; new wording is a new text version `[[COPY-REVIEW]]`.
  - An audit event on grant and on withdrawal: `grant_session_consent`/`withdraw_session_consent` only add the consent row; the T2.9 endpoint checks the text version shown, writes the audit event (as `consent.changed` does in the settings route) and commits.

## Revision 0004: platform-wide request count (db-migrations, D-37; 2026-09-29)

Branch `feat/REQ-LLM-01-calls-since`, `backend/alembic/versions/20260929_0004_llm_calls_since.py` (Revises `0003`; additive: one function, nothing of 0001 to 0003 changed; the downgrade drops it).

- `app_llm_calls_since(p_model varchar, p_since timestamptz) RETURNS bigint`: SECURITY DEFINER, `plpgsql STABLE`, `search_path = pg_catalog, public, pg_temp`, fully qualified names, EXECUTE revoked from PUBLIC and granted to `bridge_app` only. It counts the `llm_calls` rows of `p_model` with `created_at >= p_since` that reached a provider, for every tenant and the platform jobs. It leaves out every `blocked_*` status (by prefix, so a `blocked_*` status added later is left out too) and `batch_reserved`. A settled batch item counts once, and a status it does not know counts, so a cap refuses early and never late. It returns the count only, never a row, as `app_llm_spend_usd` returns the spend only. A NULL model or start raises `invalid_parameter_value`, because it would count nothing and open the cap. Today the excluded set equals P7's `ledger.NOT_SENT` (`blocked_kill_switch`, `blocked_budget`, `blocked_tier2`, `blocked_consent`, `batch_reserved`); the behaviour test pins it against `CallStatus`.
- Tests: `integration/test_migrations.py` (the function catalog: definer, pinned `search_path`, EXECUTE exactly `bridge_app`; the round trip now also checks that 0004 leaves 0003 exactly as it found it; the pg_temp shadowing check calls it). `integration/test_privileges.py::test_llm_calls_since_counts_every_tenants_sent_calls` covers every `CallStatus` for a user, an organisation member and the platform job. It counts all of them for any caller (a user, a member, an outsider with no rows, nothing bound), although the outsider reads none of the rows and a user reads only their own. It leaves out the blocked, reserved, other-model and earlier rows, starts the window inclusively and refuses NULLs. Mutation proofs (each breaks one rule of the revision, runs the behaviour and catalog tests, and restores the file): no `blocked_*` exclusion, no `batch_reserved` exclusion, SECURITY INVOKER, an exclusive start, EXECUTE left to PUBLIC, no NULL refusal, and the four named blocked statuses instead of the prefix. Every one is red.
- For P7 (`feat/REQ-LLM-01-providers`, not edited here): after this merges, `SqlLedger.calls_since` (`backend/src/bridge/llm/sql_ledger.py:236-246` at the branch's head) selects `func.app_llm_calls_since(model, since)` instead of counting the rows the bound tenant may read. It returns an `int` whatever the binding. The docstring's "open" note and the card's P7 open item 1 then close. `InMemoryLedger.calls_since` keeps `NOT_SENT`.
- Open: the cap reads the count before the attempt and the row is written after it, so concurrent calls can each pass the check and overshoot the slot's quota by the calls in flight (P7's rule, not the function's). The count scans the window through `ix_llm_calls_created_at` (all models); an index on `(model, created_at)` can follow if the ledger grows.

## Review round 2 (2026-09-29, prototype track): reviewer PASS; MINOR follow-ups (not built, PLAN §8)

1. `sql_ledger.py:208` — the exact-subject half of `batch_owned` has no test (a handle naming the owner without its organisation). Add `test_a_handle_naming_the_owner_without_its_organisation_is_refused` to `tests/integration/llm/test_sql_batches.py`.
2. `budget.py:174` — soft-cap crossings are judged on a snapshot that includes in-flight batch reservations and `batch_submit` never calls `after()`, so a crossing can be missed. Judge the crossing on spend without reservations, or re-check when reservations are released (before the Phase 4 soft-cap email).
3. `client.py:630` — if writing the reservations fails after `batch_create`, the provider batch runs unpolled and uncounted. Cancel the batch through the adapter (or retry the reservation) and add a unit test.
4. `client.py:700` — the settlement commits before the dead-letter/human-queue event; a crash in between loses it. When T2.3 turns the sinks into tables, write both in one transaction or make the sinks idempotent on `(batch_id, custom_id)`.

## Security review (2026-09-29): MINOR follow-ups

The review's one MAJOR is fixed: the sanitiser cut its output only and was quadratic on unclosed `<script>`/`<style>` openers (1 MB took 541 s, synchronously, before the budget check). `strip_blocks` now scans linearly (the old regex is its test oracle), and `sanitise` cuts its input to `sanitiser.max_input_ratio` (8, `ai/models.yaml`) times the field's cap before any pass, reported as `truncated`; timing regressions in `unit/llm/test_sanitiser.py` (`12adf27` red, `6e592ae` fix). MINORs:

1. **Done (`526a0eb` red, `af0d846` fix).** `auth/sessions.py` `is_live` requires `sessions.mfa_pending = false`, so the per-session Tier-2 opt-in is never live in a login waiting for its second factor (`integration/llm/test_session_consent.py`).
2. `logging.py:16-19` — `_redact` substring-matches `token`, so `input_tokens`, `output_tokens` and `cache_read_tokens` log as `[redacted]`. Match whole key names (or rename the logged keys) and add a test.
3. `budget.py:150` and `errors.py:79` — a global-scope `LLMBudgetExceeded` carries the platform's spend and cap in `str(exc)`. The API mapping must send a fixed message for scope `global` (never the platform's figures) when the first route maps LLM errors.
4. `guard.py:90-96` — cross-owner consent reads fail closed under RLS (a moderator's session cannot read the author's `tier2_llm_moderation` consent). Phase 4 moderation needs an `app_has_consent` SECURITY DEFINER (db-migrations), never a widened SELECT policy.
5. `registry.py:169` and `anthropic_adapter.py:76-93` — server-tool fees (web search, web fetch) are not priced into estimates or costs, and `check_tools` does not require `allowed_domains`. Fix both before any task in `ai/models.yaml` lists a web tool.
6. **Done (`526a0eb` red, `af0d846` fix).** `deps.py` `get_llm` depends on `CurrentSession`: 401 without a signed-in session (or `mfa_required`), and the database session is bound to the user before the service is built, so a request never makes an unbound platform call (`unit/llm/test_deps.py`).
7. `client.py:538-601` — `batch_submit` accepts any number of items; add `max_batch_items` to `ai/models.yaml` (below the provider's limit) and refuse larger batches before anything is sent.

## P7 providers (prototype track, D-37; 2026-09-29)

Branch `feat/REQ-LLM-01-providers` (impl-backend, xhigh). Local prototype runs may use the owner's free
OpenAI-compatible providers or Anthropic; tests, `make check` and CI use fakes, respx and synthetic cassettes only.

**New environment variables (names only; documented in `backend/.env.example`):**

- `LLM_PROVIDER` (`fake` | `free` | `anthropic`; empty: `free` in dev when a complete slot is set, else `fake`; always
  `fake` under `APP_ENV=test`; `anthropic` in staging and production, which refuse `free` and (production) `fake`). The
  test conftest blanks it and every `LLM_FREE_*` variable, so a shell or `backend/.env` never leaks into tests.
- `LLM_PROTOTYPE_TOTAL_CAP_USD` (`.env.example` 5.00; unset: USD 5 in dev and test, no total in staging and production
  unless set; `Settings.llm_total_cap_usd`).
- `LLM_FREE_1_BASE_URL`, `LLM_FREE_1_API_KEY`, `LLM_FREE_1_MODEL`, `LLM_FREE_1_DAILY_REQUESTS`,
  `LLM_FREE_1_RESPONSE_FORMAT`
- `LLM_FREE_2_BASE_URL`, `LLM_FREE_2_API_KEY`, `LLM_FREE_2_MODEL`, `LLM_FREE_2_DAILY_REQUESTS`,
  `LLM_FREE_2_RESPONSE_FORMAT`
- `LLM_FREE_3_BASE_URL`, `LLM_FREE_3_API_KEY`, `LLM_FREE_3_MODEL`, `LLM_FREE_3_DAILY_REQUESTS`,
  `LLM_FREE_3_RESPONSE_FORMAT`

Existing variables it relies on: `ANTHROPIC_API_KEY`, `LLM_KILL_SWITCH`, `LLM_GLOBAL_DAILY_CAP_USD` (1.00 in
`.env.example`), `LLM_MODELS_FILE`.

**Design.**

- Settings (`bridge/config.py`): a slot's base URL, key, model and daily requests are set together or not at all (half a
  slot stops start-up); `RESPONSE_FORMAT` is optional (`json_object` default, `json_schema`, `none`). Base URLs are https
  (plain http on loopback only, for a local model server) without credentials, query or fragment; the model id is 1-74
  characters. Staging and production refuse `LLM_PROVIDER=free` and every `LLM_FREE_*` value, with no override (D-37:
  free providers are for local runs; the "unless explicitly allowed" option was not built). `llm_demo_fallback` is true
  in dev and test only.
- Registry (`ai/models.yaml`, `registry.py`): the Anthropic prices verified on 2026-09-29
  (`research/anthropic-prices-2026-09.md`): `pricing_status: verified`, `pricing_verified_on`, `pricing_source`
  (strictly parsed); Sonnet 5 2/10, Haiku 4.5 1/5, Opus 5.5 4/20 USD per MTok with their cache rates, batch 0.5. Each task
  lists `free_slots` (all four: `[1, 2, 3]`; default none). `Registry.for_free_slot` derives a slot's registry: one
  zero-priced model `free<N>:<model>` (the `llm_calls.model` of its rows) with the slot's `daily_requests`, the tasks
  listing the slot without effort, fallback or tools, `json_schema_format: false` (schema in the prompt), `max_tokens`
  lowered to `free_providers.max_output_tokens` (8192).
- `OpenAICompatibleAdapter` (`openai_adapter.py`, plain httpx): Chat Completions with the bearer key; finish reasons
  mapped (`stop`, `length`, `content_filter`/`refusal`, tool calls; anything else `unknown`, never provider text); usage
  bounded; every failure an `LLMProviderError` naming the slot and status only, `from None` (no provider body, no key);
  redirects never followed; replies over 2 MB, malformed or nested past the parser's limit refused. No retries (one
  attempt, one request, one ledger row). No batch API.
- Caps (`budget.py`): before every attempt, a free slot refuses once today's rows of its model that reached the provider
  hit its cap (`LLMRequestCapReached`, a `blocked_budget` row; retries count), via `LedgerStore.calls_since`: platform-wide
  in SQL (`app_llm_calls_since`, revision 0004; every tenant's rows, the number only), `NOT_SENT` in memory.
  The prototype total (`Settings.llm_total_cap_usd`) refuses once the ledger's lifetime spend (`app_llm_spend_usd`, every
  tenant; only Anthropic costs money) plus the estimate would pass it (scope `total`). The spend caps apply to attempts
  on a paid model (`ModelSpec.paid`; every `ai/models.yaml` model must have positive input and output prices; a check
  without a model counts as paid), so an overrun (calls in flight) never blocks a zero-priced free slot.
- Data rule (`demo_data.py`, in the free slot's `LLMService` after the consent guard, before anything is sanitised,
  budgeted or sent): another account's Tier-2 text is refused (`Tier2DemoOnly`, a `Tier2NotAllowed`: `blocked_tier2`
  row); a call with no user, a non-demo user, a non-demo field owner or an ownerless field not marked public platform
  data (`InputField.public`, Tier 1 only, e.g. saved research excerpts) raises `NotDemoData` (unrecorded) and is answered
  by the fake. `SqlDemoAccounts` reads `users.demo_account` in its own session as the caller's tenant; a missing column,
  row or privilege reads as "not a demo account". An organisation's call is judged by its bound member. The Anthropic
  service has no rule (T2.2 rules unchanged); `LLMService` refuses a free adapter (`requires_data_rule`) without it.
- Demo fallback (`demo_fallback.py`): the output schema's own `demo_fallback()` classmethod, a fixed placeholder its
  author chose as the safe answer (a classifier holds; text fields may use `DEMO_TEXT` `[[COPY-REVIEW]]`), which must be
  of the schema and set `injection_suspected=True`; the layer invents nothing, and on local runs the router refuses a
  schema without one (`LLMConfigError`) before routing. Deterministic and reading no input. `Result.demo_fallback` and
  `Result.fallback_reason`; `DemoFallbackFlag` is the base for API responses that return LLM output.
- Routing (`routing.py`, `RoutedLLMClient`; `deps.routed_client` is `LLMDep`; `app.state.llm_runtime`): `fake` answers
  every call with the fake; `free` takes the first slot the task lists that is configured and under today's cap;
  `anthropic` uses the T2.2 service only with verified prices. In dev and test a missing slot or key, unverified prices,
  non-demo data, a hit cap, the kill switch, an unavailable provider, a provider error or a failed call (refused,
  truncated, schema failure, unsupported stop) answers with the schema's placeholder, flagged, logged as
  `llm.demo_fallback`. Rule refusals are never faked (consent guard, `Tier2DemoOnly` also when every slot is capped,
  `LLMConfigError`, `LLMBatchNotOwned`); the fallback runs the subject check and the consent guard itself where the
  service did not (the fake, a route with no provider, the kill switch) and records its refusals (`blocked_tier2`,
  `blocked_consent`). In staging and production errors propagate as in T2.2; the fake provider and unverified prices
  raise `LLMUnavailable`. The free adapter ignores proxy and netrc settings from the environment, maps `eos` to
  `end_turn` and strips one surrounding code fence; every adapter's client is closed in the app's lifespan.
- Batches: free providers and the fake have no batch API. The simplest safe option: a batch outside the Anthropic route
  (or its fallback) gets a `demo_fallback` handle holding only the custom ids (`BatchHandle.demo_fallback`,
  `fallback_reason`), checked as a real batch (batchable, ids, consent guard, D-37 Tier-2 refusal); polling it returns the
  fake answer per item, statelessly (restart-safe, reads nothing). A real batch handle is polled only with
  `LLM_PROVIDER=anthropic` (`LLMUnavailable` otherwise). Callers that want a free model's answer call `complete` per
  item. No task is batchable today.

**Tests.** `unit/llm/test_provider_settings.py` (slot validation, half slots, URLs, staging and production refuse free,
`.env.example` names), `unit/llm/test_openai_adapter.py` (wire and reply mapping, errors, key hiding, redirects, size and
nesting bounds), `unit/llm/test_request_caps.py`, `unit/llm/test_budget.py` (request cap, prototype total, zero-cost
attempts), `unit/llm/test_registry.py` (verified prices, `free_slots`, `for_free_slot`), `unit/llm/test_demo_data.py`,
`unit/llm/test_demo_fallback.py`, `unit/llm/test_routing.py` (fake and free routes, non-demo data never sent, Tier-2
refusals, slot order and caps, every failure path labelled, kill switch, no fallback outside local runs),
`unit/llm/test_routing_anthropic_and_batches.py` (price gate, missing key, daily and total caps, batches),
`unit/llm/test_deps.py`, `integration/llm/test_sql_request_caps.py`, `integration/llm/test_demo_accounts.py`,
`integration/llm/test_routed_client.py` (a real account never reaches the slot; a seeded demo account does, with the
schema-v3 column added in a rolled-back transaction).

**Open (for the orchestrator).**

1. **Platform-wide request count: done.** Revision 0004 (`app_llm_calls_since(p_model, p_since)`, SECURITY DEFINER,
   EXECUTE `bridge_app`) is merged; `SqlLedger.calls_since` calls it, so every account shares a slot's daily cap
   (`integration/llm/test_sql_request_caps.py::test_two_demo_accounts_share_a_slots_daily_cap`,
   `::test_a_slots_cap_counts_every_accounts_calls`). `integration/test_privileges.py` takes `NOT_SENT` from
   `bridge.llm.ledger`, so the SQL rule and the in-memory one cannot drift apart unnoticed (0004 review MINOR).
2. **Schema v3** is merged (`users.demo_account`); a free slot serves only accounts `seed --demo` marks.
3. **API plumbing.** No route returns LLM output yet. P6 (EM7 wording), P10 (scout summary) and P13 (assistant) must
   extend `DemoFallbackFlag` and set it from `Result.demo_fallback`; the UI label is a frontend task.
4. **Every output schema used on a local run needs a `demo_fallback()`** placeholder (the safe answer, e.g. "hold",
   with `injection_suspected=True`), and callers that decide on an output treat `demo_fallback` as "no verdict".
5. The prototype total counts this database's ledger: resetting the demo database resets it.
6. Model ids (research note): Sonnet 5 is legacy since Sonnet 5.5 (retirement not before 2027-06-30); Haiku 4.5 retires
   not before 2026-10-15. The `docs/spec/09` allocation names both, so they are kept; moving to Sonnet 5.5 is a spec
   change for the human.
7. The free adapter does not retry a 429 (the call falls back); `ModelPool`/`TokenPacer` stay with T4.3.
8. PLAN §8: one `security-reviewer` round on the new LLM adapter, then BLOCKER/MAJOR only (done: see below).

### P7 review round 1 (reviewer PASS with MINORs; security-reviewer CHANGES_REQUIRED, 2 MAJOR), fixed 2026-09-29

- **MAJOR 1** (`083549e`): an ownerless field was treated as demo data, so a demo caller could send another user's
  Tier-1 text to a free provider. An ownerless field is now `NotDemoData` unless marked `public` (Tier 1 only).
  `unit/llm/test_routing.py::test_an_ownerless_field_never_reaches_a_free_provider` (respx sees no call).
- **MAJOR 2** (`0adf393`): the generic fallback fabricated a permissive verdict (first enum member,
  `injection_suspected=False`). The layer now invents nothing: the schema's own `demo_fallback()` (with
  `injection_suspected=True`) or `LLMConfigError`, checked before routing on local runs. THREAT_MODEL refusal row updated.
- **MINORs done:** production refuses `LLM_PROVIDER=fake`; the USD 5 total is dev and test only unless set (`fb490a5`);
  `trust_env=False`, adapters closed in the lifespan, `eos`, one code fence stripped (`65ff167`); the router's
  refusals recorded, real batch handles polled on Anthropic only, a `capture_logs` test for `llm.demo_fallback` (N9)
  (`1a1bd74`); `paid` judged on the model with positive YAML prices, a free adapter refused without the data rule,
  `calls_since` pinned to its model for one tenant (M41) (`139de1b`). Revision 0004 merged and `calls_since` switched to
  it (platform-wide); `.env.example` says so.
- **Follow-ups (not built):**
  1. Extend `test_no_model_ids_in_code` to free-provider model families and hosts (for example `llama-`, `gemini-`,
     `gpt-`, `mistral`, `qwen`, and provider hostnames) so they stay in `.env` only.
  2. A cap can be overshot by the calls in flight (each attempt checks before sending; concurrent attempts may all
     pass): bounded by the calls in flight across the platform; revisit with a row lock or an advisory lock per slot.
  3. Commit sizes: `5412dbb` (router and its tests, about 690 lines) exceeded the ~300-line guideline; later rounds split
     tests from code.

## P7 reviews (2026-09-29): reviewer PASS; security-reviewer PASS round 2; MINOR follow-ups (not built)

1. `InputField(public=True)` is an explicit opt-out of the demo-data rule: the reviewers of P10/P11/P13 check it is used only for repo-saved public excerpts, never for a user's text.
2. Each schema's `demo_fallback()` placeholder must be the non-granting answer (the layer enforces the type and `injection_suspected=True`, not the enum value); callers keep treating `demo_fallback` as "no verdict".
3. `.env.example`-only free-provider model ids and hosts: extend `test_no_model_ids_in_code` to common OpenAI-compatible model families and provider hosts.
4. Concurrent calls can overshoot a slot's cap (check before send); a per-slot advisory lock or row lock later.
5. Commit sizes over ~300 lines on this branch (no rewrite).
