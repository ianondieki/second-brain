# Section 1 — The Low-Memory Docker-Compose Environment

The canonical file is [`/docker-compose.yml`](../docker-compose.yml). This doc
covers the *why*, the RAM math, and the Windows-specific gotchas.

## Memory budget (hard ceilings)

| Service     | Engine                    | `mem_limit` | Typical idle RSS |
|-------------|---------------------------|-------------|------------------|
| `n8n`       | Node + SQLite             | 450 MB      | 180–300 MB       |
| `evolution` | Baileys (WhatsApp Web)    | 400 MB      | 150–260 MB       |
| `postgres`  | Postgres 16-alpine        | 256 MB      | 40–120 MB        |
| `redis`     | Redis 7-alpine (64MB cap) | 96 MB       | 15–40 MB         |
| **Ceiling** |                           | **1202 MB** | **~0.5–0.7 GB**  |

`mem_limit` is the kernel-enforced hard wall (OOM-kill above it). Real resident
memory at idle sits well under 0.7 GB — comfortably inside your "<1 GB free"
constraint while leaving the rest to Windows + browser.

### Levers that keep it small
- **n8n on SQLite**, not Postgres — removes an entire DB process from n8n's path.
- **`NODE_OPTIONS=--max-old-space-size`** on both Node services caps the V8 heap
  *below* the container limit, so you get a clean GC instead of an OOM kill.
- **Execution pruning** (`EXECUTIONS_DATA_PRUNE`, 7-day age, don't save
  successes) stops the SQLite file and execution log from growing unbounded.
- **Evolution `DATABASE_SAVE_DATA_NEW_MESSAGE=false`** + history/contacts/chats
  off — we never need chat history; storing it would bloat Postgres and Redis.
- **Redis `maxmemory 64mb` + `allkeys-lru` + no persistence** — pure cache.
- **Postgres tuned down** (`shared_buffers=32MB`, `work_mem=2MB`).

## Windows Docker Desktop setup

1. Install **Docker Desktop** with the **WSL2** backend (Settings → General →
   "Use the WSL 2 based engine").
2. **Cap Docker's global RAM** so it can never starve Windows. Create
   `C:\Users\<you>\.wslconfig`:
   ```ini
   [wsl2]
   memory=2GB
   processors=2
   swap=2GB
   ```
   Then in PowerShell: `wsl --shutdown`, and restart Docker Desktop. 2 GB is
   plenty for this stack and hard-guarantees Windows keeps ~6 GB.
3. **Enable file sharing** for the drive holding your vault: Docker Desktop →
   Settings → Resources → File Sharing → add `C:\` (or the specific folder).
   This is what makes the `${VAULT_PATH}:/data/vault:ro` bind mount work.
   *(WSL2 backend usually shares all drives automatically; if the mount is
   empty inside the container, this setting is the first thing to check.)*

## Bring-up

```powershell
# from the repo root, next to docker-compose.yml
copy .env.example .env       # then edit .env with real values
docker compose pull          # fetch images
docker compose up -d
docker compose ps            # all four up? postgres should be "healthy"
docker stats --no-stream     # confirm RSS is well under the limits
```

## First-run n8n account (no basic auth!)

Modern n8n (v1+) **removed** the old `N8N_BASIC_AUTH_*` variables. Instead:

1. Open <http://localhost:5678>.
2. n8n shows a one-time **"Set up owner account"** screen — create your local
   admin (email + password). This is stored in the n8n SQLite DB, not in `.env`.
3. That account gates the editor from then on.

We set `N8N_SECURE_COOKIE=false` because the owner-account login cookie is
marked `Secure` by default, which browsers refuse to store over plain
`http://localhost` — leaving you unable to log in. Relaxing it is safe here
because the port is bound to `127.0.0.1` only (loopback, not the LAN).

## Why read-only mount (`:ro`)
n8n only ever *reads* your notes for the nudge pipeline. Mounting read-only
removes any chance a buggy or compromised workflow rewrites or deletes your
knowledge base. If you later add a "capture to vault" flow, give it a separate,
narrowly-scoped writable subfolder (e.g. `/data/inbox`), never the whole vault.

## Image pinning
The compose file ships with explicit-ish tags. `postgres:16-alpine` and
`redis:7-alpine` are stable. For **n8n** and **Evolution**, pin to the exact
version you tested before any long-lived deploy:
- n8n tags: <https://hub.docker.com/r/n8nio/n8n/tags> (e.g. `:1.71.3`)
- Evolution releases: <https://github.com/EvolutionAPI/evolution-api/releases>

A floating tag can silently introduce a breaking change on the next `pull`.
