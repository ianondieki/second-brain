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

## Hosted platform (in development)

A hosted developer ⇄ organisation platform is being built in this repository under `backend/`, `frontend/` and
`infra/`, following the spec in [`docs/spec/`](docs/spec/) and the plan in [`docs/platform/`](docs/platform/). It does
not change or import the local companion above. Local setup: [`docs/runbooks/dev-setup.md`](docs/runbooks/dev-setup.md).

### Run the demo (`make demo`)

A seeded local copy of the platform for demos: two developers, four fixture organisations, published proposals with
certificates, pitches and engagements at several stages. Nothing is paid for and nothing leaves the laptop except the
certificate timestamps (below).

**You need** Docker Desktop (Windows: the WSL 2 backend), Git and Python 3.9 or later (the same Python as the companion
above); `make` is optional (below). Give Docker 4 GB of memory: on Windows with the WSL 2 backend, memory is set in
`%UserProfile%\.wslconfig`, not in Docker Desktop (a file with the two lines `[wsl2]` and `memory=4GB`, then
`wsl --shutdown` and start Docker Desktop again); on macOS, Docker Desktop → Settings → Resources. The demo's
containers are capped at 2.75 GB in all and use about 420 MB once seeded (API 131 MB, worker 104 MB, S3 stand-in 66 MB,
Postgres 65 MB, web 40 MB, Mailpit 11 MB; the seed step peaks at 153 MB and then exits; measured with `make demo-stats`).

**Start it** from the repository folder, in PowerShell or Git Bash:

1. `python infra/demo/demo.py up` (or `make demo`). The first run writes throwaway secrets to `infra/demo/.env` and
   `infra/demo/backend.env` (both gitignored and readable only by you; never commit them), creates `backend/.env` from
   `backend/.env.example` if it is missing, builds the images (several minutes the first time), starts Postgres,
   Mailpit, the S3 stand-in, the API, the worker and the web app, seeds the data and prints the addresses and logins.
   Later starts keep the data and leave whatever you did in the app as it is.
2. Open the web app and sign in with a login below; the second factor is a TOTP code from
   `python infra/demo/demo.py totp` (`make demo-totp`).

Every `make demo-…` target is a short `python infra/demo/demo.py …` command, so `make` is not needed; Windows and Git for
Windows do not include it (install GNU make, for example with Chocolatey's `choco install make`, if you want the
targets). On macOS and Linux, where `python` may be missing, use `make demo DEMO_PY=python3` or `python3 infra/demo/demo.py`.

| make target | Without make |
|---|---|
| `make demo` / `make demo-down` / `make demo-reset` | `python infra/demo/demo.py up` / `down` / `reset --yes` |
| `make demo-totp EMAIL=<address>` | `python infra/demo/demo.py totp <address>` (all logins without an address) |
| `make demo-logins` / `make demo-stats` / `make demo-logs` | `python infra/demo/demo.py logins` / `stats` / `logs` |
| `make demo-clock DAYS=3` / `make demo-reminders` | `python infra/demo/demo.py clock --days 3` / `reminders` |

| What | Where |
|---|---|
| Web app | http://localhost:3000 |
| Mailpit: every email the demo sends (receipts, "approved to proceed", reminders, security notices) | http://localhost:8025 |
| API documentation | http://localhost:8000/api/docs |

**Demo logins.** Every account uses the password `bridge-demo-2026`. It and the TOTP secrets are public on purpose and
exist only in dev and test: the seed and the helpers refuse staging and production.

| Login | Who | What they can show |
|---|---|---|
| `amina@developers.example` | Amina Wanjiru, developer (D2) | My ideas with certificates and pitches; "Who has seen this" (a SACCO B reviewer opened one) |
| `brian@developers.example` | Brian Otieno, developer (D1) | My ideas; a pitch still new at Telco A, two held until the organisations are verified |
| `reviewer@telco-a.example` | Telco A (fixture), reviewer | the Inbox: Brian's new proposal; open it, accept the Evaluation NDA and read the full proposal |
| `owner@telco-a.example`, `signatory@telco-a.example`, `finance@telco-a.example` | Telco A (fixture): owner and admin, signatory, finance | the Inbox with each proposal's stage |
| `owner@sacco-b.example`, `signatory@sacco-b.example`, `reviewer@sacco-b.example`, `finance@sacco-b.example` | SACCO B (fixture), the same seats | the Inbox with two proposals in progress |
| `owner@county-c.example` | County Government of C (fixture), owner (E1: domain verified, not yet E2) | the Inbox: proposals wait until it is E2 |

`make demo-totp` prints the current code of every login; `make demo-totp EMAIL=reviewer@telco-a.example` prints one.
A code is accepted once: if the sign-in was refused, wait for the next code (30 seconds).

