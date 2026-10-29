# REQ-FND-01

- Task: T1.1, T1.2 (`docs/platform/PLAN.md` Phase 1)
- Agent: orchestrator (B), test-writer review
- Files owned: `legacy/`, `scripts/run_legacy_tests.py`, `scripts/test_run_legacy_tests.py`, `.gitignore`, `.github/workflows/pr.yml` (legacy jobs), `infra/ci/`
- Depends on: T1.1 first.

## Scope

Archive n8n/Docker material into `legacy/` (one `git mv` + README); `scripts/run_legacy_tests.py` applies `docs/platform/tests_skip_linux.txt` off Windows; CI legacy matrix ubuntu (skip list) + windows-latest (full suite); a non-blocking `--no-skip` ubuntu job keeps the list honest (D-12); cloudflared stub on PATH and `requirements.txt` in CI (D-13).

## Acceptance criteria and tests

AC-REM-4/a: pr.yml `legacy` job (ubuntu + windows-latest); `scripts/test_run_legacy_tests.py` (skip-list parsing, stale-id detection).

## Notes

D-13 mechanism: `adviser.__main__.check()` receives an explicit env dict in the two `CheckTests`, so `ADVISER_CLOUDFLARED` in the process environment is never read; the workflow puts an empty `cloudflared` stub on PATH instead (same intent: a dummy file, no real binary).
