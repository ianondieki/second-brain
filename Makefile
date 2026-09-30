# Bridge platform tasks (docs/spec/08; CLAUDE.md "Build commands"). Works from Git Bash, PowerShell or cmd:
# every recipe line is a plain command chain (`cd x && y`). Run `make help` for the list.
# make check never reaches a real LLM, email, WhatsApp or payment provider (AC-SEC-5): tests are fenced by
# backend/tests/egress.py, and CI runs the same targets inside infra/ci/egress-lock.sh.

COMPOSE = docker compose --env-file infra/.env -f infra/docker-compose.dev.yml
LEGACY_PY ?= python
UV = uv
# The local demo (infra/demo/demo.py, standard-library Python): the same commands on Windows, macOS and Linux.
DEMO_PY ?= $(LEGACY_PY)
DEMO = $(DEMO_PY) infra/demo/demo.py

.PHONY: help dev dev-full down logs migrate seed openapi api-types check check-backend check-frontend \
        check-legacy check-copy check-e2e test-integration e2e budget \
        demo demo-down demo-reset demo-totp demo-logins demo-logs demo-stats demo-clock \
        demo-reminders demo-scouts demo-walkthrough

help:
	@echo "dev             start the seeded local stack (Postgres+pgvector, Mailpit, S3 stand-in, api, worker, web)"
	@echo "dev-full        dev plus ClamAV (needs ~1.3 GB more RAM)"
	@echo "down            stop the stack (data volumes kept)"
	@echo "check           everything CI runs: backend, frontend, legacy suite, Playwright smoke"
	@echo "check-backend   ruff, ruff format, mypy --strict, OpenAPI drift, pytest (unit + integration)"
	@echo "check-frontend  eslint, tsc, vitest, API types drift"
	@echo "check-legacy    the unchanged local-companion suite (scripts/run_legacy_tests.py)"
	@echo "check-copy      banned-claims copy-lint (copy/banned_claims.txt, AC-IP-4)"
	@echo "check-e2e       Playwright smoke against the running stack (make dev first)"
	@echo "budget          gzipped JS per route against a running production web app (make dev first; not in check)"
	@echo "openapi         regenerate backend/openapi.json;  api-types  regenerate frontend/lib/api/schema.d.ts"
	@echo "demo            the local demo: seeded stack without ClamAV, fits Docker Desktop's 4 GB (README: Run the demo)"
	@echo "demo-down       stop the demo (its data is kept);  demo-reset  wipe the demo's data and start it again"
	@echo "demo-totp       current TOTP codes of the demo logins (one: make demo-totp EMAIL=<address>)"
	@echo "demo-logins     the demo logins;  demo-stats  memory per demo container;  demo-logs  follow its logs"
	@echo "demo-clock      show the demo's dev/test clock, or move it: make demo-clock DAYS=3 (HOURS=5)"
	@echo "demo-reminders  send today's developer nudges and organisation digests now (they land in Mailpit)"
	@echo "demo-scouts     run the due scouts now on the demo's clock (their digests land in Mailpit)"
	@echo "demo-walkthrough record the demo story after make demo-reset: video in docs/demo/video, docs/demo/screenshots"

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

check: check-copy check-backend check-frontend check-legacy check-e2e

check-backend:
	cd backend && $(UV) run ruff check . && $(UV) run ruff format --check . && $(UV) run mypy
	cd backend && $(UV) run python -m bridge.openapi --check
	cd backend && $(UV) run pytest

check-frontend:
	cd frontend && npm run lint && npm run typecheck && npm run test && npm run api:check

check-legacy:
	$(LEGACY_PY) scripts/run_legacy_tests.py

check-copy:
	$(LEGACY_PY) scripts/copy_lint.py

check-e2e:
	cd frontend && npm run e2e

# The local demo (P9; REQ-FND-02): infra/docker-compose.demo.yml over the dev stack, as its own project (bridge-demo).
# demo-reset is the only target that wipes the demo's volumes, and nothing depends on it.
demo:
	$(DEMO) up

demo-down:
	$(DEMO) down

demo-reset:
	$(DEMO) reset --yes

demo-totp:
	$(DEMO) totp $(EMAIL)

demo-logins:
	$(DEMO) logins

demo-logs:
	$(DEMO) logs

demo-stats:
	$(DEMO) stats

demo-clock:
	$(DEMO) clock --days $(or $(DAYS),0) --hours $(or $(HOURS),0)

demo-reminders:
	$(DEMO) reminders

demo-scouts:
	$(DEMO) scouts

# The recorded walkthrough (P16-W; docs/demo/README.md): run it right after make demo-reset (it changes demo data). It
# moves the demo clock a day and sends the reminders with the same DEMO_PY (WALKTHROUGH_RUN_DEMO_CMDS=1).
demo-walkthrough: export WALKTHROUGH_RUN_DEMO_CMDS ?= 1
demo-walkthrough: export DEMO_PY := $(DEMO_PY)
demo-walkthrough:
	$(DEMO) e2e-env
	cd frontend && npm run demo:walkthrough

# docs/spec/07 item 5: at most 150,000 bytes of gzipped JS per route (frontend/scripts/js-budget.mjs). Measures the
# default routes; BUDGET_BASE_URL and BUDGET_COOKIE (frontend/.env.example) come from the shell.
budget:
	cd frontend && npm run budget
