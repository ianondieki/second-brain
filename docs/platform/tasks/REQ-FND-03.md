# REQ-FND-03

- Task: T1.3 (`docs/platform/PLAN.md` Phase 1)
- Agent: orchestrator (I)
- Files owned: `.github/workflows/`, `infra/ci/`
- Depends on: T1.3 scaffold.

## Scope

CI `pr.yml`: ruff, ruff format, mypy --strict, eslint, tsc, vitest, pytest, migration up/down/up + `alembic check`, OpenAPI drift, Playwright smoke, scanners (gitleaks, pip-audit, npm audit, osv-scanner, Trivy, CodeQL) blocking on high/critical, egress-locked test steps; `nightly.yml` skeleton.

## Acceptance criteria and tests

AC-SEC-4: `backend/tests/unit/ci/test_workflows.py` (scanner jobs present, never `continue-on-error: true`, fail on high/critical). AC-SEC-5: same file (no provider host or provider secret outside `nightly.yml`; only its evals job may name `api.anthropic.com`) and the pr.yml egress probe (`infra/ci/egress_probe.py` under `infra/ci/egress-lock.sh`).

## Notes

Egress lock: iptables owner-match for a `sandbox` user plus DOCKER-USER rules for containers.
