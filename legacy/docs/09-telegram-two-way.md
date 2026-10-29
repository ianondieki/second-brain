# Section 9 — Two-Way Telegram Assistant (interactive bot)

The morning nudge is *one-way* (it only pushes). This workflow makes the bot
**interactive**: you can text it a question and it answers with the LLM, or send
it a command (`/note`, `/done`, …) that updates your vault. Import
[`n8n/telegram-assistant-workflow.json`](../n8n/telegram-assistant-workflow.json).

## Why polling, not webhooks
A Telegram bot receives messages two ways: a **webhook** (Telegram pushes to a
public HTTPS URL) or **`getUpdates` polling** (you ask "anything new?"). Your n8n
is bound to `127.0.0.1` — there is no public URL — so a webhook would need a
tunnel (Cloudflare Tunnel / ngrok). This workflow **polls** instead: a Schedule
Trigger fires every few seconds and calls `getUpdates` as a **long poll** (see
*Latency* below). Nothing is exposed to the internet, and it works on the same
localhost stack you already run.

> Only **one** consumer may call `getUpdates` per bot at a time. The morning
> nudge workflow only *sends*, so there is no conflict. Don't set a Telegram
> webhook on the same bot while this poller is active (you'd get HTTP 409).

## Topology
```
[Poll Every 5s] -> [Read Offset] -> [Get Updates] -> [Route & Handle] -> [Needs LLM?]
                                                                               |-- true  --> [Chat LLM (Groq)] -> [Extract Reply] --\
                                                                               |-- false --------------------------------------------> [Send Reply]
```

- **Read Offset** — reads `/data/inbox/.tg_offset`, the id of the last message
  already handled. A *file* is used deliberately (not n8n static data): static
  data isn't persisted on manual test runs, which would replay messages. The
  file behaves identically for manual and active runs.
- **Get Updates** — `GET …/getUpdates?timeout=4&allowed_updates=["message"]&offset=<n>`.
  `timeout=4` is a **long poll**: the request holds open and returns the *instant*
  a message arrives (or after 4s if none), instead of returning empty immediately.
  That's the bulk of the latency win — see *Latency*.
- **Route & Handle** — the brain. For each update it enforces the guards below,
  then either runs the command inline or marks the message `needs_llm`. Finally
  it advances the offset file to `max(update_id)+1` so nothing is processed twice.
- **Needs LLM?** — IF node. Commands already have a reply; chat messages go to Groq.
- **Chat LLM (Groq)** → **Extract Reply** — same OpenAI/Gemini-shape normalizer
  as the nudge, but an empty/blocked reply yields a *soft fallback* instead of
  throwing (a chat turn should never go silent).
- **Send Reply** — `sendMessage` with `parse_mode: HTML`. Every reply is
  HTML-escaped before any `<b>`/`<i>` tags are added, so a stray `<` in your
  text can't break parsing.

## Guards (why it's safe to leave on)
1. **Owner-only.** Replies only to `TELEGRAM_CHAT_ID`. If a stranger finds the
   bot, they get silence — and never cost you an LLM call.
2. **No self-loop.** Messages where `from.is_bot` is true are ignored.
3. **Text-only.** Stickers/photos/edits are skipped (`allowed_updates=["message"]`
   plus a `message.text` check).
4. **At-least-once, no replay.** The offset advances past everything seen; in the
   rare crash-mid-handle case a message may repeat, never silently vanish.

## Commands
| Command | Effect | Feeds |
|---|---|---|
| `/note <text>` (`/n`, `/capture`) | Writes a `type: capture` note to `_inbox` | your vault |
| `/touch <project>` | Logs activity → resets the staleness clock | morning nudge filter |
| `/done <project>` | Stops nudging that project | morning nudge filter |
| `/reopen <project>` | Undoes a `/done` | morning nudge filter |
| `/help` (`/start`) | Lists the commands | — |
| *anything else* | Answered by the Groq LLM | — |

Commands share the exact action-log format the morning **Filter Stale Projects**
node reads (`/data/inbox/.actions.jsonl`), so texting `/done stripe` actually
silences tomorrow's nudge.

## Setup (2 steps — no new keys, no infra changes)
Everything it needs (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GROQ_API_KEY`, the
writable `_inbox` mount, `NODE_FUNCTION_ALLOW_BUILTIN=fs,path`) is already in your
`.env` / `docker-compose.yml` from the morning nudge.

1. n8n → **Import from File** → `n8n/telegram-assistant-workflow.json`.
2. Flip the workflow **Active** toggle **on** (the Schedule trigger only runs when
   active). Within a minute, text your bot "hi" — it replies.

> Testing with **Execute Workflow** works too, but offset only persists to the
> file when handling completes; if you spam it during manual tests you might see
> a message answered twice. Activating is the real mode.

## Grounded follow-ups (the nudge → conversation handoff)
The nudge and the assistant are two workflows, but they're wired together so it
*feels* like one bot: **nudge arrives, then you discuss it.**

- When the morning nudge fires, its **Filter Stale Projects** node writes the
  project it's nudging you about to `/data/inbox/.tg_context.json` (title,
  `days_stale`, `deadline`, `recent_notes`, plus any due reviews).
- When you then reply with free text, the assistant's **Route & Handle** node
  loads that focus file and injects it into the Groq prompt as `CURRENT FOCUS`.

So the real flow is:
```
08:00  bot →  🧊 HOOK … 🧠 CONTEXT … ✅ MICRO-ACTION       (nudge + writes focus)
       you → explain more / why does this matter / where did I leave off?
       bot →  <answer about THAT project, using its recent_notes>
```
If no nudge has fired yet (no focus file), the assistant just answers as a
general helper — no crash, no stale project forced into unrelated questions.

> **You must run BOTH workflows.** The *nudge* workflow
> (`morning-nudge-telegram.json`) is what proactively sends the project message —
> on its 08:00 cron, or whenever you hit **Execute Workflow** to fire it now. The
> *assistant* (`telegram-assistant-workflow.json`) is what listens for your
> replies. Activate both; the assistant alone will only ever react to messages,
> never start the conversation.

## Short-term memory (multi-turn)
The assistant remembers the last few turns so a real back-and-forth flows
naturally ("explain more" → "ok what first?" → "how long will that take?").

- **Where.** A bounded window lives in `/data/inbox/.tg_history.json`. **Route**
  builds the Groq prompt as a full `messages` array — `system → prior turns →
  new message` — and records the user turn; **Extract Reply** appends the
  assistant turn (stored as *plain* text, never the HTML that's sent).
- **Bounded.** Only the last 8 turns are kept and each is length-clipped, so the
  token budget (and the file) can't balloon no matter how long you chat.
- **Self-resetting — no stale bleed.** The thread auto-clears when a **newer
  nudge focus** arrives (each morning's nudge, or a manual re-fire, starts a
  clean conversation) or after a **6-hour** cold-chat gap. So yesterday's chat
  about a different project never leaks into today's.
- **Best-effort.** Every read/write is guarded; if memory can't be written the
  reply still goes out — the bot degrades to stateless, never breaks.

## Latency (why replies are near-instant)
Two settings, working together, decide how fast the bot answers:

- **Long poll — `getUpdates?timeout=4`.** The request *holds open* and returns the
  moment your message lands, rather than `timeout=0` returning empty and forcing
  you to wait for the next tick. Most messages are answered in ~1s.
- **5-second cadence.** The Schedule Trigger fires every 5s, so even a message
  that arrives in the ~1s gap between polls waits at most ~1s. (Was a 1-minute
  schedule → up to 60s of dead wait. That was the whole problem.)

**Why this is safe (no double replies, no 409):**
- The interval (5s) is kept **greater** than the poll hold (4s), so two
  `getUpdates` calls never run at once — Telegram allows only one consumer.
- **Route advances the offset early** — it writes `.tg_offset` the instant it
  reads the batch, *before* the slow Groq call. So if a long LLM answer makes the
  next poll fire mid-flight, that poll reads the already-advanced offset, sees
  nothing new, and exits. A message can't be handled (or answered) twice.
- These invariants are locked by tests: `timeout > 0`, cadence is `seconds`, and
  `timeout < interval` are all asserted in `scripts/test-pipeline.mjs`.

> **Tuning.** Want it even snappier under chatty bursts? Lower the Schedule to
> every 3s and set `timeout=2` (keep `timeout < interval`). Want fewer idle calls?
> Raise both (e.g. 15s / `timeout=10`). The only hard rule is poll-hold < interval.
> Truly sub-second, push-based delivery needs a **webhook**, which requires
> exposing n8n via a public HTTPS tunnel — more infra, not built here.

## Notes & upgrade paths
- **Vault-grounded answers** ("what am I behind on?") would mean feeding the
  scan results into the chat prompt — a natural next step, not built here.
