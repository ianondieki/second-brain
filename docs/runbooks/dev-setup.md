# Dev setup

## Purpose

Get the Bridge platform (`backend/`, `frontend/`, `infra/`) running locally so you can build and test a task card.
This does not cover the legacy local companion (`reminder/`, `adviser/`, `tests/`) beyond running its suite; see
`docs/spec/02-existing-repo.md` for that.

Requirements: REQ-AUTH-01 (sessions, signup/login/magic links/TOTP), REQ-FND-02 (idempotent reference seed).

## Preconditions

- Windows 10/11, macOS or Linux, with admin/sudo rights to install packages and run Docker.
- A GitHub account with access to `ianondieki/second-brain`.

## 1. Prerequisites

### Windows

```powershell
winget install astral-sh.uv
winget install ezwinports.make
winget install GitHub.cli
winget install OpenJS.NodeJS.LTS   # Node 22; confirm with `node -v`
winget install Docker.DockerDesktop
uv python install 3.12             # backend pins >=3.12,<3.13
```

Docker Desktop on Windows runs on WSL 2. Give the WSL 2 VM at least 4 GB or Postgres will crash under load
(see Troubleshooting). Create or edit `%UserProfile%\.wslconfig`:

```ini
[wsl2]
memory=4GB
```

Then restart WSL so the change takes effect: `wsl --shutdown`.

Two Windows-only gotchas:

- If your antivirus intercepts TLS (common on managed laptops), `uv` will fail to verify HTTPS certificates. Set
  `UV_SYSTEM_CERTS=1` in your shell profile so `uv` trusts the Windows certificate store.
- If you also have the legacy companion's `.venv` activated, its `VIRTUAL_ENV` variable can make `uv` pick the
  wrong interpreter. Unset it before running `uv` commands: `Remove-Item Env:VIRTUAL_ENV` (PowerShell) or
  `unset VIRTUAL_ENV` (bash).

### macOS / Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # uv
brew install make gh                                # macOS; use your package manager on Linux
# Node 22 and Docker: install from nodejs.org / docker.com, or your package manager
uv python install 3.12
```

Verify: `uv --version`, `make --version`, `gh --version`, `node -v` (22.x), `docker version`.

## 2. First run

Copy the two example env files (both are gitignored; never commit the copies): `copy infra\.env.example infra\.env`
and `copy backend\.env.example backend\.env` (PowerShell), or `cp infra/.env.example infra/.env` and
`cp backend/.env.example backend/.env` (bash).

Edit `infra/.env` and set `POSTGRES_SUPERUSER_PASSWORD`, `BRIDGE_OWNER_PASSWORD`, `BRIDGE_APP_PASSWORD` to your own
local values. Put the **same** `BRIDGE_OWNER_PASSWORD` and `BRIDGE_APP_PASSWORD` into `backend/.env`'s
`DATABASE_OWNER_URL` and `DATABASE_URL` (the owner role runs migrations and the seed; the app role is RLS-bound and
used by the API and worker).

Generate the two required secrets in `backend/.env` (each must be at least 32 characters; the app refuses to start
otherwise): PowerShell `[Convert]::ToBase64String((1..32 | % { Get-Random -Maximum 256 }))`, bash
`openssl rand -base64 32`. Use one value for `SECRET_KEY` and a separate one for `DATA_ENCRYPTION_KEY`.

Start the stack:

```bash
make dev
```

This builds and starts, all bound to `127.0.0.1`: `web` (Next.js, port 3000), `api` (FastAPI, port 8000), `mailpit`
(UI on 8025, SMTP on 1025), `postgres` (pgvector, port 5432) and `s3` (SeaweedFS S3 stand-in, port 8333, unused
until Phase 2 uploads). `make dev-full` additionally starts `clamav` (port 3310; needs ~1.3 GB more RAM), used for
attachment scanning from Phase 2.

Migrations and the seed run automatically: the `migrate` one-shot service runs `alembic upgrade head` then
`python -m bridge.seed` (idempotent: niches, plans, NDA v1, holidays, provisional directory, dev/test only) before
`api` and `worker` start. Rerun on a running stack with `make migrate`.

Signup and login emails (magic links, TOTP enrolment) never leave the box: they land in Mailpit's UI at
`http://localhost:8025`, not in a real inbox.

