# Section 10 — Evening Check-in (close the loop on staleness)

The morning nudge *resurfaces* cold work; the evening check-in *records* what you
actually moved, so the staleness clock stays honest **without you remembering any
slash commands**. Import [`n8n/evening-checkin-workflow.json`](../n8n/evening-checkin-workflow.json)
— it works hand-in-glove with the two-way assistant (§9).

## How it works
```
20:30  Cron ─▶ Build Check-in (scan active items, write roster) ─▶ Telegram:
       "🌙 What did you move forward today?"
       you → "pushed the Stripe integration and revised spaced repetition"
       assistant → maps that to your real items → logs `touch` actions →
       "✅ Logged today's progress: • Stripe billing • Spaced repetition"
```

The clever bit: your reply is **plain language**, not commands. The assistant
sends it to the LLM with your *active roster* and asks for a strict JSON mapping,
then writes a `touch` to `/data/inbox/.actions.jsonl` for each matched item — the
exact log the morning nudge already honours. So tonight's "yeah I worked on
Stripe" means Stripe won't nag you tomorrow.

## The two halves
| Workflow | Role |
|---|---|
| `evening-checkin-workflow.json` (NEW) | 20:30 cron → scans active projects + learning topics → writes the **roster + `awaiting` flag** → sends the prompt |
| `telegram-assistant-workflow.json` (§9) | already polling; when a reply lands **in the window**, it maps + logs instead of chatting |

There is **no second poller** — that would clash with the assistant's `getUpdates`
(HTTP 409). The check-in rides the assistant you already run.

## State files (same file-based pattern as everything else)
- **`.tg_checkin.json`** — `{ ts, awaiting, projects[] }`. Written by the evening
  workflow; the assistant reads it.
- **`.tg_checkin_pending.json`** — a short-lived marker Route writes when it routes
  a reply as a check-in, so Extract Reply knows the next LLM response is a *mapping*
  (a JSON array) rather than a chat answer. Consumed (deleted) after one use.

## Why it can't misfire (the guards)
1. **Window-bounded.** Only a reply within **4 hours** of the prompt is treated as
   a check-in; later messages are normal chat.
2. **First-reply-only.** The `awaiting` flag is consumed by your first reply, so a
   follow-up question that evening goes back to normal chat.
3. **No chat-history pollution.** Check-in turns are *not* stored in the
   conversation memory — they're a side-channel, not a conversation.
4. **Graceful no-match.** If the LLM maps your reply to nothing (e.g. "watched a
   movie"), nothing is logged and the bot says so — never a spurious `touch`.
5. **Best-effort writes.** If the inbox is read-only the prompt still sends; if the
   mapping can't be parsed, you get a friendly fallback, never a crash.

## Setup
Needs nothing new — same `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / vault mount.

1. Import `evening-checkin-workflow.json` onto a blank canvas and **Publish/Activate**.
2. Make sure the **assistant** (§9) is also active — it's what handles your reply.
3. (Optional) change the time: open **Cron 20:30 Daily** and edit the expression
   (`30 20 * * *`). The instance `TZ` governs what 20:30 means.

> **You run all three now:** morning nudge (proactive), the assistant (replies),
> and the evening check-in (proactive). They share the vault, the action log, and
> the Telegram channel — three cron/poll triggers, one coherent loop.

## Tuning the window
The 4-hour reply window lives in the assistant's **Route** node (`CHECKIN_TTL_MS`).
If you tend to reply the next morning, widen it; if you want it strict to the
evening, shorten it. The pending-marker freshness (2 min, in **Extract Reply**)
only bounds the single LLM round-trip and rarely needs changing.
