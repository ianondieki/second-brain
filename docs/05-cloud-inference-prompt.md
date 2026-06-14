# Section 5 — The Cloud Inference Cognitive Prompt

The canonical, copy-paste prompt lives at
[`n8n/cloud-inference-prompt.md`](../n8n/cloud-inference-prompt.md) and is
embedded verbatim in Node 3's `SYSTEM_PROMPT`. This doc explains the
engineering behind it.

## Contract
- **System message:** the cognitive prompt (role, ranking logic, format,
  3-step flow, guardrails).
- **User message:** raw JSON `{ today, stale_projects[] }`. We deliberately
  send *structured data*, not prose, so the model reasons over fields instead
  of guessing.

## Design decisions
1. **Pre-sorted, single-target selection.** Node 3 ranks the array (deadline →
   priority → days_stale) *before* the call, and the prompt says "nudge the
   FIRST item." This makes the output deterministic and lets a fast/cheap model
   do well — it doesn't have to re-derive priority. One optional secondary line.
2. **Output discipline.** "Output ONLY the message body, no code fences, no
   JSON" — so Node 5 can pipe `choices[0].message.content` straight to WhatsApp
   with no post-processing.
3. **Phone-first formatting.** Single-asterisk `*bold*`, `_italics_`, emoji
   bullets, <90 words, blank line between blocks — matches the WhatsApp renderer
   exactly (double `**asterisks**` do NOT render bold on WhatsApp).
4. **The 3-step persuasion flow** (each label emoji-prefixed, on its own line):
   - `🧊 *HOOK*` — names what went cold + `days_stale` (loss-aversion cue).
   - `🧠 *CONTEXT*` — paraphrases `recent_notes` so re-entry is frictionless.
   - `✅ *MICRO-ACTION*` — one ≤10-minute task; defeats activation energy.
5. **Anti-hallucination guardrail.** "Never invent facts not present in the
   notes" — the model may only paraphrase `recent_notes`; an empty
   `recent_notes` triggers a "re-read the note" fallback action.
6. **Low temperature (0.4).** Consistent structure, mild wording variety.

## The prompt
See [`n8n/cloud-inference-prompt.md`](../n8n/cloud-inference-prompt.md) for the
verbatim block and a rendered example.

## Tuning knobs
| Want… | Change |
|-------|--------|
| Punchier copy | drop `max_tokens` to 400, temp 0.3 |
| More variety | temp 0.6–0.7 |
| Two nudges | allow 2 primary blocks; raise word cap to ~140 |
| Include learning logs | in Node 3, also pass `type: learning` items whose `last_actionable_date` exceeds `review_interval_days`, and add a 4th flow step `📚 REVIEW` |
| Different model | Groq `llama-3.3-70b-versatile` (quality) or `llama-3.1-8b-instant` (speed); Gemini `gemini-1.5-flash` |