Stop the stack (data volumes are kept, so your seeded database survives) with `make down`.

## 3. Everyday commands

```bash
make check            # everything CI runs: backend, frontend, legacy suite, Playwright smoke
make check-backend    # ruff, ruff format --check, mypy --strict, OpenAPI drift, pytest (backend/)
make check-frontend   # eslint, tsc, vitest, API types drift (frontend/)
make check-legacy     # the unchanged local-companion suite, via scripts/run_legacy_tests.py
make check-e2e        # Playwright smoke; needs the stack running (`make dev` first)
```

After changing an API route or schema, regenerate the OpenAPI document and the frontend's generated types:

```bash
make openapi          # backend/openapi.json
make api-types        # also regenerates frontend/lib/api/schema.d.ts (runs openapi first)
```

Backend integration tests use Postgres. Point `TEST_DATABASE_ADMIN_URL` (a superuser URL) at the `infra/.env`
Postgres instance to run them against it:

```bash
export TEST_DATABASE_ADMIN_URL=postgresql+psycopg://postgres:<POSTGRES_SUPERUSER_PASSWORD>@localhost:5432/postgres
cd backend && uv run pytest
```

Without `TEST_DATABASE_ADMIN_URL`, the same tests start a throwaway pgvector container through testcontainers
instead (slower, but needs no local Postgres).

## 4. Rules that surprise newcomers

- Tests can never reach the internet. `backend/tests/egress.py` fences unit/integration tests locally, and CI runs
  every test step behind `infra/ci/egress-lock.sh`, which rejects outbound packets except to loopback and private
  networks. No test can call a real LLM, email, WhatsApp or payment provider.
- `reminder/`, `adviser/`, `tests/` are the unchanged local companion. Do not edit them for platform work; they stay
  byte-for-byte the same except where a task card says otherwise.
- Alembic revisions are written only by the `db-migrations` agent; do not hand-edit `backend/alembic/`.
- Secrets live only in the untracked `infra/.env` and `backend/.env` files (both gitignored), with sandbox/test
  values. Every variable the code reads is documented with a one-line comment in the matching `.env.example`.
- The app fails closed: it refuses to start if `SECRET_KEY` or `DATA_ENCRYPTION_KEY` is missing or under 32
  characters.

## 5. Troubleshooting

**Docker VM runs out of memory; Postgres keeps restarting.** Symptom: `postgres` container logs show crash
recovery on every start, or `api`/`worker` never become healthy. Fix: give WSL 2 at least 4 GB (see Prerequisites,
`.wslconfig` + `wsl --shutdown`), then `make down` and `make dev` again. `make dev-full` (adds ClamAV) needs even
more headroom.

**`GET /readyz` returns 503.** The API is up but cannot reach the database (Postgres still starting, or wrong
`DATABASE_URL`/`DATABASE_OWNER_URL` password in `backend/.env`). Check `docker compose --env-file infra/.env -f
infra/docker-compose.dev.yml logs postgres` and confirm the passwords in `infra/.env` and `backend/.env` match.

**A request fails with `csrf_failed` (403).** The frontend needs a fresh CSRF cookie before a state-changing
request. Fetch `/api/auth/csrf` first (the login/signup flows already do this); if you are calling the API
directly, do the same.

**Windows: async database code hangs or errors oddly.** psycopg's async driver needs Python's selector event loop;
Windows defaults to the proactor loop. Tests (`backend/tests/conftest.py`) and Alembic (`backend/alembic/env.py`)
already select `asyncio.SelectorEventLoop` on `sys.platform == "win32"`, so this should not surface in normal use;
if you write a new async entry point on Windows, follow the same pattern as `backend/src/bridge/seed/__main__.py`.

## Contacts

Open a question in the repository (`ianondieki/second-brain`) or raise it in `docs/platform/DECISIONS-NEEDED.md`
per `CLAUDE.md`'s session rules.
