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
`last_actionable_date` has gone stale, asks a cloud LLM to write a short,
phone-formatted nudge (Hook → Context → Micro-action), and sends it to your
WhatsApp.

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
| [`n8n/morning-nudge-workflow.json`](n8n/morning-nudge-workflow.json) | Importable n8n workflow |
| [`n8n/cloud-inference-prompt.md`](n8n/cloud-inference-prompt.md) | Canonical LLM prompt |
| [`notes/templates/`](notes/templates/) | `#Project-File` & `#Learning-Log` templates |

## Quick start
1. **Get free API keys:** [Groq](https://console.groq.com/keys) or
   [Gemini](https://aistudio.google.com/app/apikey).
2. `copy .env.example .env` and fill every value (vault path, passwords, keys).
3. Cap Docker RAM via `.wslconfig` (see §1), then `docker compose up -d`.
4. Pair WhatsApp via QR (see §3).
5. Import `n8n/morning-nudge-workflow.json` into n8n, attach the Groq
   credential, **Execute** once to dry-run, then toggle **Active** (§4).
6. Drop a couple of notes from `notes/templates/` into your vault to test.

Full instructions are in the `docs/` sections in order.

## Cost & footprint
- **$0/month** — Docker + n8n + Evolution are open-source; LLM runs on free tiers.
- **< 1.2 GB RAM ceiling**, no local model, no local vector DB.
