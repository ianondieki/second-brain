# Anthropic API list prices (D-37, prototype track)

Retrieved 2026-09-29. USD per million tokens (MTok). Read-only research; no accounts or credentials used.

**Verdict: verified** (every number for all three models came from an official Anthropic page fetched on 2026-09-29).

## Price table

P = https://platform.claude.com/docs/en/about-claude/pricing ("Model pricing" table), fetched 2026-09-29.
S5 = https://platform.claude.com/docs/en/models/sonnet-5/overview, fetched 2026-09-29.

| Model (page name) | API id / alias on page | Input | Output | Cache read | 5m cache write | 1h cache write | Source |
|---|---|---|---|---|---|---|---|
| Claude Sonnet 5 (legacy) | `claude-sonnet-5` (S5: "Model ID") | $2 | $10 | $0.20 | $2.50 | $4 | P; S5 (same values) |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` (API ID), `claude-haiku-4-5` (alias) | $1 | $5 | $0.10 | $1.25 | $2 | P; models overview |
| Claude Opus 5.5 | `claude-opus-5-5` (API ID and alias) | $4 | $20 | $0.20 (0.05x base, not the usual 0.1x) | $5 | $8 | P; models overview |

Ids: models overview https://platform.claude.com/docs/en/models/overview (fetched 2026-09-29; it redirected from docs.claude.com/en/docs/about-claude/models/overview) lists Haiku 4.5 and Opus 5.5 ids. It lists Sonnet 5.5 (`claude-sonnet-5-5`) as current and only links Sonnet 5 as legacy; the Sonnet 5 id comes from S5.

## Batch discount

- "The Batch API allows asynchronous processing of large volumes of requests with a 50% discount on both input and output tokens." (P, "Batch processing")
- Batch table on P: Sonnet 5 $1 in / $5 out; Haiku 4.5 $0.50 in / $2.50 out; Opus 5.5 $2 in / $10 out.
- Cache multipliers stack with the batch discount: "These multipliers stack with other pricing modifiers, including the Batch API discount and data residency." (P)

## Notes and changes

- Sonnet 5 footnote (P): "$2/$10 ... announced at launch as introductory pricing through August 31, 2026, is now the standard price. The previously scheduled increase to $3/$15 ... on September 1, 2026 will not occur."
- Sonnet 5 is now legacy; the current Sonnet is Claude Sonnet 5.5 (`claude-sonnet-5-5`, $2/$10). Haiku 4.5 retirement: "Not sooner than October 15, 2026" (models overview). Sonnet 5 retirement: "Not sooner than June 30, 2027" (S5).
- Cache formulas (P): 5-minute write 1.25x base input, 1-hour write 2x, read 0.1x (0.05x on Opus 5.5). The table values above are those printed in the model pricing table, and agree with the multipliers.
- Claude 4.7 and later models use a newer tokenizer producing about 30% more tokens for the same text (P). This affects Sonnet 5 and Opus 5.5 cost per text, not the per-token price.
- `inference_geo: "us"` applies a 1.1x multiplier on Claude 4.6 and later (P).

## Fetch log

| URL | Outcome |
|---|---|
| https://docs.claude.com/en/docs/about-claude/pricing | 302 to platform.claude.com/docs/en/about-claude/pricing (followed) |
| https://platform.claude.com/docs/en/about-claude/pricing | OK, full page |
| https://www.anthropic.com/pricing | 301 to https://claude.com/pricing (followed) |
| https://claude.com/pricing | OK, summarised: Opus 5.5 $4/$20, read $0.20, write $5; Haiku 4.5 $1/$5, read $0.10, write $1.25; batch 50%. Sonnet 5 only in a "Legacy" line without figures; 1h write not shown. Cross-check only, not used as a source. |
| https://docs.claude.com/en/docs/about-claude/models/overview | 302 to platform.claude.com/docs/en/about-claude/models/overview (followed) |
| https://platform.claude.com/docs/en/about-claude/models/overview | OK (page self-reports url .../docs/en/models/overview) |
| https://platform.claude.com/docs/en/models/sonnet-5/overview | OK |

## Open questions

- The pages are fetched through a summarising tool for the claude.com page only; the two docs pages were returned as raw markdown. The claude.com/pricing page was not used for any number.
- Prices may change again; re-fetch before any billing or cost-cap figure is frozen.
