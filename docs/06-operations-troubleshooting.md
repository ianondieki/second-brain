# Section 6 — Operations & Troubleshooting

Day-2 runbook for the stack. Most issues are one of: bad `.env`, an unshared
Windows drive, a bad Telegram token/chat id, or a cloud API key/quota problem.

## Health checks

```powershell
docker compose ps                 # n8n up & "healthy"
docker stats --no-stream          # RSS under the mem_limit
docker compose logs -f n8n        # follow n8n
```

Bash/WSL or Git Bash users can run the bundled checks:
```bash
set -a; source .env; set +a
./scripts/smoke-test.sh
```
PowerShell users:
```powershell
./scripts/smoke-test.ps1
```

## Symptom → cause → fix

| Symptom | Likely cause | Fix |
|---|---|---|
| Node 2 throws "No Markdown files under /data/vault" | `VAULT_PATH` wrong, or drive not shared | Fix `VAULT_PATH` (forward slashes); Docker Desktop → Settings → Resources → File Sharing → add the drive; `docker compose up -d` |
| Can't log into n8n / "cookie not saved" | secure cookie over http | Ensure `N8N_SECURE_COOKIE=false` is set (it is in compose); hard-refresh |
| n8n container restarts / OOM-killed | heap or limit too low after heavy use | Confirm `--max-old-space-size=320` < `mem_limit 450m`; raise both together if you add big workflows |
| Node 4 returns 401 | bad/empty `GROQ_API_KEY` | Set a valid key in `.env`, `docker compose up -d` (env changes need a recreate) |
| Node 4 returns 429 | free-tier rate/quota hit | Switch model to `llama-3.1-8b-instant`, or fail over to Gemini (§4) |
| Node 5 (Telegram) returns 401/404 | wrong `TELEGRAM_BOT_TOKEN` | Re-copy the token from @BotFather; recreate n8n |
| Node 5 (Telegram) returns 400 | bad `TELEGRAM_CHAT_ID` or HTML parse error | Verify the chat id (§9); the Extract node already escapes `<`/`>`/`&` |
| Assistant never replies | workflow not Published/active, or message already polled | See §9 — Publish the assistant, send a fresh message |
| Message sent at the wrong hour | timezone | Set `TZ` in `.env`; `GENERIC_TIMEZONE` follows it; recreate n8n |
| Bold shows as literal `*text*` | HTML render skipped / wrong node | The Extract Nudge node converts `*bold*` → `<b>`; confirm Node 5 sends `$json.html` with `parse_mode: HTML` |

> **`.env` changes require a recreate, not just restart:** environment
> variables are baked in at container create time.
> `docker compose up -d` recreates changed services; `docker compose restart`
> does **not** pick up new env values.

## Verifying the workflow logic (no Docker needed)

The nudge logic — vault scanning, frontmatter parsing, staleness, ranking, and
the HTTP request bodies — has a standalone regression test that runs the
**exact** JavaScript embedded in the workflow JSON files against a battery of
edge-case notes:

```bash
node scripts/test-pipeline.mjs      # needs only Node 18+; no Docker, no keys
```

It exits non-zero on any failure, so you can run it in CI or as a pre-commit
check. All fixture dates are relative to "today", so the test never goes stale.
**Run it after any edit to the workflow's Code nodes** — if it still passes, the
logic is intact; then do the live §4 dry-run for the parts only the real stack
can exercise (image pulls, n8n's runtime expressions, the Groq/Telegram APIs).

## Backups
- **Your notes** are the source of truth — back up the Windows vault folder
  (it's just Markdown; put it in git, Syncthing, or any cloud drive).
- **n8n workflows/owner account** live in the `n8n_data` volume. Export the
  workflow JSON from the UI for a portable copy (already in
  `n8n/morning-nudge-telegram.json`).

## Upgrading
1. Read the n8n release notes for breaking changes.
2. Bump the image tag in `docker-compose.yml` (don't track floating tags).
3. `docker compose pull && docker compose up -d`.
4. Re-run the §4 dry-run before trusting the next 08:00 cron.

## Clean teardown
```powershell
docker compose down            # stop + remove the container, keep the volume/data
docker compose down -v         # ALSO delete the n8n_data volume — destructive
```
`down -v` does **not** touch your Windows vault (it's a read-only bind mount,
not a named volume).
