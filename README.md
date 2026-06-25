# Agentic Second Brain — Hybrid Local/Cloud

A 100% free, open-source, resource-frugal "second brain" that nudges you each
morning over **Telegram** about projects that have gone cold. Built to run on an
**8 GB Windows laptop** without ever loading a local LLM.

## Architecture

```text
┌──────────────────────── Windows host (8 GB RAM) ─────────────────────────┐
│                                                                          │
│  Markdown vault (Obsidian/Logseq)  ──read-only──▶  ┌──────────────┐      │
│  C:/.../SecondBrain/*.md                           │     n8n      │      │
│                                                    │ (orchestr.)  │      │
│   Docker Desktop (WSL2)                            └──────┬───────┘      │
│   one container: n8n (SQLite, ~450m)                     │              │
└──────────────────────────────────────────────────────────┼──────────────┘
                                     │ HTTPS (free tier)    │ Telegram Bot API
                                     ▼                      ▼
                    Cloud LLM — Groq / Gemini ($0)     📱 Telegram (nudge + chat)
```

- **Local layer (ultra-light):** Docker → a single n8n container (SQLite
  backend). Idle well under **0.5 GB** — no WhatsApp gateway, no Postgres/Redis.
- **Cloud layer (free):** all LLM synthesis is offloaded to Groq or Gemini
  free tiers, and delivery rides the official **Telegram Bot API**. No local
  model, no local vector DB.

## What it does
Every morning at 08:00 it scans your Markdown notes, finds projects whose
`last_actionable_date` has gone stale (and learning notes due for spaced
review), asks a cloud LLM to write a short, phone-formatted nudge (Hook →
Context → Micro-action, plus a 📚 review line when one's due), and sends it to
your **Telegram**.

The bot is two-way (§9):
- **Interactive assistant** — reply to the nudge ("explain more", "what first?")
  and it answers with context + short-term memory, or run a command: `/note
  <text>` to capture a thought, `/touch <project>` to reset its staleness,
  `/done <project>` to stop nudging it. Captures land in a separate writable
  inbox; the vault stays read-only.
- **Evening check-in (§10)** — at 20:30 the bot asks "what did you move forward
  today?"; you reply in plain language and it auto-logs `touch` actions to the
  right projects, so the staleness clock stays honest with zero command-typing.
- **Error → Telegram alert** — if a run fails, you get a one-line alert instead
  of silent breakage.

## Repo map
| Path | Purpose |
|------|---------|
| [`docker-compose.yml`](docker-compose.yml) | The whole local stack (§1) |
| [`.env.example`](.env.example) | Copy to `.env`, fill secrets |
| [`docs/01-docker-environment.md`](docs/01-docker-environment.md) | §1 RAM budget + Windows setup |
| [`docs/02-knowledge-base-ontology.md`](docs/02-knowledge-base-ontology.md) | §2 frontmatter schema |
| [`docs/04-automation-engine.md`](docs/04-automation-engine.md) | §4 node-by-node pipeline |
| [`docs/05-cloud-inference-prompt.md`](docs/05-cloud-inference-prompt.md) | §5 the cognitive prompt |
| [`docs/06-operations-troubleshooting.md`](docs/06-operations-troubleshooting.md) | §6 runbook & fixes |
| [`docs/07-inbound-and-errors.md`](docs/07-inbound-and-errors.md) | §7 inbound capture, commands, error alerts |
| [`docs/08-confidence-and-verification.md`](docs/08-confidence-and-verification.md) | §8 what's proven vs trusted + 5-min check |
| [`docs/09-telegram-two-way.md`](docs/09-telegram-two-way.md) | §9 interactive two-way Telegram bot |
| [`docs/10-evening-checkin.md`](docs/10-evening-checkin.md) | §10 evening check-in → auto-logs progress |
| [`n8n/morning-nudge-telegram.json`](n8n/morning-nudge-telegram.json) | Morning nudge workflow (Telegram) |
| [`n8n/telegram-assistant-workflow.json`](n8n/telegram-assistant-workflow.json) | Two-way Telegram assistant (chat + commands) |
| [`n8n/evening-checkin-workflow.json`](n8n/evening-checkin-workflow.json) | Evening check-in → maps your reply to `touch` actions |
| [`n8n/error-handler-workflow.json`](n8n/error-handler-workflow.json) | Error → Telegram alert |
| [`n8n/cloud-inference-prompt.md`](n8n/cloud-inference-prompt.md) | Canonical LLM prompt |
| [`notes/templates/`](notes/templates/) | `#Project-File` & `#Learning-Log` templates |
| [`scripts/`](scripts/) | smoke tests + `test-pipeline.mjs` regression test |

## Quick start
1. **Get a free API key:** [Groq](https://console.groq.com/keys) (default) or
   [Gemini](https://aistudio.google.com/app/apikey).
2. **Create a Telegram bot:** message [@BotFather](https://t.me/BotFather) →
   `/newbot` → copy the token; get your chat id from `getUpdates` (see §9).
3. `copy .env.example .env` and fill every value (vault path, encryption key,
   API key, Telegram token + chat id). The workflow reads its keys from `.env`
   via `$env` — **no in-app credential setup**.
4. Cap Docker RAM via `.wslconfig` (see §1), then `docker compose pull && docker compose up -d`.
5. Open <http://localhost:5678>, create the n8n **owner account** (one-time).
6. Import `n8n/morning-nudge-telegram.json`, **Execute Workflow** once to
   dry-run, then toggle **Active** (§4). Import `n8n/telegram-assistant-workflow.json`
   for the two-way bot, and the error-handler workflow for alerts (§9).
7. Drop `notes/templates/EXAMPLE-stale-project.md` into your vault to force a
   nudge on the dry-run, or run `scripts/smoke-test.ps1` to verify the stack.

Verify the workflow logic anytime (no Docker needed):
```bash
node scripts/test-pipeline.mjs     # runs the shipped Code-node logic against fixtures
```

Full instructions are in the `docs/` sections in order; §6 is the troubleshooting runbook.

## Cost & footprint
- **$0/month** — Docker + n8n are open-source; the LLM runs on free tiers and the
  Telegram Bot API is free.
- **One container, < 0.5 GB RAM**, no local model, no local vector DB.
