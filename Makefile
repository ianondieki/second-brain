# Bridge platform tasks (docs/spec/08; CLAUDE.md "Build commands"). Works from Git Bash, PowerShell or cmd:
# every recipe line is a plain command chain (`cd x && y`). Run `make help` for the list.
# make check never reaches a real LLM, email, WhatsApp or payment provider (AC-SEC-5): tests are fenced by
# backend/tests/egress.py, and CI runs the same targets inside infra/ci/egress-lock.sh.

COMPOSE = docker compose --env-file infra/.env -f infra/docker-compose.dev.yml
LEGACY_PY ?= python
UV = uv

.PHONY: help dev dev-full down logs migrate seed openapi api-types check check-backend check-frontend \
        check-legacy check-e2e test-integration e2e

help:
	@echo "dev             start the seeded local stack (Postgres+pgvector, Mailpit, S3 stand-in, api, worker, web)"
	@echo "dev-full        dev plus ClamAV (needs ~1.3 GB more RAM)"
	@echo "down            stop the stack (data volumes kept)"
	@echo "check           everything CI runs: backend, frontend, legacy suite, Playwright smoke"
	@echo "check-backend   ruff, ruff format, mypy --strict, OpenAPI drift, pytest (unit + integration)"
	@echo "check-frontend  eslint, tsc, vitest, API types drift"
	@echo "check-legacy    the unchanged local-companion suite (scripts/run_legacy_tests.py)"
	@echo "check-e2e       Playwright smoke against the running stack (make dev first)"
	@echo "openapi         regenerate backend/openapi.json;  api-types  regenerate frontend/lib/api/schema.d.ts"

dev:
	$(COMPOSE) up -d --build --wait

dev-full:
	$(COMPOSE) --profile full up -d --build --wait

down:
	$(COMPOSE) --profile full down

logs:
	$(COMPOSE) logs -f --tail=100

migrate:
	$(COMPOSE) run --rm migrate

openapi:
	cd backend && $(UV) run python -m bridge.openapi

api-types: openapi
	cd frontend && npm run api:types

check: check-backend check-frontend check-legacy check-e2e

check-backend:
	cd backend && $(UV) run ruff check . && $(UV) run ruff format --check . && $(UV) run mypy
	cd backend && $(UV) run python -m bridge.openapi --check
	cd backend && $(UV) run pytest

check-frontend:
	cd frontend && npm run lint && npm run typecheck && npm run test && npm run api:check

check-legacy:
	$(LEGACY_PY) scripts/run_legacy_tests.py

check-e2e:
	cd frontend && npm run e2e
