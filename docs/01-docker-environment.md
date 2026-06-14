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

The `mem_limit` is the kernel-enforced hard wall (OOM-kill above it). Real
resident memory at idle sits well under 0.7 GB, comfortably inside your
"<1 GB free" constraint while leaving the other ~7 GB to Windows + browser.

### Levers that keep it small
- **n8n on SQLite**, not Postgres — removes an entire DB process from n8n's path.
- **`--max-old-space-size`** on both Node services caps the V8 heap *before*
  the container hits `mem_limit`, so you get a clean GC instead of an OOM kill.
- **Execution pruning** (`EXECUTIONS_DATA_PRUNE`, 7-day age) stops the SQLite
  file and in-memory execution log from growing unbounded.
- **Evolution `DATABASE_SAVE_DATA_NEW_MESSAGE=false`** — we never need full
  chat history; storing it would bloat Postgres and Redis.
- **Redis `maxmemory 64mb` + `allkeys-lru` + no persistence** — cache only.
- **Postgres tuned down** (`shared_buffers=32MB`, `work_mem=2MB`).

## Windows Docker Desktop setup

1. Install **Docker Desktop** with the **WSL2** backend (Settings →
   General → "Use the WSL 2 based engine").
2. **Cap Docker's global RAM** so it can never starve Windows. Create
   `C:\Users\<you>\.wslconfig`:
   ```ini
   [wsl2]
   memory=2GB
   processors=2
   swap=2GB
   ```
   Then `wsl --shutdown` and restart Docker Desktop. 2 GB is plenty for this
   stack and hard-guarantees Windows keeps ~6 GB.
3. **Enable file sharing** for the drive holding your vault: Docker Desktop →
   Settings → Resources → File Sharing → add `C:\` (or the specific folder).
   This is what makes the `${VAULT_PATH}:/data/vault:ro` bind mount work.

## Bring-up

```powershell
# from the repo root, next to docker-compose.yml
copy .env.example .env       # then edit .env with real values
docker compose up -d
docker compose ps            # all four healthy?
docker stats --no-stream     # confirm RSS is well under the limits
```

Open n8n at <http://localhost:5678> (basic-auth from `.env`). The vault is
visible read-only inside the n8n container at `/data/vault`.

## Why read-only mount (`:ro`)
n8n only ever *reads* your notes for the nudge pipeline. Mounting read-only
removes any chance a buggy/compromised workflow rewrites or deletes your
knowledge base. If you later add a "capture to vault" flow, give it a
*separate*, narrowly-scoped writable subfolder (e.g. `/data/inbox`).
