# Graph Report - second-brain  (2026-09-24)

## Corpus Check
- 60 files · ~71,464 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: (none) 3, .example 1, .code-workspace 1)

## Summary
- 1313 nodes · 2822 edges · 65 communities (44 shown, 21 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 145 edges (avg confidence: 0.88)
- Token cost: 132,932 input · 0 output

## Community Hubs (Navigation)
- Git Project Scanner
- Adviser Briefing Tests
- Adviser Webhook Server
- Adviser Turn Tests
- Adviser Brain Tests
- Reminder Run Tests
- Node Pipeline Test Harness
- Reminder Delivery Core
- Reminder Verdict & Email Tests
- LangGraph Investigator Deps
- Email & WhatsApp Notify
- Speech (Whisper + TTS)
- Adviser CLI Commands
- Adviser Read-only Tools
- Adviser Memory & Server Glue
- Reminder Email Composition
- Server Process Fakes
- Adviser Conversation Memory
- Investigator Graph Tests
- WhatsApp Webhook Tests
- Spoken Briefing Speaker
- Public Tunnel Endpoint
- Reminder & Adviser Architecture
- Notify Error Tests
- Adviser Turn Routing
- Meta Webhook Registration
- Exclusive HTTP Server
- WhatsApp Message Parsing
- WhatsApp API Client
- Adviser Agent Prompting
- Project Classification
- Sandbox Tool Tests
- Model Pool & Rate Limits
- Docker Low-Memory Env
- Knowledge Base Ontology
- Turn Graph Nodes
- Telegram Two-way Assistant
- Daily Spoken Check-in
- Project Portfolio Cache
- Groq Nudge Prompt Nodes
- Env & Config Tests
- Docs Section Index
- Reminder Fallback Text
- Voice Encoding Tests
- Console Encoding Tests
- WhatsApp Template Setup Tests
- Console WhatsApp Stand-in
- Brief Command Tests
- Check Command Tests
- WhatsApp Builder Tests
- Rate Pacer Tests
- Delivery Channels & Workarounds
- Adviser Graph Builder
- Speech Code-strip Tests
- Speech Split Tests
- Console Output Tests
- Voice Plan Tests
- Speakable Text Tests
- Smoke Test (sh)

## God Nodes (most connected - your core abstractions)
1. `Flagged` - 44 edges
2. `TurnTests` - 43 edges
3. `RunTests` - 39 edges
4. `GitOracleTests` - 34 edges
5. `project()` - 31 edges
6. `git_state()` - 28 edges
7. `Verdict` - 27 edges
8. `AdviserServer` - 24 edges
9. `Client` - 22 edges
10. `text()` - 22 edges

## Surprising Connections (you probably didn't know these)
- `ModelPool` --uses--> `TokenPacer`  [INFERRED]
  adviser/brain.py → reminder/graph.py
- `FakeGraph` --uses--> `ExclusiveHTTPServer`  [INFERRED]
  tests/adviser_fakes.py → adviser/server.py
- `ServerTests` --uses--> `Inbound`  [INFERRED]
  tests/test_adviser_server.py → adviser/whatsapp.py
- `TurnTests` --uses--> `Inbound`  [INFERRED]
  tests/test_adviser_turn.py → adviser/whatsapp.py
- `Client` --uses--> `DeliveryError`  [INFERRED]
  adviser/whatsapp.py → reminder/notify.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Legacy n8n Morning Nudge Pipeline** — docs_04_automation_engine_scan_read_vault, docs_04_automation_engine_filter_stale_projects, docs_04_automation_engine_cloud_llm_groq, docs_04_automation_engine_extract_nudge, docs_04_automation_engine_send_to_telegram, n8n_cloud_inference_prompt_system_prompt [EXTRACTED 1.00]
- **Telegram Staleness Loop via Shared Action Log** — docs_04_automation_engine_morning_nudge_pipeline, docs_09_telegram_two_way_telegram_assistant, docs_10_evening_checkin_evening_checkin_workflow, docs_07_inbound_and_errors_action_log, docker_compose_inbox_mount [EXTRACTED 1.00]
- **WhatsApp Voice Adviser Turn Flow** — docs_11_whatsapp_voice_adviser_cloudflare_tunnel, docs_11_whatsapp_voice_adviser_webhook_signature, docs_11_whatsapp_voice_adviser_groq_whisper, docs_11_whatsapp_voice_adviser_adviser_agent, docs_11_whatsapp_voice_adviser_edge_tts_voice_notes [EXTRACTED 1.00]

## Communities (65 total, 21 thin omitted)

### Community 0 - "Git Project Scanner"
Cohesion: 0.06
Nodes (51): scan(), _blob_sha(), _blob_sha_chunked(), _commit_parents(), discover(), _git_dirs(), git_state(), _ignored() (+43 more)

### Community 1 - "Adviser Briefing Tests"
Cohesion: 0.06
Nodes (17): BackgroundTests, Base, briefing_file(), DecisionTests, FailureTests, FakeClient, FakeServices, project() (+9 more)

### Community 2 - "Adviser Webhook Server"
Cohesion: 0.06
Nodes (26): AdviserServer, _handler(), do_GET(), do_POST(), _drain(), _send(), mask(), What the public /health says (it is reachable through the tunnel): alive or… (+18 more)

### Community 3 - "Adviser Turn Tests"
Cohesion: 0.08
Nodes (10): run(), FakeClient, Records what the adviser would send to WhatsApp., tool_call(), Clock, One conversation turn end to end with fakes: hear, route, think, speak,…, StoreTests, text() (+2 more)

### Community 4 - "Adviser Brain Tests"
Cohesion: 0.06
Nodes (17): failing(), FailingLLM, Exception, GenericFakeChatModel, RateLimited, A throwaway second-brain folder: reminders.json + two projects under projects/., Replays scripted replies and records every message list it was given., response (+9 more)

### Community 5 - "Reminder Run Tests"
Cohesion: 0.08
Nodes (6): Deps, Everything with side effects, swappable in tests., Guards, retries, alerts and state through the real LangGraph workflow with fake…, RunTests, failing(), send()

### Community 6 - "Node Pipeline Test Harness"
Cohesion: 0.05
Nodes (30): ref_fs, ref_module, ref_os, ref_path, ref_url, ACTIONS, checkinCode, checkinWf (+22 more)

### Community 7 - "Reminder Delivery Core"
Cohesion: 0.08
Nodes (37): html, clean_line(), ConfigError, configured_channels(), deliver(), _finished(), _gave_up(), _group_skipped() (+29 more)

### Community 8 - "Reminder Verdict & Email Tests"
Cohesion: 0.12
Nodes (9): Flagged, What the investigator agent concluded about one flagged project., Verdict, EmailLayoutTests, __init__(), project(), WhatsApp pairs *, _, ~ and ` marks across the message, so one stray mark in a…, The email is for a reader who has never seen the code: clear parts, one action… (+1 more)

### Community 9 - "LangGraph Investigator Deps"
Cohesion: 0.08
Nodes (27): BaseChatModel, BaseModel, httpx, langchain_core_language_models, langchain_core_messages, langgraph_prebuilt, MessagesState, pydantic (+19 more)

### Community 10 - "Email & WhatsApp Notify"
Cohesion: 0.09
Nodes (29): email_message, email_utils, EmailMessage, http_client, build_email(), build_hello_world(), build_template_definition(), build_whatsapp_template() (+21 more)

### Community 11 - "Speech (Whisper + TTS)"
Cohesion: 0.09
Nodes (30): _balanced(), _edge_tls(), plan_voice(), RuntimeError, SSLContext, Hearing and speaking. voice note (OGG/Opus) ──Groq Whisper──▶ text transcribe()…, Written reply -> words a voice should say: no markdown marks, links, code or…, (prose, code): fenced blocks and lines that look like code or shell commands… (+22 more)

### Community 12 - "Adviser CLI Commands"
Cohesion: 0.11
Nodes (25): make_models(), brief(), build_services(), chat(), ask(), check(), main(), owner() (+17 more)

### Community 13 - "Adviser Read-only Tools"
Cohesion: 0.14
Nodes (25): make_adviser_tools(), clip(), guarded(), list_project_files(), project_git(), propose_reminder_change(), read_project_file(), search_project() (+17 more)

### Community 14 - "Adviser Memory & Server Glue"
Cohesion: 0.14
Nodes (21): What the adviser remembers between messages, all under .state/ (git-ignored).…, Seconds since the epoch for an ISO time, or 0.0 when it cannot be read., timestamp(), The webhook server: Meta ─HTTPS─▶ tunnel ─▶ 127.0.0.1:PORT ─▶ queue ─▶ one…, hashlib, http_server, io, json (+13 more)

### Community 15 - "Reminder Email Composition"
Cohesion: 0.11
Nodes (26): _ago(), Card, compose_alert(), compose_email(), _day_stamp(), fix_hint(), _html_card(), _html_label() (+18 more)

### Community 16 - "Server Process Fakes"
Cohesion: 0.11
Nodes (5): FakeProc, FakeTunnel, TunnelTests, register(), popen()

### Community 17 - "Adviser Conversation Memory"
Cohesion: 0.13
Nodes (11): apply_reminder_change(), load_briefing(), date, True exactly once per message id, and remembers it (thread-safe)., Messages a previous run accepted but never finished, oldest first. Each is…, The live conversation, already reset if it went stale., Edit reminders.json for one project: done | snooze | reopen. Only ever called…, Remember when the owner wrote. Never raises: losing this only delays a spoken… (+3 more)

### Community 18 - "Investigator Graph Tests"
Cohesion: 0.13
Nodes (11): itertools, langchain_core_language_models_fake_chat_models, langchain_core_runnables, Config, shutil, FakeLLM, InvestigatorTests, GenericFakeChatModel (+3 more)

### Community 19 - "WhatsApp Webhook Tests"
Cohesion: 0.10
Nodes (8): FakeGraph, Answers the Graph API calls the adviser makes, on http://127.0.0.1:<port>, and…, sign(), _post(), ChallengeTests, ClientTests, WhatsApp two-way layer: signature, verification, payload parsing, builders,…, SignatureTests

### Community 20 - "Spoken Briefing Speaker"
Cohesion: 0.15
Nodes (9): _OtherProcessIsSpeaking, Exception, Speaks each new check-in once, as soon as WhatsApp allows it., True when the record is safely on disk. A record that cannot be written means…, WhatsApp allows a free-form message only within 24 hours of the owner's last…, Speak today's check-in if it is due and allowed. Returns what happened, for the…, Put the check-in in the conversation, so a reply like "tell me more about the…, Speaker (+1 more)

### Community 21 - "Public Tunnel Endpoint"
Cohesion: 0.13
Nodes (9): free_port(), PublicEndpoint, QuickTunnel, cloudflared's own answer, on this machine: is the tunnel connected to…, Keeps a tunnel up and registered with Meta. 1. start cloudflared, wait until it…, Sleep in small steps; True if asked to stop., Until told to stop: return quietly; on cloudflared dying or disconnecting:…, One cloudflared process. start() returns the public https:// URL. (+1 more)

### Community 22 - "Reminder & Adviser Architecture"
Cohesion: 0.13
Nodes (20): Agent Sandbox (path lock + secret redaction), Cold / At-risk Detection (git state from .git), Division of Labour: Agent Says, Code Sends, Investigator Agent (read-only tools, structured verdict), Reminder LangGraph Workflow (scan-investigate-compose-deliver), reminders.json Settings, Windows Task Scheduler Job, Adviser Agent (cross-project read-only tools) (+12 more)

### Community 24 - "Adviser Turn Routing"
Cohesion: 0.14
Nodes (17): Two-way WhatsApp project adviser: talk to your second brain by text or voice…, route(), think(), confirm_proposal(), drop_change_claims(), _projects_text(), TypedDict, question_for() (+9 more)

### Community 25 - "Meta Webhook Registration"
Cohesion: 0.17
Nodes (18): app_id(), _get(), _graph(), RuntimeError, A public HTTPS address for the webhook, kept alive and registered with Meta.…, Point the app's WhatsApp webhook at callback_url and make sure the WABA sends…, register(), RegistrationError (+10 more)

### Community 26 - "Exclusive HTTP Server"
Cohesion: 0.13
Nodes (7): ExclusiveHTTPServer, http.server sets SO_REUSEADDR, which on Windows lets a SECOND process bind a…, do_GET(), do_POST(), _reply(), TranscribeTests, ThreadingHTTPServer

### Community 27 - "WhatsApp Message Parsing"
Cohesion: 0.14
Nodes (15): build_text(), build_voice(), _digits(), _parse_message(), parse_webhook(), WhatsApp Cloud API, the two-way half. Inbound: webhook verification (GET), the…, (messages, statuses) from a `messages` webhook. Never raises on odd shapes:…, `voice: true` makes WhatsApp show it as a voice note (play button, waveform,… (+7 more)

### Community 28 - "WhatsApp API Client"
Cohesion: 0.21
Nodes (6): build_read(), Client, Blue ticks for the owner's message (and every earlier one), plus 'typing…' for…, The business number's side of the conversation. `base` is only changed by tests., GET /{media-id} for a 5-minute URL, then GET that URL with the token., Request

### Community 29 - "Adviser Agent Prompting"
Cohesion: 0.15
Nodes (12): build_messages(), datetime, The adviser agent. snapshot of every project + today's reminder + the…, (what to say, what to also send as text), around the [[text]] marker or a…, split_reply(), BaseMessage, difflib, functools (+4 more)

### Community 30 - "Project Classification"
Cohesion: 0.23
Nodes (10): classify(), pick_featured(), Split scanned projects into (flagged, quiet, held) where held = done/snoozed., WhatsApp shows one project a day: rotate so the same one doesn't repeat daily., GitState, Project, cfg(), ClassifyTests (+2 more)

### Community 32 - "Model Pool & Rate Limits"
Cohesion: 0.17
Nodes (12): AdviserBusy, _cooldown(), ModelPool, Exception, RuntimeError, Every model is rate-limited or failing right now., Tries models in order, skipping ones out of token budget or cooling down after…, Seconds until this model can take a call of about `est` tokens: its error cool-… (+4 more)

### Community 33 - "Docker Low-Memory Env"
Cohesion: 0.16
Nodes (13): n8n Service (sb-n8n), Read-only Vault Mount (/data/vault), Section 1 - Low-Memory Docker Environment, Memory Budget (450 MB hard ceiling), n8n Owner Account + N8N_SECURE_COOKIE=false, .wslconfig WSL2 RAM Cap, Morning Nudge Pipeline (n8n, 08:00 cron), Node 2 - Scan & Read Vault (Code, fs) (+5 more)

### Community 34 - "Knowledge Base Ontology"
Cohesion: 0.19
Nodes (14): Section 2 - Knowledge Base Ontology, Flat YAML Frontmatter Schema, last_actionable_date Heartbeat, #Learning-Log Archetype, No Local Vector DB Decision, #Project-File Archetype, Node 3 - Filter Stale Projects (Code), Pre-sorted Single-Target Selection (+6 more)

### Community 35 - "Turn Graph Nodes"
Cohesion: 0.19
Nodes (9): build_turn(), ack(), acknowledge(), deliver(), speak(), Everything a turn touches; tests swap in fakes., Services, for_whatsapp() (+1 more)

### Community 36 - "Telegram Two-way Assistant"
Cohesion: 0.23
Nodes (12): Writable Inbox Mount (/data/inbox), Action Log (.actions.jsonl), Slash Commands (/note /touch /done /reopen), Proven vs Trusted-but-not-executed, getUpdates Long Polling (timeout < interval), Offset File (.tg_offset), Owner-only / No-self-loop Guards, Short-term Memory (.tg_history.json) (+4 more)

### Community 37 - "Daily Spoken Check-in"
Cohesion: 0.29
Nodes (10): actionable_projects(), greeting(), datetime, The daily reminder, spoken. WhatsApp only lets a business open a conversation…, One spoken sentence: no markdown, no double spaces, bounded, ends in a full…, The spoken check-in. Empty when there is nothing worth saying out loud., script(), _sentence() (+2 more)

### Community 38 - "Project Portfolio Cache"
Cohesion: 0.22
Nodes (4): _key(), Portfolio, The scanner's view of every project, cached for a few minutes (a scan takes…, Exact name, then a unique prefix/containment, then the closest spelling.

### Community 39 - "Groq Nudge Prompt Nodes"
Cohesion: 0.20
Nodes (10): $env-exposed Secrets (GROQ_API_KEY, TELEGRAM_*), Node 4 - Cloud LLM Synthesis (Groq), Node 4b - Extract Nudge (Code), Gemini 1.5 Flash Swap-in, Node 5 - Send to Telegram, Anti-hallucination Guardrail, HOOK / CONTEXT / MICRO-ACTION Flow, .env Changes Require Recreate (+2 more)

### Community 41 - "Docs Section Index"
Cohesion: 0.28
Nodes (9): Section 4 - Automation Engine, Section 5 - Cloud Inference Prompt, Section 7 - Commands, Action Log & Error Alerts, Section 9 - Two-Way Telegram Assistant, Section 10 - Evening Check-in, Section 10 - Project Reminders (email + WhatsApp), Section 11 - WhatsApp Voice Adviser, Cloud Inference Cognitive Prompt (canonical) (+1 more)

### Community 42 - "Reminder Fallback Text"
Cohesion: 0.22
Nodes (9): actionable(), _and_list(), fallback_text(), ["a"] -> "a"; ["a", "b", "c"] -> "a, b and c"., Projects still worth nagging about: the agent didn't judge them finished or…, What this reminder told the owner, for the WhatsApp adviser (adviser/) to talk…, save_briefing(), verdict_for() (+1 more)

### Community 43 - "Voice Encoding Tests"
Cohesion: 0.33
Nodes (3): tone(), EncodeTests, synth()

### Community 44 - "Console Encoding Tests"
Cohesion: 0.29
Nodes (3): ConsoleEncodingTests, cp1252_stream(), Regression: `chat` answered in 2.7s and then lost the whole reply to…

### Community 51 - "Delivery Channels & Workarounds"
Cohesion: 0.40
Nodes (6): Avast TLS Scanning Workaround, Gmail SMTP Email Digest, Meta WhatsApp Cloud API, Once-per-day Delivery + Retry Budget, WhatsApp Template Name Fallback, Cloudflare Tunnel + Auto Meta Webhook Registration

### Community 52 - "Adviser Graph Builder"
Cohesion: 0.67
Nodes (3): build_adviser(), think(), used()

## Knowledge Gaps
- **38 isolated node(s):** `smoke-test.sh script`, `require`, `HERE`, `N8N`, `errwf` (+33 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 477 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ToolTests` connect `Sandbox Tool Tests` to `Investigator Graph Tests`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Why does `Speaker` connect `Spoken Briefing Speaker` to `Adviser CLI Commands`, `Daily Spoken Check-in`?**
  _High betweenness centrality (0.029) - this node is a cross-community bridge._
- **Why does `AdviserServer` connect `Adviser Webhook Server` to `Exclusive HTTP Server`, `Adviser CLI Commands`, `Adviser Memory & Server Glue`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `Flagged` (e.g. with `investigate_projects()` and `project_facts()`) actually correct?**
  _`Flagged` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `TurnTests` (e.g. with `Inbound` and `FakeClient`) actually correct?**
  _`TurnTests` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `RunTests` (e.g. with `Deps` and `Verdict`) actually correct?**
  _`RunTests` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `smoke-test.sh script`, `require`, `HERE` to the rest of the system?**
  _38 weakly-connected nodes found - possible documentation gaps or missing edges._