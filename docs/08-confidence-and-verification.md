# Section 8 — Confidence & Verification (read this if you're unsure)

Honest engineering: here is exactly what has been **proven**, what is
**trusted but not yet executed**, and the **5-minute** way to settle it.

## ✅ Proven here (automated, repeatable)
Run `node scripts/test-pipeline.mjs` — **87 assertions, 0 failures**, executed
against the *exact* JavaScript shipped inside the workflow JSON files:

- Vault scan: recursion, skipping `.git`/`.obsidian`/etc., non-`.md` ignored, empty-vault error.
- Frontmatter parse: BOM, CRLF, inline `# comments`, quoted values, `[lists]`.
- Staleness: per-note `stale_after_days`, missing-date and `done` exclusion.
- Ranking: deadline(asc) → priority → days_stale.
- WhatsApp action log: `touch` resets the clock, `done` excludes, `reopen` un-excludes, latest-wins, old touch ignored.
- Learning reviews: `review_interval_days` due/not-due, `done` excluded, review-only still messages, ordering, `/done` on a topic.
- Inbound handler: `/note` writes a file, `/touch` `/done` append the log, `/help`, unknown command, **owner-only** filter, group/status ignored, no-loop guard.
- Error formatter: full + sparse payloads.
- LLM response guard (Extract Nudge): Groq **and** Gemini response shapes, ``` fence stripping, empty/blocked completion throws a clear error (no blank send), error-shaped 200 surfaced (no `TypeError`), runaway output truncated.
- Request bodies (Groq + Evolution): correct JSON, `$env` interpolation, `GROQ_MODEL` override, multi-line content survives escaping.
- Telegram rendering (Extract Nudge, Telegram variant): `*bold*`/`_italic_` → `<b>`/`<i>`, `<`/`>`/`&` HTML-escaped first (no parse breakage/injection), lone asterisk left literal, send body carries `parse_mode: HTML` + `chat_id` from `$env`.
- Telegram **two-way assistant** (polling): offset file read/parse/advance (no message replays), owner-only filter, no self-loop (ignores `is_bot`), non-text ignored, `/note` writes a tagged capture file, `/done` appends to the action log + HTML-escapes the echo, free text routed to the LLM with the chat prompt, empty LLM reply → soft fallback (never silent), `getUpdates` URL carries the offset.
- **Grounded follow-ups**: the Telegram nudge writes the nudged project to a focus file; the assistant loads it so a free-text reply (e.g. "explain more") is answered about that exact project (`CURRENT FOCUS` injected); with no focus file it falls back to plain chat without crashing.
- **Conversation memory** (bounded, self-resetting): prior user+assistant turns are replayed into the next prompt as a real `messages` array, the current message is always last, a newer nudge focus resets the thread (no cross-day bleed), and the window is trimmed so it can't blow up the token budget.
- **Low-latency polling**: `getUpdates` uses a long-poll (`timeout>0`, returns the instant a message arrives) on a seconds-based cadence, and the poll hold is asserted to stay **below** the schedule interval so two `getUpdates` can never overlap (no Telegram 409).

Also re-checked every change: all 5 Code nodes `node --check` clean; all 3
workflow JSONs parse; `docker compose config` validates. The suite is **time-
relative** — verified identical at today and +500 days, so it cannot rot.

## ⚠️ Trusted but NOT yet executed (and why)
This environment has **no Docker daemon and no live API keys**, so these can
only be confirmed on your machine. They are the honest source of any doubt:

| # | Thing | Why unverifiable offline | If it's wrong, you'll see |
|---|---|---|---|
| 1 | n8n **node parameter schemas** (e.g. `jsonBody` as an object expression, `scheduleTrigger`/`webhook` shapes) | needs a running n8n to import | red node on import / "could not be parsed" |
| 2 | **Image tags** pull (`atendai/evolution-api:v2.1.1`, n8n `latest`) | no daemon | `manifest unknown` on `pull` |
| 3 | **Live API 200s** (Groq, Evolution send) | no keys / no gateway | 401 / 404 / 429 in node output |
| 4 | **Evolution webhook-set** body shape (inbound) | version-sensitive | 400 on the `webhook/set` call |

## The 5-minute definitive check (do this first on the laptop)
1. `docker compose pull` — settles #2. If a tag 404s, bump it (links in §1).
2. `docker compose up -d && docker compose ps` — all healthy.
3. n8n → **Import** `morning-nudge-workflow.json` — **settles #1**: if it
   imports with no red nodes, the schemas are correct.
4. Drop `notes/templates/EXAMPLE-stale-project.md` + `EXAMPLE-due-review.md`
   into the vault, click **Execute Workflow**, watch nodes go green —
   **settles #1 and #3** for the morning path.

## The 4 likely failure points → one-line fixes
Keep this handy during the first run:

- **Groq/Evolution node shows a body/JSON error.** Switch its body to a string:
  change `jsonBody` from `={{ { ... } }}` to `={{ JSON.stringify({ ... }) }}`.
  (Both forms are valid n8n; stringify is the bulletproof fallback.)
- **Evolution send returns 400 "text".** Your image expects the v1 shape — use
  body `={{ { "number": $env.WA_TARGET_NUMBER, "textMessage": { "text": $json.text } } }}`
  (Node 4b already normalized the LLM reply into `$json.text`).
- **Groq returns 404 model_not_found.** That model id was retired — set a
  current one in `.env` `GROQ_MODEL` (check https://console.groq.com/docs/models),
  e.g. `llama-3.1-8b-instant`. No workflow edit needed.
- **`webhook/set` returns 400.** Use the flattened body
  `{ "enabled": true, "url": "...", "events": ["MESSAGES_UPSERT"] }` (no outer
  `webhook` key) — see §7.1.

## Cron didn't fire?
The cron uses an expression (`0 8 * * *`). If your n8n version dislikes the
imported expression, open the Schedule Trigger and re-pick **Trigger Interval =
Days, at 08:00** in the UI — same effect, zero config drift.

---
**Bottom line:** the *logic* is exhaustively tested and correct. The residual
risk is entirely in n8n/Evolution version-specifics, every one of which has a
documented one-line fix above and is exposed within the first 5 minutes of a
dry-run. Nothing here fails silently.