**What is seeded.** Four proposals, each with its public teaser, confidential part and certificate: Amina's "Repayment
nudges for SACCO members" (in negotiation with SACCO B, whose reviewer has opened it) and "Fuel-level alerts for
off-grid tower sites" (closed with Telco A: NDA, agreement, two milestones, sign-off and a recorded payment); Brian's
"Cashless market-fee collection for counties" (submitted to Telco A, held for County Government of C and NGO D) and
"USSD repayment reminders for feature phones" (approved to proceed by SACCO B). NGO D (fixture) is an E0 listing with
no members. The provisional directory of public organisations (E0) is loaded too. The Inbox shows each engagement's
stage; the tracker screens come later (the API at http://localhost:8000/api/docs already runs every step).

**Time and reminders.** `make demo-clock DAYS=3` moves the app's clock forward (deadlines, due dates and reminders
follow it; it never moves back until `make demo-reset`). `make demo-reminders` sends the day's developer nudges and the
weekly organisation digests at once (it runs `python -m bridge.reminders run --now` in the worker, which refuses
production); they appear in Mailpit. The worker also sends them on its own after 07:30 and 08:30 Nairobi time.

**LLM providers (optional).** Without any, every AI feature answers with a fixed fake reply labelled "demo fallback".
To use a free OpenAI-compatible provider or Anthropic, set these in `backend/.env` (names only here; never commit
values) and run `make demo` again: `LLM_PROVIDER`, `LLM_PROTOTYPE_TOTAL_CAP_USD`, `LLM_FREE_<N>_BASE_URL`,
`LLM_FREE_<N>_API_KEY`, `LLM_FREE_<N>_MODEL`, `LLM_FREE_<N>_DAILY_REQUESTS`, `LLM_FREE_<N>_RESPONSE_FORMAT` (N = 1 to
3), `ANTHROPIC_API_KEY`, `LLM_KILL_SWITCH`, `LLM_GLOBAL_DAILY_CAP_USD`. `backend/.env.example` explains each one. Only
the seeded demo accounts' data is sent to a free provider.

**Real, simulated or planned**

| Part | In the demo |
|---|---|
| Accounts, TOTP, proposals, Tier-2 encryption, certificates, `/verify`, pitches, the tracker and its History | real (the product's code and database rules) |
| Certificate timestamps | real: DigiCert's public timestamp authority (FreeTSA as fallback), free and needs the internet; offline, a certificate reads "Timestamp pending" until it is reached. The demo does not pin the authority's certificate chain (production does) |
| Email | captured by Mailpit; nothing is delivered |
| Phone verification (D1) | the fake SMS provider: codes stay inside the app |
| Identity (D2) and organisation verification (E1, E2) | set by the seed; the review flows come later |
| Attachment scanning | the demo scanner: the EICAR test file is "infected", everything else clean |
| Payments | recorded and confirmed by the parties; no money moves |
| AI features | the fake unless you add a provider (above) |

**Stop, reset, check.** `make demo-down` stops the demo and keeps its data; `make demo-reset` wipes only the demo's
data (its own `bridge-demo` project and volumes, whatever `COMPOSE_PROJECT_NAME` says; the dev stack is untouched) and
starts it fresh. Starting again after using the demo keeps what you did: the seed only adds what is missing and leaves
any engagement someone moved on, any changed password and any deleted idea as it is (its log says which). If the
very first `make demo` was interrupted (the laptop slept, or Docker ran out of memory), run `make demo-reset`: the seed
never resumes an engagement it did not just open, so a half-driven one stays where it stopped. `make
demo-logins`, `make demo-stats` (memory per container) and `make demo-logs` help while it runs. The demo uses the dev
stack's ports, so stop the dev stack (`make down`) before `make demo`. If the demo says `infra/demo/.env` is gone while
its data exists, run `make demo-reset`. With the demo running, `python infra/demo/demo.py e2e-env` writes the
Playwright variables (`E2E_VERIFY_CERT_ID`, `E2E_DATABASE_OWNER_URL`, `E2E_BASE_URL`, `E2E_MAILPIT_URL`) to the
gitignored `frontend/.env.e2e` and prints how to load them.

**Variables the demo reads from your shell** (never from a file in the repository): `DEMO_PY`, the Python that `make`
runs the launcher with (default `python`); `DEMO_COMPOSE_EXTRA`, extra compose files added after the demo's own, such
as a CA override for a build machine behind a TLS-inspecting proxy or other host ports (separated by `;` on Windows
and `:` elsewhere; keep them outside the repository).

## Legacy

The original n8n + Docker design is archived, unmaintained, in [`legacy/`](legacy/README.md).
