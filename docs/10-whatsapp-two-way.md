# Section 10 — Two-Way WhatsApp Assistant (interactive bot)

The WhatsApp equivalent of the Telegram assistant (§9): text your bot a question
and it answers with the LLM, or send a command (`/note`, `/done`, …) that updates
your vault. Import [`n8n/whatsapp-assistant-workflow.json`](../n8n/whatsapp-assistant-workflow.json).

It runs on the **Evolution API** gateway already in your `docker-compose.yml` — no
new infrastructure beyond the WhatsApp stack you set up for the nudge.

## Why a webhook (and why this is *faster* than Telegram)
Telegram has no public URL on localhost, so §9 **polls**. WhatsApp is different:
**Evolution itself is the bridge** to WhatsApp and runs in your stack, so it can
**push** every inbound message straight to an n8n webhook over the internal Docker
network (`http://n8n:5678/webhook/wa-inbound`). No polling, no schedule, no 5-second
cadence — replies are effectively **instant**. That's why this workflow has fewer
nodes than the Telegram one (no Read Offset / Get Updates / poll trigger).

## Topology
```
[WhatsApp Webhook] -> [Route & Handle] -> [Needs LLM?]
                                            |-- true  --> [Chat LLM (Groq)] -> [Extract Reply] --\
                                            |-- false --------------------------------------------> [Send WhatsApp]
```

- **WhatsApp Webhook** — receives Evolution's `MESSAGES_UPSERT` POST at path
  `wa-inbound`. (n8n nests the payload under `.body`.)
- **Route & Handle** — the brain. Parses the message (`conversation` or
  `extendedTextMessage.text`), enforces the guards below, then runs a command
  inline or marks the message `needs_llm` and builds the Groq prompt with memory
  and focus.
- **Needs LLM?** — IF node. Commands already have a reply; chat goes to Groq.
- **Chat LLM (Groq)** → **Extract Reply** — normalizes the OpenAI/Gemini shape;
  an empty/blocked reply yields a *soft fallback* instead of throwing. WhatsApp
  markup is **native**, so the text is kept verbatim — no HTML rendering/escaping.
- **Send WhatsApp** — Evolution `sendText` to `$env.WA_TARGET_NUMBER`. Because the
  bot is owner-only the reply always goes to you, so a fixed `$env` number is used
  (this also survives the Groq HTTP node, which would otherwise drop a threaded id).

## This SUPERSEDES `inbound-capture-workflow.json`
The old `inbound-capture` workflow only handled **commands**. This assistant is a
**superset** — same commands *plus* free-text chat *plus* memory — and it reuses
the **same webhook path** (`wa-inbound`), so your existing Evolution `webhook/set`
keeps working unchanged. **Deactivate (or delete) `inbound-capture` before
activating this one** — two workflows can't share a webhook path while both active.

## Guards (why it's safe to leave on)
1. **No self-loop.** `key.fromMe === true` is skipped — the bot's own replies come
   back through the webhook, and without this they'd trigger fresh LLM calls in a
   loop. (More important here than on Telegram.)
2. **Owner-only.** Only your `WA_TARGET_NUMBER` is answered; strangers get silence
   and never cost you an LLM call.
3. **Groups/status ignored.** `@g.us` and `status@broadcast` JIDs are dropped.
4. **Text-only.** Media/empty messages are skipped.

## Commands
Identical to §9 (`/note`, `/touch`, `/done`, `/reopen`, `/help`/`/start`) and they
write the **same** `/data/inbox/.actions.jsonl` the morning nudge reads — so
`/done stripe` on WhatsApp silences tomorrow's WhatsApp *and* Telegram nudge.

## Grounded follow-ups & memory (parity with Telegram)
- The WhatsApp nudge (`morning-nudge-workflow.json`) now writes the project it
  nudged you about to **`.wa_context.json`**; the assistant injects it as
  `CURRENT FOCUS`, so "explain more" is answered about that exact project.
- Short-term memory lives in **`.wa_history.json`** (last 8 turns, 6h TTL, resets
  on a newer nudge focus). These are **separate files** from Telegram's `.tg_*`
  ones, so the two channels never cross-contaminate.

## Setup
Everything it needs is already in your `.env` / `docker-compose.yml`
(`WA_TARGET_NUMBER`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE`, `GROQ_API_KEY`,
`NODE_FUNCTION_ALLOW_BUILTIN=fs,path`, `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`).

1. Pair your phone with Evolution (scan the QR — see §7) and confirm the WhatsApp
   nudge can send.
2. Point Evolution's webhook at n8n (if not already): `events: ["MESSAGES_UPSERT"]`,
   `url: http://n8n:5678/webhook/wa-inbound` — see §7.1 for the exact `webhook/set`
   body.
3. **Deactivate `inbound-capture`**, import `whatsapp-assistant-workflow.json`, and
   **activate** it. Text your bot — it replies.

> **You still run BOTH halves.** The *nudge* (`morning-nudge-workflow.json`)
> proactively sends the morning message and writes the focus; the *assistant*
> listens and answers. Activate both.

## If the QR code won't appear (the usual WhatsApp blocker)
None of the above matters until Evolution pairs with your phone, and a missing QR
is the classic stumbling block. In order of likelihood:

1. **Image was `:latest`.** Evolution's `latest` tag frequently ships a build
   where QR generation is broken. The compose file is now **pinned to
   `atendai/evolution-api:v2.1.1`** — after `git pull`, run `docker compose pull`
   then `docker compose up -d` to recreate the container on the pinned image.
2. **You were looking in the logs.** In Evolution **v2** the QR is *not* printed to
   the terminal. Get it from the **Manager UI**: open
   **http://localhost:8080/manager**, log in with your `EVOLUTION_API_KEY`, create
   an instance named exactly your `EVOLUTION_INSTANCE` (`secondbrain`), integration
   **WHATSAPP-BAILEYS**, then click **Connect** — the QR renders in the browser.
3. **Instance didn't exist yet.** You must *create* the instance before you can
   *connect* it. The Manager UI does both; via API it's `POST /instance/create`
   with `{ "instanceName": "secondbrain", "integration": "WHATSAPP-BAILEYS",
   "qrcode": true }` and header `apikey: <EVOLUTION_API_KEY>`.
4. **Postgres not healthy.** Evolution `depends_on` a healthy Postgres; if that
   container isn't up, Evolution can't persist the instance and loops without a QR.
   Check `docker compose ps` — Postgres must be **healthy**.
5. **Phone side.** WhatsApp → **Settings → Linked Devices → Link a Device** → scan.

`LOG_LEVEL` is temporarily set to `ERROR,WARN,INFO` so pairing problems are
visible. Once linked, set it back to just `ERROR` to cut log churn.

## Telegram vs WhatsApp — which to run
You can run **either or both** (they share the vault, action log, and nudge logic;
only the delivery channel differs).

| | Telegram (§9) | WhatsApp (§10) |
|---|---|---|
| Inbound | polling (`getUpdates`) | webhook (Evolution push) |
| Latency | ~1s (5s poll + long-poll) | effectively instant |
| Setup | bot token (30s) | QR pairing + Evolution stack |
| Stability | very high | depends on the unofficial WhatsApp engine |
| Formatting | HTML (`<b>`), rendered from `*bold*` | native `*bold*` |
