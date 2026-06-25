# Section 1 — The Low-Memory Docker-Compose Environment

The canonical file is [`/docker-compose.yml`](../docker-compose.yml). This doc
covers the *why*, the RAM math, and the Windows-specific gotchas.

## Memory budget (hard ceilings)

| Service     | Engine                    | `mem_limit` | Typical idle RSS |
|-------------|---------------------------|-------------|------------------|
| `n8n`       | Node + SQLite             | 450 MB      | 180–300 MB       |
| **Total**   |                           | **450 MB**  | **~0.2–0.3 GB**  |

`mem_limit` is the kernel-enforced hard wall (OOM-kill above it). With delivery
on the cloud Telegram Bot API there is no local WhatsApp gateway, so this is a
**single container** — idle resident memory sits around 0.2–0.3 GB, far inside
your "<1 GB free" constraint.

### Levers that keep it small
- **One service.** Telegram delivery removed the Evolution/Postgres/Redis trio
  that the old WhatsApp gateway needed (~750 MB of ceiling gone).
- **n8n on SQLite**, not Postgres — removes an entire DB process from n8n's path.
- **`NODE_OPTIONS=--max-old-space-size`** caps the V8 heap *below* the container
  limit, so you get a clean GC instead of an OOM kill.
- **Execution pruning** (`EXECUTIONS_DATA_PRUNE`, 7-day age, don't save
  successes) stops the SQLite file and execution log from growing unbounded.

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

# IMPORTANT: create the inbox folder BEFORE `up`, or the bind mount errors.
# Use the same path you set for INBOX_PATH in .env:
mkdir "C:\Users\<you>\Documents\SecondBrain\_inbox"   # e.g.

docker compose pull          # fetch the image
docker compose up -d
docker compose ps            # n8n up & "healthy"
docker stats --no-stream     # confirm RSS is well under the limit
```

> Docker bind-mounts a host path; if `INBOX_PATH` (or `VAULT_PATH`) doesn't
> exist on disk, `docker compose up` fails with a mount error. The vault
> already exists (your notes); just make sure the inbox folder does too.

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
The compose file ships with an explicit-ish tag for the one service. Pin **n8n**
to the exact version you tested before any long-lived deploy:
- n8n tags: <https://hub.docker.com/r/n8nio/n8n/tags> (e.g. `:1.71.3`)

A floating tag can silently introduce a breaking change on the next `pull`.
