# REQ-EMB-01

- Task: T2.2 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-ai
- Files owned: `bridge/llm/embeddings.py`, `bridge/jobs/reembed.py`
- Depends on: Parallel with T2.1.

## Scope

`Embedder` interface: `FakeEmbedder` (fixed, deterministic 1024-dim unit vectors derived from the text; used in tests and CI), `BgeM3Embedder` (sentence-transformers, fp16/int8, lazy optional import; the model is **not downloaded** in this phase: ask the human first, Docker has 4 GB), `VoyageAdapter` stub behind a DPA flag (off). `EMBEDDER=fake|bge-m3` setting; production fails closed without a real embedder. `embed_model`/`embed_version` written per row; the `reembed` job re-embeds rows whose model or version differ.

## Acceptance criteria and tests

`unit/llm/test_embeddings_fake.py`; AC-PROP-4 uses the fake.
