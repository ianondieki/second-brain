# Section 5 — The Cloud Inference Cognitive Prompt

The canonical, copy-paste prompt lives at
[`n8n/cloud-inference-prompt.md`](../n8n/cloud-inference-prompt.md) and is
embedded verbatim in Node 3's `SYSTEM_PROMPT`. This doc explains the
engineering behind it.

## Contract
- **System message:** the cognitive prompt (role, ranking logic, format,
  3-step flow, optional review line, guardrails).
- **User message:** raw JSON `{ today, stale_projects[], due_reviews[] }`. We
  deliberately send *structured data*, not prose, so the model reasons over
  fields instead of guessing. Either array may be empty; the prompt leads with
  whichever is present (projects take precedence).

> **Authoring constraint:** the prompt lives inside a JS template literal in
> Node 3, so it must contain no backticks or `${...}`. Field names are written
> as plain words (`stale_projects`, not `` `stale_projects` ``).

## Design decisions
1. **Pre-sorted, single-target selection.** Node 3 ranks the array (deadline →
   priority → days_stale) *before* the call, and the prompt says "nudge the
   FIRST item." This makes the output deterministic and lets a fast/cheap model
   do well — it doesn't have to re-derive priority. One optional secondary line.
2. **Output discipline.** "Output ONLY the message body, no code fences, no
   JSON" — keeps the reply send-ready. Node 4b (Extract Nudge) still normalizes,
   strips any stray fences, and renders `*bold*`/`_italic_` to Telegram HTML as a
   belt-and-braces guard before the send.
3. **Phone-first formatting.** Single-asterisk `*bold*`, `_italics_`, emoji
   bullets, <90 words, blank line between blocks — the Extract Nudge node
   converts those single asterisks to `<b>` for Telegram (double `**asterisks**`
   are not the convention here).
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
| Learning reviews | **Already wired in.** Node 3 emits `due_reviews` for `type: learning` notes past their `review_interval_days`, and rule 5 adds the `📚 REVIEW` line. Tune the global default via `GLOBAL_REVIEW_DAYS` in Node 3. |
| Different model | Set `GROQ_MODEL` in `.env` — no workflow edit. `llama-3.3-70b-versatile` (quality) / `llama-3.1-8b-instant` (speed); Gemini `gemini-1.5-flash` |
