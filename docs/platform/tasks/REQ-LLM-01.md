# REQ-LLM-01

- Task: T2.2 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-ai
- Files owned: `bridge/llm/` (except `models.py`, owned by T2.1), `backend/ai/models.yaml`, `backend/tests/unit/llm/`, `backend/tests/fixtures/cassettes/`
- Depends on: Parallel with T2.1; the SQL ledger store after T2.1 merges.

## Scope

`LLMClient.complete(task, messages, schema, tools=None, effort=None, cache_breakpoints=None) -> Result{parsed, stop_reason, usage, citations}` and `batch_submit/poll`; `AnthropicAdapter` on the official SDK (never reached in tests: the egress guard plus fakes); `ai/models.yaml` maps task → model, effort, max_tokens, batchable, confidential (default true) and purpose; no model id elsewhere. Structured output via JSON schema or `tool_choice: auto` + `strict: true`, never forced. Refusal → log + human queue + at most one retry on the next allowed model; `max_tokens` → one retry at 2×; schema failure → one retry with the error, then dead-letter. Ledger `llm_calls` for every call (sanitised inputs); pre-call budget check: per-tenant monthly cap from `plans.limits.llm_monthly_cap_usd`, a global daily cap (`LLM_GLOBAL_DAILY_CAP_USD`), `LLM_KILL_SWITCH=1`. Sanitiser (strip HTML and markdown links, zero-width and bidi controls, base64 runs >200 chars, length caps) and `<submission nonce=…>` framing; `injection_suspected` in every schema. Tier-2 guard: a task whose purpose needs a consent refuses Tier-2 input without a live `tier2_llm_assistant`/`tier2_llm_moderation` consent. Fakes: `FakeLLMClient` and synthetic cassettes (D-18: no paid calls; cassettes are hand-written and marked `synthetic: true`).

## Acceptance criteria and tests

AC-SEC-6 (`unit/llm/test_no_tier2_in_llm_calls.py`), unit tests for retries, caps, the kill switch and the sanitiser. AC-SCOUT-4 is Phase 4.
