# Agentic Second Brain

## Project reminders (current)

Every morning a **LangGraph** workflow looks at the project folders on this laptop,
finds the ones that have gone cold (no work for 3 days, or uncommitted/unpushed work
left sitting), sends an **investigator agent** with read-only tools into each one to
work out where you left off and what the next 15-minute step is, then reminds you by
**email** and **WhatsApp**. Plain code decides whether and when anything is sent; the
agent only decides what to say. No Docker, no n8n.

```powershell
python -m venv .venv && .venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m reminder --dry-run                      # watch the agent; sends nothing
powershell -ExecutionPolicy Bypass -File scripts\install-reminder-task.ps1   # schedule it
```

Setup, settings (`reminders.json`), behaviour and troubleshooting:
[`docs/10-project-reminders.md`](docs/10-project-reminders.md).

| Path | Purpose |
|------|---------|
| [`reminder/graph.py`](reminder/graph.py) | the LangGraph workflow + investigator agent |
| [`reminder/tools.py`](reminder/tools.py) | the agent's read-only, sandboxed tools |
| [`reminder/scan.py`](reminder/scan.py) | project discovery, git state without git |
| [`reminder/remind.py`](reminder/remind.py) | policy, email, once-a-day delivery, CLI |
| [`reminder/notify.py`](reminder/notify.py) | Gmail SMTP + Meta WhatsApp Cloud API |
| [`reminders.example.json`](reminders.example.json) | settings template (live copy `reminders.json` is gitignored) |
| [`tests/`](tests/) | `.venv\Scripts\python.exe -m unittest discover -s tests -t .` |
| [`scripts/install-reminder-task.ps1`](scripts/install-reminder-task.ps1) | register with Task Scheduler |

## WhatsApp voice adviser (two-way, current)

Reply to the reminder, or message any time, by **text or voice note**. A second
LangGraph agent, with read-only tools over *every* project, answers like a senior dev
mentor, and a voice note gets a **fluent voice note back**. It remembers the
conversation, and it can pause or finish a project's reminders only after you say yes.
Free stack: Groq Whisper (speech-to-text) + Groq models + edge-tts voices + a
Cloudflare tunnel that re-registers itself with Meta.

```powershell
.venv\Scripts\python.exe -m adviser check      # what is set up (needs WA_APP_SECRET in .env)
.venv\Scripts\python.exe -m adviser chat       # try the brain in the terminal first
.venv\Scripts\python.exe -m adviser serve      # go live on WhatsApp
powershell -ExecutionPolicy Bypass -File scripts\install-adviser-task.ps1 -StartNow   # keep it running
```

Setup, commands, limits and troubleshooting:
[`docs/11-whatsapp-voice-adviser.md`](docs/11-whatsapp-voice-adviser.md).

| Path | Purpose |
|------|---------|
| [`adviser/turn.py`](adviser/turn.py) | one conversation turn as a LangGraph workflow (hear, route, think, speak, deliver) |
| [`adviser/brain.py`](adviser/brain.py) | the adviser agent, its cross-project tools, the Groq model pool |
| [`adviser/speech.py`](adviser/speech.py) | Whisper speech-to-text, edge-tts, OGG/Opus voice notes |
| [`adviser/whatsapp.py`](adviser/whatsapp.py) | webhook signature/parsing, media, voice-note sends |
| [`adviser/server.py`](adviser/server.py) · [`adviser/tunnel.py`](adviser/tunnel.py) | webhook server; Cloudflare tunnel + Meta registration |
| [`adviser/memory.py`](adviser/memory.py) | conversation memory, dedupe, confirmed reminder changes |

---

## Legacy: n8n + Docker stack

> The sections below describe the original n8n/Docker design. It is kept for
> reference but no longer needed for reminders. It read only hand-written notes in a
> Markdown vault, needed ~1 GB of RAM for Docker, and its WhatsApp gateway
> (Evolution API / Baileys) can't currently link new devices. Its Groq model
> (`llama-3.3-70b-versatile`) has also been retired by Groq.

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
| [`docs/10-project-reminders.md`](docs/10-project-reminders.md) | §10 daily project reminders (email + WhatsApp) |
| [`docs/11-whatsapp-voice-adviser.md`](docs/11-whatsapp-voice-adviser.md) | §11 two-way WhatsApp voice adviser |
| [`n8n/morning-nudge-workflow.json`](n8n/morning-nudge-workflow.json) | Morning nudge workflow (WhatsApp) |
| [`n8n/morning-nudge-telegram.json`](n8n/morning-nudge-telegram.json) | Morning nudge workflow (Telegram) |
| [`n8n/telegram-assistant-workflow.json`](n8n/telegram-assistant-workflow.json) | Two-way Telegram assistant (chat + commands) |
| [`n8n/inbound-capture-workflow.json`](n8n/inbound-capture-workflow.json) | WhatsApp → capture/commands |
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
