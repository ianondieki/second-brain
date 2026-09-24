# REQ-FND-02

- Task: T1.3 (`docs/platform/PLAN.md` Phase 1)
- Agent: orchestrator (B, F, I)
- Files owned: `backend/` (skeleton), `frontend/` (skeleton), `infra/`, `Makefile`
- Depends on: T1.2.

## Scope

Monorepo scaffold: `backend/` (uv, FastAPI, Pydantic v2, SQLAlchemy 2 async + psycopg 3, Alembic, Procrastinate, structlog; package `bridge`), `frontend/` (Next.js pinned per the ADR-001 addendum, Tailwind, shadcn/ui, next-intl, openapi-typescript), `infra/docker-compose.dev.yml` (Postgres 16 + pgvector, Mailpit, MinIO, ClamAV; api, worker, web), `Makefile` (`make dev`, `make check`), `backend/.env.example`, `frontend/.env.example`.

## Acceptance criteria and tests

AC-SEC-5: `make check` never reaches a provider (socket guard in `backend/tests/conftest.py`; egress-locked CI steps).

## Notes

The app fails closed when a required secret is missing (`bridge/config.py`).
