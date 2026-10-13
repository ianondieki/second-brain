# The public demo image (`bridge-demo`)

One container image that runs the whole seeded Bridge product on one port (7860), for any Docker host: GitHub
Codespaces now, a Hugging Face Docker Space or an Oracle Always Free Arm VM later (P28 track PD, REQ-FND-04; the
owner's steps are in `docs/runbooks/public-demo.md`).

**A demo only.** Every name and organisation in it is fictional. Email stays in an internal Mailpit, SMS and payments
are simulated, LLM calls answer with the deterministic fallback, attachment scanning and embeddings are the fakes, and
SeaweedFS's usage statistics are off. **One connection leaves the container**: when a proposal is registered, the
worker asks a public timestamp service for an RFC 3161 timestamp of its certificate (DigiCert, with FreeTSA as the
fallback; the app's defaults, as in `make demo`), sending a hash, never the proposal. Nothing else is sent anywhere.
Its secrets are thrown away at every boot and its data is wiped every night. Never point it at real data, real
providers or real users' accounts, and never use it as a base for production.

## What is inside

| Part | From | Listens on |
|---|---|---|
| Web app (Next.js standalone, Node 22) | `frontend/`, built with `/api` rewritten to `127.0.0.1:8000` | `0.0.0.0:$PORT` (7860), the only public port |
| API (FastAPI, uvicorn; its interactive docs are off in public mode) | `backend/` (`uv.lock`, with the demo seed and dev tools) | `127.0.0.1:8000` |
| Job worker (procrastinate) | `backend/` | none |
| PostgreSQL 16 + pgvector | the PGDG apt repository (signed key, checked by hash) | `127.0.0.1:5432` |
| S3 (SeaweedFS 4.47) | `chrislusf/seaweedfs:4.47`'s `weed` binary | `127.0.0.1` only |
| Mail catcher (Mailpit 1.31.2) | `axllent/mailpit:v1.31.2`'s binary | `127.0.0.1:1025` (SMTP), `:8025` |
| Supervisor (`run.py`, standard-library Python) | this folder | none |

`run.py` runs everything as `demo` (uid 1000, which Hugging Face requires) under tini. At every boot it makes new
secrets with `infra/demo/demo.py`'s generators (held in memory, never printed or written down), wipes `~/data`,
initialises Postgres with the roles of `infra/postgres/`, starts S3 and Mailpit, runs the demo compose's migrate step
(migrations, buckets, the provenance key, `python -m bridge.seed --demo`) with `PUBLIC_DEMO=true` and
`PUBLIC_DEMO_CONTENT=fictional`, then starts the API, the worker and the web app. A crashed process is restarted with
back-off.

## Run it locally

```bash
docker build -f infra/demo/space/Dockerfile -t bridge-demo .     # from the repository root
docker run --rm -p 7860:7860 bridge-demo
```

Open http://localhost:7860 once the log says `ready in N s`. Or pull the published image:
`docker run --rm -p 7860:7860 ghcr.io/ianondieki/bridge-demo:latest` (once its package is public).

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `7860` | the web app's port inside the container |
| `PUBLIC_BASE_URL` | derived | the address visitors use (links in emails, calendar feeds). Otherwise `https://$SPACE_HOST` on Hugging Face, the forwarded address in a codespace, else `http://localhost:$PORT` |
| `PUBLIC_DEMO_CONTENT` | `fictional` | `full` also loads the news excerpts and the provisional directory of real organisations: only after D-38 and G6 (the runbook's go-live checklist) |
| `COOKIE_SECURE` | `true` | `__Host-` cookies; browsers accept them on `http://localhost` and every HTTPS host |

Nothing else from the environment reaches the app.

Visitors' sign-in throttles are counted per address, which the API reads from the `X-Forwarded-For` header the web app
passes on: behind an edge proxy that sends it (Caddy; Hugging Face and Codespaces unverified) each visitor has their
own; run bare with `docker run -p`, every visitor shares one (`127.0.0.1`). The runbook's go-live checklist has the
check.

## Measured (2026-10-13, linux/amd64, 4 CPUs)

| | |
|---|---|
| Image size | 1.59 GB unpacked, 414 MB compressed (the registry download) |
| Boot, `docker run` to the first `200` on `/` | 40-53 s over five runs (the supervisor logs `ready in` 49-60 s) |
| Memory, steady after sign-ins and page loads (`docker stats`) | 533-594 MiB; the boot stays below that |
| Nightly reset (stop, wipe, boot again) | 50-62 s |
| `docker stop` | 5 s |

Give it at least 1 GB of memory; 2 GB leaves room for traffic. Codespaces' smallest machine (8 GB), a Hugging Face
CPU basic Space (16 GB) and a 6 GB Oracle A1 VM are all ample.

## The nightly reset

At 03:00 Africa/Nairobi (00:00 UTC) the supervisor stops the processes (the web app, worker and API, then S3 and
Mailpit, then Postgres), wipes `~/data` and boots again with new secrets, so every session ends and every change made
during the day is gone. The site is unavailable for about a minute. To reset now:

```bash
docker exec <container> python3 /opt/infra/demo/space/run.py reset    # or: docker kill -s USR1 <container>
```

`docker stop` (SIGTERM) stops everything in the same order. Data never survives a restart of the container either.

## Files

- `Dockerfile`: the multi-stage build (context: the repository root); `Dockerfile.dockerignore` keeps the context to
  what it copies.
- `run.py`: the supervisor (`python3 run.py`, or `python3 run.py reset`).
- `.github/workflows/demo-image.yml` publishes the image to GHCR; `.github/workflows/demo-space.yml` points a Hugging
  Face Space at it; `.devcontainer/` runs it in a codespace.
