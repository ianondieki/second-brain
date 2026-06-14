# Section 4 — End-to-End Automation Engine (n8n → Cloud API)

Importable workflow: [`n8n/morning-nudge-workflow.json`](../n8n/morning-nudge-workflow.json)
Import via n8n → **Workflows → ⋯ → Import from File**.

## Pipeline topology

```text
(1) Cron 08:00 ─▶ (2) Read Vault Markdown ─▶ (3) Filter Stale (Code)
        ─▶ (4) Cloud LLM Synthesis (Groq) ─▶ (5) Send to WhatsApp Gateway
```

If Node 3 finds nothing stale it returns `[]`, so nodes 4–5 never fire and
**no message is sent** — zero-noise mornings.

---

### Node 1 — Cron Time Trigger
`Schedule Trigger`, cron `0 8 * * *`. Timezone comes from `GENERIC_TIMEZONE`
(set in compose, default `Africa/Lagos`). Fires once at 08:00 local.

### Node 2 — Local File System read
`Read/Write Files from Disk` (operation **Read**), file selector
`/data/vault/**/*.md`. Emits **one item per note** with the file contents as a
binary property named `data`. Because the vault is bind-mounted read-only at
`/data/vault`, this is a pure read.

### Node 3 — JavaScript stale filter
`Code` node, run-once-for-all-items. It:
1. Decodes each note via `this.helpers.getBinaryDataBuffer(i, 'data')`
   (works correctly under `N8N_DEFAULT_BINARY_DATA_MODE=filesystem`).
2. Parses flat YAML frontmatter with a tiny regex parser (no `gray-matter`
   dependency required, though it's allowlisted if you prefer it).
3. Keeps only `type: project`, drops `status: done`.
4. Computes `days_stale = today − last_actionable_date` and compares against
   `stale_after_days` (per-note) or the global default of **5**.
5. Trims each note body to ≤8 signal lines (logs / `next` / checkboxes) to keep
   the cloud payload — and token cost — tiny.
6. Builds **one** output item: `{ system, user, count }`, where `system` is the
   cognitive prompt (Section 5) and `user` is the JSON of stale projects.

### Node 4 — Cloud LLM (HTTP Request)
`HTTP Request`, POST to Groq's OpenAI-compatible endpoint:
`https://api.groq.com/openai/v1/chat/completions`.

- **Auth:** Generic Credential → **Header Auth** credential named *“Groq API
  (Bearer)”* with `Name = Authorization`, `Value = Bearer <GROQ_API_KEY>`.
  Create it once under n8n → Credentials, then it's reused. (The placeholder
  `id` in the JSON will resolve when you pick the credential post-import.)
- **Body (JSON, expression):**
  ```js
  {
    "model": "llama-3.3-70b-versatile",
    "temperature": 0.4,
    "max_tokens": 700,
    "messages": [
      { "role": "system", "content": $json.system },
      { "role": "user",   "content": $json.user }
    ]
  }
  ```
- **Output:** the message text is at `choices[0].message.content`.

> **Swap to Google Gemini free tier** instead of Groq:
> - URL: `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent`
> - Auth: header `x-goog-api-key: <GEMINI_API_KEY>` (Header Auth credential).
> - Body: `{ "contents": [{ "parts": [{ "text": $json.system + "\n\n" + $json.user }] }] }`
> - Read result from `candidates[0].content.parts[0].text` and adjust Node 5's
>   `text` expression accordingly.

### Node 5 — Outbound to WhatsApp gateway (HTTP Request)
`HTTP Request`, POST `http://evolution-api:8080/message/sendText/{{$env.EVOLUTION_INSTANCE}}`
(reachable container-to-container by service name on the `sbnet` network).

- **Headers:** `apikey: {{$env.EVOLUTION_API_KEY}}`, `Content-Type: application/json`.
- **Body (JSON, expression):**
  ```js
  { "number": $env.WA_TARGET_NUMBER, "text": $json.choices[0].message.content, "delay": 1200 }
  ```
  `delay` gives a human-like typing pause (Section 3.4).

---

## Credentials checklist (one-time)
| What | Where | Value |
|------|-------|-------|
| Groq key | n8n Credential “Groq API (Bearer)” | `Authorization: Bearer <GROQ_API_KEY>` |
| Evolution key | `.env` → `EVOLUTION_API_KEY` | reused via `$env` in Node 5 |
| Recipient | `.env` → `WA_TARGET_NUMBER` | your number, E.164 no `+` |
| Instance | `.env` → `EVOLUTION_INSTANCE` | `secondbrain` |

## Dry-run before enabling the cron
1. Open the workflow, click **Execute Workflow** (manual).
2. Inspect Node 3 output — confirm it found your seeded stale note.
3. Inspect Node 4 — confirm a clean WhatsApp-formatted string.
4. Confirm Node 5 returns `key.id` and the message arrives on your phone.
5. Toggle the workflow **Active** to arm the 08:00 cron.

## Token cost reality check
One stale-project payload is ~300–800 tokens in, ~150 out. Groq's free tier
(thousands of requests/day) and Gemini 1.5 Flash free tier both absorb a
single daily call with enormous headroom. Effective cost: **$0**.
