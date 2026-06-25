# Agentic Second Brain — Hybrid Local/Cloud

A 100% free, open-source, resource-frugal "second brain" that nudges you each
morning over WhatsApp about projects that have gone cold. Built to run on an
**8 GB Windows laptop** without ever loading a local LLM.

## Architecture

```text
┌──────────────────────── Windows host (8 GB RAM) ─────────────────────────┐
│                                                                          │
│  Markdown vault (Obsidian/Logseq)  ──read-only──▶  ┌──────────────┐      │
│  C:/.../SecondBrain/*.md                           │     n8n      │      │
│                                                    │ (orchestr.)  │      │
│                                                    └──────┬───────┘      │
│   Docker Desktop (WSL2, capped at 2 GB)                   │              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐               │ HTTP         │
│   │ postgres │  │  redis   │  │ evolution│◀──────────────┘ sendText     │
│   │  256m    │  │   96m    │  │  400m    │── WhatsApp Web (QR) ─▶ 📱      │
│   └──────────┘  └──────────┘  └──────────┘                              │
└───────────────────────────────────┬──────────────────────────────────────┘
                                     │ HTTPS (free tier)
                                     ▼
                    Cloud LLM  —  Groq  /  Gemini 1.5 Flash   ($0)
```

- **Local layer (ultra-light):** Docker → n8n + Evolution API (WhatsApp Web
  gateway) + a tiny Postgres/Redis for the gateway. Combined RAM ceiling
  **< 1.2 GB**; idle ~0.5–0.7 GB.
- **Cloud layer (free):** all LLM synthesis is offloaded to Groq or Gemini
  free tiers. No local model, no local vector DB.

## What it does
Every morning at 08:00 it scans your Markdown notes, finds projects whose
`last_actionable_date` has gone stale (and learning notes due for spaced
review), asks a cloud LLM to write a short, phone-formatted nudge (Hook →
Context → Micro-action, plus a 📚 review line when one's due), and sends it to
your WhatsApp.

Two optional workflows make it two-way (§7):
- **Inbound capture & commands** — message the bot `/note <text>` to capture a
  thought, `/touch <project>` to reset its staleness, `/done <project>` to stop
  nudging it. Captures land in a separate writable inbox; the vault stays
  read-only.
- **Error → WhatsApp alert** — if a run fails, you get a one-line alert instead
  of silent breakage.

## Repo map
| Path | Purpose |
|------|---------|
| [`docker-compose.yml`](docker-compose.yml) | The whole local stack (§1) |
| [`.env.example`](.env.example) | Copy to `.env`, fill secrets |
| [`docs/01-docker-environment.md`](docs/01-docker-environment.md) | §1 RAM budget + Windows setup |
| [`docs/02-knowledge-base-ontology.md`](docs/02-knowledge-base-ontology.md) | §2 frontmatter schema |
| [`docs/03-whatsapp-bridge.md`](docs/03-whatsapp-bridge.md) | §3 QR pairing + anti-spam |
| [`docs/04-automation-engine.md`](docs/04-automation-engine.md) | §4 node-by-node pipeline |
| [`docs/05-cloud-inference-prompt.md`](docs/05-cloud-inference-prompt.md) | §5 the cognitive prompt |
| [`docs/06-operations-troubleshooting.md`](docs/06-operations-troubleshooting.md) | §6 runbook & fixes |
| [`docs/07-inbound-and-errors.md`](docs/07-inbound-and-errors.md) | §7 inbound capture, commands, error alerts |
| [`docs/08-confidence-and-verification.md`](docs/08-confidence-and-verification.md) | §8 what's proven vs trusted + 5-min check |
| [`docs/09-telegram-two-way.md`](docs/09-telegram-two-way.md) | §9 interactive two-way Telegram bot |
| [`docs/10-whatsapp-two-way.md`](docs/10-whatsapp-two-way.md) | §10 interactive two-way WhatsApp bot |
| [`n8n/morning-nudge-workflow.json`](n8n/morning-nudge-workflow.json) | Morning nudge workflow (WhatsApp) |
| [`n8n/morning-nudge-telegram.json`](n8n/morning-nudge-telegram.json) | Morning nudge workflow (Telegram) |
| [`n8n/telegram-assistant-workflow.json`](n8n/telegram-assistant-workflow.json) | Two-way Telegram assistant (chat + commands) |
| [`n8n/whatsapp-assistant-workflow.json`](n8n/whatsapp-assistant-workflow.json) | Two-way WhatsApp assistant (chat + commands) |
| [`n8n/inbound-capture-workflow.json`](n8n/inbound-capture-workflow.json) | WhatsApp → capture/commands (superseded by the assistant) |
| [`n8n/error-handler-workflow.json`](n8n/error-handler-workflow.json) | Error → WhatsApp alert |
| [`n8n/cloud-inference-prompt.md`](n8n/cloud-inference-prompt.md) | Canonical LLM prompt |
| [`notes/templates/`](notes/templates/) | `#Project-File` & `#Learning-Log` templates |
| [`scripts/`](scripts/) | smoke tests + `test-pipeline.mjs` regression test |

## Quick start
1. **Get a free API key:** [Groq](https://console.groq.com/keys) (default) or
   [Gemini](https://aistudio.google.com/app/apikey).
2. `copy .env.example .env` and fill every value (vault path, encryption key,
   API keys, WhatsApp number). The workflow reads its keys from `.env` via
   `$env` — **no in-app credential setup**.
3. Cap Docker RAM via `.wslconfig` (see §1), then `docker compose pull && docker compose up -d`.
4. Open <http://localhost:5678>, create the n8n **owner account** (one-time).
5. Pair WhatsApp via QR (see §3) using the instance name from `.env`.
6. Import `n8n/morning-nudge-workflow.json`, **Execute Workflow** once to
   dry-run, then toggle **Active** (§4). Optionally import the inbound and
   error workflows and wire them up (§7).
7. Drop `notes/templates/EXAMPLE-stale-project.md` into your vault to force a
   nudge on the dry-run, or run `scripts/smoke-test.ps1` to verify the gateway.

Verify the workflow logic anytime (no Docker needed):
```bash
node scripts/test-pipeline.mjs     # runs the shipped Code-node logic against fixtures
```

Full instructions are in the `docs/` sections in order; §6 is the troubleshooting runbook.

## Cost & footprint
- **$0/month** — Docker + n8n + Evolution are open-source; LLM runs on free tiers.
- **< 1.2 GB RAM ceiling**, no local model, no local vector DB.
