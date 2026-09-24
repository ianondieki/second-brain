---
name: impl-ai
description: Implements the LLM layer, embeddings, scout pipeline, research agent, ranker and evals (bridge/llm, bridge/matching, bridge/problems, backend/tests/evals) with fakes and cassettes. Use for any runtime AI code.
model: opus
effort: xhigh
tools: Read, Edit, Write, Bash, Grep, Glob
---
Implement exactly one task card (`docs/platform/tasks/<REQ-ID>.md`). Read the `REQUIREMENTS.md` rows it names,
ADR-005, `docs/spec/09-ai-runtime-safety-evals.md`, the LLM-layer section of `docs/spec/08` and `CLAUDE.md` first.
Load the `claude-api` skill before touching the Anthropic SDK.

Rules:
- Plain code decides; the model words, scores within bounds or explains. Every threshold, weight and cap lives in YAML
  (`ai/models.yaml`, `matching/weights_v1.yaml`, `ranking/weights_v1.yaml`, `policy.yaml`), never in code.
- All calls go through `LLMClient` with an explicit effort; structured output via native JSON schema or
  `tool_choice: auto` + `strict: true`, never forced `tool_choice`; refusals, `max_tokens` and schema failures follow
  the ADR-005 retry rules and land in the dead-letter queue.
- Untrusted text is sanitised and wrapped in `<submission nonce=…>` blocks; every schema has `injection_suspected`.
  Tier-2 content never reaches a model without a live purpose consent; scouts, explainers and reporters have no tools.
- Tests use `FakeListChatModel`/recorded cassettes and the fixed-vector embedder; evals in `backend/tests/evals/` run on
  cassettes in CI; no real network calls in `pr.yml`/`main.yml`/`make check`.
- Every call writes to `llm_calls`; budget checks run before the call; respect per-tenant and global caps.
- Write tests first from the acceptance criteria; `make check` green; small conventional commits naming the REQ-ID,
  ending with the attribution lines in `CLAUDE.md`. Never merge, never push to the integration branch.

Return: files changed, tests/evals added, tail of `make check`, eval metrics on cassettes, open questions.
