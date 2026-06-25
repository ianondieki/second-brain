# Section 4 — End-to-End Automation Engine (n8n → Cloud API)

Importable workflow: [`n8n/morning-nudge-telegram.json`](../n8n/morning-nudge-telegram.json)
Import via n8n → **Workflows → top-right ⋯ → Import from File**.

## Pipeline topology (6 nodes)

```text
(1) Cron 08:00 ─▶ (2) Scan & Read Vault ─▶ (3) Filter Stale (Code)
        ─▶ (4) Cloud LLM Synthesis (Groq) ─▶ (4b) Extract Nudge (Code)
        ─▶ (5) Send to Telegram
```

If Node 3 finds nothing stale it returns `[]`, so nodes 4–5 never fire and **no
message is sent** — zero-noise mornings.

> **Design note — why Code, not the "Read Files" node.** Reading files via the
> binary "Read/Write Files from Disk" node and decoding them in a Code node
> depends on binary-mode internals that differ across n8n versions and are
> brittle. Reading directly with Node's `fs` (allow-listed via
> `NODE_FUNCTION_ALLOW_BUILTIN=fs,path`) is deterministic, version-stable, and
> uses *less* memory because nothing is staged as binary. Node 2 is the
> "filesystem scan/read" step; Node 3 is the pure filter.

---

### Node 1 — Cron Time Trigger
`Schedule Trigger`, cron `0 8 * * *`. The instance timezone (`GENERIC_TIMEZONE`,
default `Africa/Lagos`) governs *when* 08:00 is. Fires once daily.

### Node 2 — Scan & Read Vault (`Code`)
Recursively walks `/data/vault` with `fs`/`path`, skipping `.git`, `.obsidian`,
`.trash`, etc., and emits **one item per `.md` file**: `{ file, raw }`. Throws a
clear error if the vault is empty (almost always a bad `VAULT_PATH` or an
unshared drive — see §1).

### Node 3 — Filter Stale Projects (`Code`, run once for all items)
1. Parses the flat YAML frontmatter with a tiny regex parser (handles inline
   `# comments`, quotes, `[a, b]` lists, and a UTF-8 BOM). No `gray-matter`
   dependency.
2. Keeps only `type: project`; drops `status: done`.
2b. Applies the optional **action log** (`/data/inbox/.actions.jsonl`,
   see §7): the latest matching `done` excludes a project, `touch` advances its
   staleness clock, `reopen` un-excludes without touching the clock. The read is
   skipped silently if the inbox isn't mounted, so the nudge works standalone.
3. Computes `days_stale = today − last_actionable_date` using **local-midnight**
   dates on both sides, so there is no timezone off-by-one.
4. Compares against `stale_after_days` (per-note) or the global default of **5**.
5. Trims each note body to ≤8 signal lines (list items / dated log lines / the
   word *next*) to keep the cloud payload — and token cost — tiny.
6. Also collects **due learning reviews**: `type: learning` notes (not `done`,
   not `/done`) whose days since `last_actionable_date` ≥ `review_interval_days`
   (default `GLOBAL_REVIEW_DAYS = 7`), sorted most-overdue first.
7. **Ranks** stale projects: nearest deadline → priority → most days_stale.
8. Emits **one** item `{ system, user, count }`, where `system` is the cognitive
   prompt (Section 5) and `user` is the pre-sorted JSON
   `{ today, stale_projects, due_reviews }`. Returns `[]` only when **both**
   arrays are empty.

### Node 4 — Cloud LLM (HTTP Request)
`HTTP Request`, POST to Groq's OpenAI-compatible endpoint
`https://api.groq.com/openai/v1/chat/completions`.

- **Auth (zero manual setup):** header `Authorization: Bearer {{$env.GROQ_API_KEY}}`.
  The key comes straight from `.env` via the container environment — no n8n
  credential to create, so the workflow runs the moment `.env` is filled.
