# Section 2 — Knowledge Base Ontology & Lightweight Scanning Frontmatter

The whole system avoids a local vector database. Instead, **structured YAML
frontmatter** turns every note into a row of cheap, regex-parsable metadata.
n8n reads the flat key/value pairs as plain strings (see the parser in the
`Filter Stale Projects` Code node), so staleness detection costs ~0 RAM.

## Design rules
1. **Flat scalars only.** No nested maps, no multi-line YAML. Every value is a
   string, number, ISO date, or a single-level `[a, b]` list.
2. **`type` is the discriminator** — `project` or `learning`. The pipeline
   filters on it first.
3. **`last_actionable_date` is the heartbeat.** It is the one field staleness
   is computed against. Update it whenever you genuinely move a note forward.
4. **Per-note override** via `stale_after_days` so a slow-burn research project
   isn't nagged as aggressively as a sprint.

## Archetype A — `#Project-File`
Full template: [`notes/templates/project-file.md`](../notes/templates/project-file.md)

```yaml
---
type: project
title: "Migrate billing to Stripe"
status: active            # active | blocked | dormant | done
priority: high            # high | medium | low
deadline: 2026-07-01      # ISO date, "" if none
last_actionable_date: 2026-06-09
owner: ian
tags: [billing, infra]
stale_after_days: 5
---
```

## Archetype B — `#Learning-Log`
Full template: [`notes/templates/learning-log.md`](../notes/templates/learning-log.md)

```yaml
---
type: learning
title: "Spaced repetition + retrieval practice"
status: active
topic: learning-science
source: "Make It Stick (Brown et al.)"
last_actionable_date: 2026-06-12
review_interval_days: 3   # cadence you WANT, used by a future review flow
confidence: 0.4           # 0.0–1.0 self-rated mastery
tags: [memory, study]
---
```

## Field reference

| Key                    | Archetype | Type    | Used by pipeline | Meaning |
|------------------------|-----------|---------|:----------------:|---------|
| `type`                 | both      | string  | ✅ (discriminator) | `project` / `learning` |
| `title`                | both      | string  | ✅ | Human label sent to the LLM |
| `status`               | both      | string  | ✅ (`done` excluded) | lifecycle |
| `priority`             | project   | string  | ✅ (ranking) | high/medium/low |
| `deadline`             | project   | date    | ✅ (ranking) | hard date |
| `last_actionable_date` | both      | date    | ✅ (heartbeat) | last real touch |
| `stale_after_days`     | project   | int     | ✅ (threshold)| per-note override (default 5) |
| `review_interval_days` | learning  | int     | ✅ (review due) | revisit cadence (default 7) |
| `confidence`           | learning  | float   | ✅ (tie-break) | self-rated mastery; lower = reviewed first |
| `tags`                 | both      | list    | — | Obsidian/Logseq graph |

## Why this beats a vector DB *here*
- A 5–500 note personal vault is tiny; linear scan + frontmatter filtering is
  milliseconds and **zero** resident memory.
- Embeddings/Chroma/Qdrant would add 300–800 MB of always-on RAM — fatal on an
  8 GB host already running Windows + a browser.
- Semantic recall *is still available*: it's offloaded to the **cloud** LLM at
  call time (Section 4), which reads the raw note strings on demand. You pay
  $0 and store nothing locally.

> When to revisit: if the vault grows past a few thousand notes and you need
> true semantic search, add embeddings as a **cloud** call (Gemini/Voyage free
> tier) writing vectors to a hosted free-tier store — never a local container.
