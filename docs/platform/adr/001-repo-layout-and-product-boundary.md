# ADR-001: Repo layout, product boundary and build-agent effort control

- Status: PROPOSED (human may veto at G0)
- Date: 2026-09-24
- Spec: docs/spec/02-existing-repo.md, docs/spec/08-architecture-stack-data-model.md (Repo layout), docs/spec/00-how-to-run.md (0.2)
- Related: ADR-007 (hosting), ADR-008 (launch scope)

## Context

The repository today is a single-user local tool (`reminder/`, `adviser/`, `tests/`) plus an archived n8n/Docker
design. The platform adds a hosted, multi-tenant product in the same repository. The spec requires the local
companion to stay byte-for-byte unchanged (except `reminder/second-brain.code-workspace`) and never be imported
by the backend. The product needs a placeholder name until branding is approved at G5. The build agents' effort
level was flagged as unverified in `docs/spec/00-how-to-run.md`.

## Decision

1. **Monorepo layout** exactly as `docs/spec/08-architecture-stack-data-model.md` "Repo layout":
   - `backend/` (Python 3.12, FastAPI; package `backend/src/bridge/` with the module list from the spec; `backend/tests/{unit,integration,contract,evals}`; `backend/config/{policy,plans}.yaml`; `backend/.env.example`).
   - `frontend/` (Next.js App Router + TypeScript + Tailwind + shadcn/ui; `app/(public|dev|org|admin)`, `components/`, `lib/api/`, `e2e/`; `frontend/.env.example`).
   - `infra/` (`docker-compose.dev.yml`, `docker-compose.prod.yml`, `Caddyfile`, `terraform/`).
   - `reminder/`, `adviser/`, `tests/` unchanged; `scripts/run_legacy_tests.py` wraps the legacy suite; `docs/platform/tests_skip_linux.txt` lists Linux skips.
   - `legacy/` holds the archived n8n/Docker material (one `git mv` commit, README "unmaintained, kept for reference").
   - `docs/spec/` is the spec; `docs/platform/` holds plan, requirements, progress, decisions, gates, threat model, `adr/`, `tasks/`, `checks/`; `docs/legal/`, `docs/runbooks/`, `.github/workflows/`, `.claude/agents/`.
2. **Product boundary**: the backend never imports `reminder/` or `adviser/`. Reusable logic is copied and ported under `backend/src/bridge/` with parity tests against `reminder/` fixtures (table in `docs/spec/02-existing-repo.md`). Groq stays only in the local companion.
3. **Placeholder product name**: `Bridge` (Python package `bridge`, i18n namespace `bridge`, UI title "Bridge (working name)") until G5 supplies the real name; the name lives in one config key `PRODUCT_NAME` and one i18n key so G5 is a rename, not a refactor.
4. **Next.js version**: the current stable major on the npm `latest` dist-tag when Phase 1 starts, pinned exactly in `frontend/package.json` and recorded here as an addendum by the `researcher` (with the npm URL). Majors are bumped only through a new ADR.
5. **Build-agent effort**: the Claude Code docs (https://code.claude.com/docs/en/sub-agents.md, "Supported frontmatter fields") document `effort` as a subagent frontmatter key: "Effort level when this subagent is active. Overrides the session effort level. Default: inherits from session. Options: low, medium, high, xhigh, max; available levels depend on the model." Therefore every file in `.claude/agents/` sets `effort` explicitly (Opus 5.5 defaults to medium otherwise), except `chore` (Haiku 4.5, which the spec runs at its default; "available levels depend on the model", so no `effort` key is set there). Effective effort is checked with `/effort status` for the session and `/tasks` for running subagents (Claude Code v2.1.242 or later shows effort on a subagent's row when its definition sets it; same URL). Fallbacks if a future Claude Code version drops the key: `effortLevel` in `.claude/settings.json`, the `--effort` CLI flag, or `CLAUDE_CODE_EFFORT_LEVEL` (https://code.claude.com/docs/en/model-config.md); the orchestrator then records the mechanism used in `CLAUDE.md`. Verified 2026-09-24 by the `claude-code-guide` lookup during Phase 0.

## Alternatives considered

- Separate repositories for platform and companion: rejected; the spec mandates one repo, and parity tests against `reminder/` fixtures are simpler in-tree.
- Importing `reminder/` from the backend: rejected; it couples a Windows-oriented local tool (Gmail SMTP, Groq) to a hosted service and breaks the "unchanged companion" rule.
- Naming the product now: rejected; brand is a G5 decision.
- Controlling effort only at session level: rejected; subagents inherit the session level, but explicit per-agent values keep `chore` cheap and implementers at `xhigh` regardless of session state.

## Consequences

- One CI pipeline runs backend, frontend and the legacy suite (`scripts/run_legacy_tests.py` on ubuntu + windows).
- Ported code carries a `# ported from reminder/<file>` header and a parity test; drift is caught by the test, not by imports.
- `PRODUCT_NAME`/i18n rename at G5 touches config, one i18n key, email footers and `docs/legal/` placeholders only.
- Every agent file is reviewable for model + effort; the reviewer rejects PRs from an agent whose effort is unset.
