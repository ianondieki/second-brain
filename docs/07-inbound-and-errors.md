# Section 7 — Commands, the Action Log & Error Alerts

The two-way **Telegram** bot (commands + chat) is documented in §9. This section
covers the two things that sit *underneath* it: the **action log** that commands
write (and the morning nudge reads), and the **error-alert** safety net.

| Workflow | File | Trigger |
|---|---|---|
| Two-way assistant (commands + chat) | [`n8n/telegram-assistant-workflow.json`](../n8n/telegram-assistant-workflow.json) | Telegram poll — see §9 |
| Error → Telegram alert | [`n8n/error-handler-workflow.json`](../n8n/error-handler-workflow.json) | any workflow error |

---

## 7.1 Commands & the action log

The assistant's slash commands (full list and behaviour in §9) never touch your
pristine vault — the vault is mounted **read-only**. All writes go to the
separate writable `/data/inbox` mount (`INBOX_PATH` in `.env`):

| Command | Writes to | Effect |
|---|---|---|
| `/note <text>` | a new `type: capture` `.md` in the inbox | captured thought |
| `/touch <project>` | `.actions.jsonl` (`touch`) | resets that project's staleness clock |
| `/done <project>` | `.actions.jsonl` (`done`) | morning nudge stops surfacing it |
| `/reopen <project>` | `.actions.jsonl` (`reopen`) | cancels a prior `/done` (clock unchanged) |

Project matching is **case-insensitive substring** both ways, so `/touch stripe`
matches *"Stripe billing migration"*. Use distinctive words to avoid ambiguity.

### How the morning nudge honours it
Node 3 of the morning pipeline reads `/data/inbox/.actions.jsonl` (if present)
and, per project, applies the **latest** matching action:
- `done` → excluded from nudges,
- `touch` → staleness clock advanced to the action date,
- `reopen` → un-excluded, clock unchanged.

If the inbox isn't mounted the read is skipped silently — the morning nudge
still works standalone. This is the contract the §9 commands rely on; the
channel (Telegram) is irrelevant to it.

---

## 7.2 Error → Telegram alert

### What it does
An n8n **Error Trigger** workflow that fires whenever a monitored workflow
throws, and sends you a one-line Telegram alert (rendered with `parse_mode:
HTML`, so the dynamic parts are escaped):

```text
⚠️ Second Brain failed
Workflow: Autonomous Morning Nudge Pipeline (Telegram)
Node: Cloud LLM Synthesis (Groq)
Error: Request failed with status code 401
http://localhost:5678/execution/42
```

### Activate it
1. Import & **Activate** *Error Handler → Telegram Alert*.
2. For each workflow you want covered (the morning nudge, the assistant), open
   **Workflow → Settings → Error Workflow** and select *Error Handler → Telegram
   Alert*. n8n only routes errors to a handler that a workflow explicitly names.

It reuses the same `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` as everything else —
no extra setup.

### Caveat
If the failure is that **Telegram itself** is unreachable, the alert send will
also fail — but the original error is still recorded under n8n → Executions.
Treat the alert as a convenience, not the system of record.
