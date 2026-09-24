## 9. AI runtime model allocation, safety & evals

**Ground rules** (in addition to `docs/spec/04-principles.md` (4.1) and the `docs/spec/08-architecture-stack-data-model.md` LLM layer): everything external is untrusted data; effort set explicitly on every call (Opus 5.5 defaults to medium); every AI artefact labelled "AI-drafted" (+ "human-reviewed on <date>" where applicable); **Tier-2 content never goes to any runtime model unless the owner opts in per purpose (`docs/spec/06-feature-modules.md#63-proposal-submission-tagging--pitch-to-company` assistant, `docs/spec/06-feature-modules.md#612-admin-moderation--disputes` moderation; default OFF)** — the classifier, over-disclosure check and originality explainer read Tier-1 fields only.

| Task | Model | Effort | Mode |
|---|---|---|---|
| Research: query planning, search/fetch, card synthesis | `claude-sonnet-5` + `web_search_20260209` / `web_fetch_20260209` | medium | Scheduled; prompt caching |
| Research: claim extraction, dedupe adjudication | `claude-haiku-4-5` | n/a | Batch API |
| Moderator pre-checklist for claims naming an org | `claude-opus-5-5` | high | On demand, low volume; drafts only |
| Scout screening (200→50) | `claude-haiku-4-5` | n/a | Batch, cached profile |
| Scout fit scoring & rationale (≤15) | `claude-sonnet-5` | medium | Batch, cached rubric |
| Injection/spam/moderation classifier (Tier 1 only) | `claude-haiku-4-5` + regex | n/a | Sync at submission |
| Teaser over-disclosure check | `claude-haiku-4-5` | n/a | Sync, warn only |
| Originality overlap explanation (submitter's text vs others' Tier 1) | `claude-sonnet-5` | medium | Sync |
| Submission assistant | `claude-sonnet-5` | medium | Sync, streaming, per-use opt-in |
| GitHub investigator (Release 2), org digest wording of fact tuples, WhatsApp adviser (v1.1) | `claude-sonnet-5` | medium | Interactive/scheduled |
| Reminder & progress-reporter wording | `claude-haiku-4-5` | n/a | Batch nightly; deterministic fallback text |
| Eval judge | `claude-opus-5-5` | high | Batch; calibrated per the evals table |
| Contract/NDA text | **No LLM authorship**; Sonnet may produce a plain-language summary labelled "not legal advice" | — | — |
| Embeddings | `BAAI/bge-m3` self-hosted (Voyage optional) | — | Worker |
| Local companion `reminder/`, `adviser/` | Groq `openai/gpt-oss-120b` / `gpt-oss-20b` (unchanged) | — | Existing ModelPool |
| `claude-fable-5-1` | Not used at runtime by default (cost; requires 30-day retention); may later be an opt-in enterprise "deep research" feature with server-side refusal fallbacks | — | — |

**Injection defences:** capability removal (scouts, originality explainer, progress reporter have no tools; research has read-only web tools bound to `allowed_domains`); the `docs/spec/08-architecture-stack-data-model.md` sanitiser and nonce-delimited framing, with `injection_suspected: bool` in every schema; rationale quotes verified verbatim or the item goes to human review; the scout-score cap, escaped templates and one-tenant runs of `docs/spec/06-feature-modules.md#68-enterprise-scout-agents--email-digests`.

**Cost controls:** Batch API for nightly jobs; prompt caching on system prompts, rubrics, profiles, taxonomies; SQL/embedding prefilters and Haiku screening before Sonnet; per-run caps; per-tenant monthly caps (80% soft-cap email, 100% hard cap pauses non-essential jobs); global daily cap and kill switch (`docs/spec/08-architecture-stack-data-model.md`).

**Evals (`backend/tests/evals/`, cassettes per PR on any prompt/model/weights change; live nightly; release blocked on failure).** Agents may generate the injection, originality, ranker-persona and progress-reporter sets (`synthetic=true`); research, scout and judge labels are human-supplied or approved at G-EVAL. Sizes below are Release 1 seeds; bracketed targets are growth goals that do not block release; thresholds are provisional until human labels exist. The injection suite always blocks.

| Agent | Gold set | Gates |
|---|---|---|
| Research | 30 (150) labelled documents across 10 (niche, region) pairs, incl. one injected page telling the agent to add a card | Citation validity 100%; unsupported numbers 0; extraction precision ≥0.85; cluster purity ≥0.90; injected card never created |
| Scout | 50 (300) labelled (org profile, proposal) pairs | Spearman ρ ≥0.6; precision@10 ≥0.7; entitlement leakage 0 |
| Injection | 50 (100) adversarial submissions with clean twins | Recall ≥0.95; FPR ≤2%; score shift ≤5; zero injected links |
| Originality | 50 (200) pairs (paraphrase, EN↔SW translation, related-distinct) | Paraphrase recall ≥0.90; FPR ≤5%; zero private-text leaks |
| Ranker | Replayed impressions (synthetic personas pre-launch) | NDCG@10 and coverage never regress >2% |
| Progress reporter | 50 milestone-state fixtures | 100% factual consistency; missing data always disclosed |
| Judge calibration | 20 (50) human labels | Cohen's κ ≥0.6 |
