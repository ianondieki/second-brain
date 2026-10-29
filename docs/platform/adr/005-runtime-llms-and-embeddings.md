# ADR-005: Runtime LLMs and embeddings

- Status: PROPOSED (human may veto at G0)
- Date: 2026-09-24
- Spec: docs/spec/08-architecture-stack-data-model.md (LLM layer, Embeddings), docs/spec/09-ai-runtime-safety-evals.md, docs/spec/04-principles.md (4.1, 4.5)
- Related: ADR-002 (consents), THREAT_MODEL.md (Prompt injection, Idea leakage), GATES.md (G-EVAL)

## Context

Runtime AI is used to word, score within bounds and explain; code decides. The local companion uses Groq. The
platform needs batchable, cacheable, citable calls with a hard budget, and embeddings that handle Swahili.
Anthropic has no embeddings endpoint.

## Decision

1. **One LLM layer** `bridge/llm`: `LLMClient.complete(task, messages, schema, tools=None, effort=None, cache_breakpoints=None) -> Result{parsed, stop_reason, usage, citations}` plus `batch_submit/poll`. Single `AnthropicAdapter` on the official SDK (Batches, prompt caching, citations, server tools). No Groq in the backend. `ai/models.yaml` maps task → model, effort, max_tokens, batchable, confidential (default `confidential: true`); no model ID is hard-coded elsewhere.
2. **Model allocation** exactly as the `docs/spec/09` table: Sonnet 5 for research planning/synthesis, scout fit scoring, originality explanation, submission assistant, investigator (R2) and adviser (v1.1); Haiku 4.5 for claim extraction, scout screening, injection/spam/over-disclosure classifiers and reminder wording; Opus 5.5 (effort high) for the moderator pre-checklist and the eval judge; Fable 5.1 not used at runtime by default. Effort is set explicitly on every call.
3. **Structured output**: native JSON schema or `tool_choice: auto` with `strict: true`; never forced `tool_choice`. `stop_reason == "refusal"` → log, human queue, at most one retry on the next allowed model; `max_tokens` → one retry at 2×; schema failure → one retry with the error, then dead-letter queue. `ModelPool` cooldowns and `TokenPacer` ported from the companion.
4. **Data rules**: Tier-2 content never reaches a runtime model unless the owner holds a live purpose-specific consent (`tier2_llm_assistant` per session, `tier2_llm_moderation` persistent); classifiers, over-disclosure check and originality explainer read Tier-1 only (AC-SEC-6). No training on idea content; untrusted text is sanitised (strip HTML/markdown links, zero-width and bidi controls, base64 runs >200 chars, length caps) and wrapped in `<submission nonce=…>` blocks; every schema carries `injection_suspected: bool`.
5. **Cost controls**: every call writes `llm_calls(tenant, task, model, tokens incl. cached, cost_usd, latency, status, trace_id)`; pre-call budget check against `plans.limits.llm_monthly_cap_usd` (80% soft-cap email, 100% hard cap pauses non-essential jobs and degrades scouts to embedding-only), a global daily cap and `LLM_KILL_SWITCH=1`. Batch API for nightly jobs; prompt caching on system prompts, rubrics, profiles and taxonomies.
6. **Embeddings**: self-hosted `BAAI/bge-m3` (1024-dim, multilingual incl. Swahili) via sentence-transformers fp16/int8 on the worker; `VoyageAdapter` optional behind a DPA flag; fixed-vector fake in CI; `embed_model`/`embed_version` stored per row; model change triggers a re-embed job.
7. **Evals**: `backend/tests/evals/` with cassettes per PR on any prompt/model/weights change; live nightly job ≤USD 5 (separate key, `api.anthropic.com` allowlisted only for that job). Injection suite always blocks release. Human labels for research, scout, ranker and judge sets arrive at G-EVAL.

## Alternatives considered

- Groq (as in the companion): rejected for the platform; no Batches/caching/citations, and model retirements already broke the legacy stack (R-HYG-03).
- Multi-provider routing: rejected in Release 1; one adapter keeps the safety surface small; the interface allows a second adapter later.
- Hosted embeddings (Voyage) as default: rejected; adds a sub-processor for proposal text; kept optional behind a DPA flag.
- Fable 5.1 at runtime: rejected by default on cost and retention terms; possible later opt-in "deep research" feature.

## Consequences

- Runtime cost is observable per tenant and per task from day one; G0 sets the per-phase build budget, `plans.yaml` the runtime caps.
- Model changes are YAML edits plus a re-run of the cassette evals; a new model needs a nightly eval pass before promotion.
- The worker image carries the bge-m3 weights; the `t4g.large` sizing in ADR-007 assumes int8 on CPU with a bounded embedding job; measured in Phase 2 and revisited if the p95 budget is missed.
