# Section 7 — Inbound Capture, Commands & Error Alerts

Two optional workflows extend the one-way morning nudge into a two-way
assistant, plus a safety net that pings you when anything breaks.

| Workflow | File | Trigger |
|---|---|---|
| Inbound capture & commands | [`n8n/inbound-capture-workflow.json`](../n8n/inbound-capture-workflow.json) | WhatsApp message → webhook |
| Error → WhatsApp alert | [`n8n/error-handler-workflow.json`](../n8n/error-handler-workflow.json) | any workflow error |

Both import the same way: n8n → **Workflows → ⋯ → Import from File**.

---

## 7.1 Inbound capture & commands

### What it does
You message your own WhatsApp; the gateway forwards it to n8n, which acts on
**slash commands** and replies. The pristine vault stays **read-only** — all
writes go to the separate writable `/data/inbox` mount (`INBOX_PATH` in `.env`).

| Command | Effect |
|---|---|
| `/note <text>` (or `/n`, `/capture`) | Saves a `type: capture` Markdown file in the inbox |
| `/touch <project>` (or `/did`) | Appends a `touch` to `.actions.jsonl` → resets that project's staleness clock |
| `/done <project>` | Appends a `done` → the morning nudge stops surfacing it |
| `/reopen <project>` | Cancels a prior `/done` (does **not** reset the clock) |
| `/help` | Lists the commands |

Project matching is **case-insensitive substring** both ways, so `/touch stripe`
matches *"Stripe billing migration"*. Use distinctive words to avoid ambiguity.

### Why it can't create a feedback loop
The gateway *is* your own WhatsApp account, so both your commands and the bot's
nudges arrive as `fromMe`. The handler therefore **only acts on messages that
start with `/`** — the bot's emoji-formatted nudges (starting with `🧊`) are
ignored. Anything that isn't a known command is silently dropped (no reply).

### How the morning nudge honours it
Node 3 of the morning pipeline reads `/data/inbox/.actions.jsonl` (if present)
and, per project, applies the **latest** matching action:
- `done` → excluded from nudges,
- `touch` → staleness clock advanced to the action date,
- `reopen` → un-excluded, clock unchanged.

If the inbox isn't mounted the read is skipped silently — the morning nudge
still works standalone.

### Wiring Evolution → n8n (one-time)
The gateway must POST inbound messages to the n8n webhook. From the host
(values from your `.env`), point the instance webhook at n8n's **container**
hostname (`n8n` on the shared `sbnet` network):

```powershell
curl -X POST "http://localhost:8080/webhook/set/%EVOLUTION_INSTANCE%" ^
  -H "apikey: %EVOLUTION_API_KEY%" -H "Content-Type: application/json" ^
  -d "{ \"webhook\": { \"enabled\": true, \"url\": \"http://n8n:5678/webhook/wa-inbound\", \"webhookByEvents\": false, \"events\": [\"MESSAGES_UPSERT\"] } }"
```

> The exact webhook JSON shape varies slightly across Evolution v2 point
> releases (some accept the flattened `{enabled,url,events}` without the outer
> `webhook` key). If the call 400s, check `GET /webhook/find/{instance}` and the
> docs for your pinned image tag. The n8n path `wa-inbound` matches the
> **Webhook** node; activate the inbound workflow so its production webhook is
> live (test URLs only fire while the editor's "Listen" is open).

### Try it
1. Activate **WhatsApp Inbound Capture & Commands**.
2. Set the webhook (above).
3. From your phone, send `/help` to the linked number → you get the command list.
4. `/note pick up dry cleaning` → a new file appears in your inbox folder.
5. `/touch <one of your stale projects>` → tomorrow's nudge skips it.

---

## 7.2 Error → WhatsApp alert

### What it does
An n8n **Error Trigger** workflow that fires whenever a monitored workflow
throws, and sends you a one-line WhatsApp alert:

```text
⚠️ *Second Brain failed*
*Workflow:* Autonomous Morning Nudge Pipeline
*Node:* Cloud LLM Synthesis (Groq)
*Error:* Request failed with status code 401
http://localhost:5678/execution/42
```

### Activate it
1. Import & **Activate** *Error Handler → WhatsApp Alert*.
2. For each workflow you want covered (the morning nudge, the inbound flow),
   open **Workflow → Settings → Error Workflow** and select
   *Error Handler → WhatsApp Alert*. n8n only routes errors to a handler that a
   workflow explicitly names.

### Caveat
If the failure is that the **gateway itself** is down, the alert send will also
fail — but the original error is still recorded under n8n → Executions. Treat
the WhatsApp alert as a convenience, not the system of record.