- **Body (JSON expression):**
  ```js
  {
    "model": ($env.GROQ_MODEL || "llama-3.3-70b-versatile"),
    "temperature": 0.4,
    "max_tokens": 700,
    "messages": [
      { "role": "system", "content": $json.system },
      { "role": "user",   "content": $json.user }
    ]
  }
  ```
  The model is env-driven (`GROQ_MODEL` in `.env`) so you can swap it without
  editing the workflow — handy when Groq retires a model id.
- **Output:** raw provider JSON; Node 4b normalizes it (see below).

> **Resilience:** the Groq node and the Telegram send node have
> `Retry On Fail` enabled (3 tries, 3 s apart) for transient 429s/network blips.
> If all retries fail, the run errors — which the §7 error-handler workflow can
> turn into a Telegram alert.

> **Swap to Google Gemini free tier** instead of Groq — only Node 4 changes:
> - URL: `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent`
> - Auth: header `x-goog-api-key: {{$env.GEMINI_API_KEY}}`.
> - Body: `{ "contents": [{ "parts": [{ "text": $json.system + "\n\n" + $json.user }] }], "generationConfig": { "temperature": 0.4 } }`
> - **No edit to Node 4b or 5** — the Extract Nudge node already reads the Gemini
>   `candidates[0].content.parts[].text` shape as well as Groq's.

### Node 4b — Extract Nudge (`Code`)
Normalizes the LLM response into a single clean message body so junk never
reaches your phone. It:
- reads **either** the Groq/OpenAI shape (`choices[0].message.content`) **or**
  the Gemini shape (`candidates[0].content.parts[].text`);
- unwraps stray ` ``` ` code fences the model sometimes adds despite the prompt;
- **throws a clear error on an empty/blocked completion** (surfacing the
  `finish_reason` / provider `error.message`) so the §7 error-handler alerts you
  instead of Telegram rejecting a blank message with HTTP 400;
- truncates a runaway response (>4000 chars) as a last-resort safety net;
- **renders to Telegram HTML:** escapes `<`/`>`/`&` first, then turns the prompt's
  `*bold*`/`_italic_` runs into `<b>`/`<i>` so the markup actually displays.

Output: `{ text, html }` — `html` is what gets sent.

### Node 5 — Send to Telegram (HTTP Request)
`HTTP Request`, POST `https://api.telegram.org/bot{{$env.TELEGRAM_BOT_TOKEN}}/sendMessage`.

- **Headers:** `Content-Type: application/json`.
- **Body (JSON expression):**
  ```js
  { "chat_id": $env.TELEGRAM_CHAT_ID, "text": $json.html, "parse_mode": "HTML", "disable_web_page_preview": true }
  ```
  `parse_mode: HTML` makes the `<b>`/`<i>` tags render; the preview is disabled so
  a stray link doesn't blow up the message into a card.

---

## Everything is driven by `.env`
No in-app credentials to wire up. Confirm these are set before the first run:

| Variable | Used in | Meaning |
|----------|---------|---------|
| `GROQ_API_KEY` | Node 4 header | free Groq key |
| `TELEGRAM_BOT_TOKEN` | Node 5 URL | bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Node 5 body | your chat id (recipient) |

> n8n exposes these to expressions as `$env.X` because they are passed into the
> container in `docker-compose.yml`. The compose file sets
> `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` so expressions can read `$env` (without it
> the HTTP nodes fail with "access to env vars denied").

## Dry-run before enabling the cron
1. Open the workflow, click **Execute Workflow** (manual run).
2. Node 2 → confirm it found your `.md` files.
3. Node 3 → confirm it isolated the stale project(s). (Drop
   `notes/templates/EXAMPLE-stale-project.md` into your vault to force one.)
4. Node 4 → confirm a 200 from Groq; Node 4b → confirm clean `text` plus a
   rendered `html` string.
5. Node 5 → confirm `ok: true` in the response and the message in your Telegram.
6. Toggle the workflow **Active** to arm the 08:00 cron.

## Token-cost reality check
One stale-project payload is ~300–800 tokens in, ~150 out. Groq's free tier
(thousands of req/day) and Gemini 1.5 Flash free tier both absorb a single daily
call with enormous headroom. Effective cost: **$0**.
