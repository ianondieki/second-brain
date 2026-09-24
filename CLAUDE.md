# CLAUDE.md

Repository: `ianondieki/second-brain`. Two products live here: the unchanged local companion (`reminder/`, `adviser/`,
`tests/`) and the hosted developer ⇄ enterprise platform ("Bridge", working name) being built under `backend/`,
`frontend/`, `infra/` per the spec in `docs/spec/`. Integration branch: `claude/eloquent-hypatia-aa3577`. Never touch
`main`; the human merges at gate G8.

## Session rules

- One build phase per session. Start by reading this file, then `docs/platform/PROGRESS.md`, `REQUIREMENTS.md`,
  `DECISIONS-NEEDED.md`, `GATES.md`, and only the `docs/spec/` files the phase needs (index below). Query the graphify
  graph (`graphify query "<question>"`) before searching files.
- Phase 0 = documents only under `docs/platform/`, `.claude/agents/` and this file. Phases 1–8 follow `docs/platform/PLAN.md`.
- The orchestrator is the main session (Fable 5.1, `/effort xhigh`; `max` in Phases 0 and 8). Sub-agents are in
  `.claude/agents/` and cannot spawn sub-agents. Check effort with `/effort status` (session) and `/tasks` (sub-agents).
- Stop and write to `DECISIONS-NEEDED.md` (then continue unblocked work or stop) when: a message would reach a non-test
  recipient; a destructive migration, force-push or history rewrite is needed; any spend or new vendor; a MUST
  requirement would change or two conflict; CI fails after 3 genuine fixes; legal/claims/pricing/brand text is needed
  (ordinary copy is written and tagged `[[COPY-REVIEW]]`); a gate is reached; the phase budget is exceeded.
- Secrets: sandbox/test values only, in an untracked `.env`; every variable documented in the `.env.example` files;
  the app fails closed when a secret is missing. Never commit secrets.

## Platform spec index

The build spec is split into topic files under docs/spec/. Read only the files the current task needs.

| File | Read it when |
|---|---|
| docs/spec/00-how-to-run.md | Starting any session: run order, phase-per-session rules, build model allocation, agent file template |
| docs/spec/01-mission.md | You need the product summary, the two sides, or the launch scope |
| docs/spec/02-existing-repo.md | Touching reminder/, adviser/, tests/, legacy files, hygiene fixes or .env.example |
| docs/spec/03-glossary-roles.md | Naming anything, or checking roles and verification levels (E0/E1/E2) |
| docs/spec/04-principles.md | Before any design decision; these rules override everything else |
| docs/spec/05-subscriptions-billing.md | Plans, entitlements, paywalls, M-Pesa/Paystack, invoices |
| docs/spec/06-feature-modules.md | Building any feature (6.1–6.12) and its acceptance criteria: repository, directory, proposals, provenance, research, trending, ranker, scouts, tracker, emails EM1–EM8, reminders, admin |
| docs/spec/07-ux-information-architecture.md | Any frontend work: navigation, onboarding, empty states, mobile, accessibility, i18n |
| docs/spec/08-architecture-stack-data-model.md | Choosing libraries, schema/migrations, jobs, LLM layer, CI, testing, deploy |
| docs/spec/09-ai-runtime-safety-evals.md | Any runtime LLM call, model choice, injection defences, cost caps, evals |
| docs/spec/10-security-privacy-compliance.md | Personal data, legal templates, Tier-2 access, feature flags, Kenyan compliance |
| docs/spec/11-delivery-phases.md | Planning a phase or checking its exit criteria and release (R1/R2/R3) |
| docs/spec/12-agent-operating-rules.md | Per-task workflow, traceability, ADRs, human gates, when to stop and ask |
| docs/spec/13-open-decisions.md | Writing or checking ADR-001..008 and policy.yaml defaults |
| docs/spec/14-definition-of-done.md | Before marking a task, requirement or the product done; the E2E scenarios |
| docs/spec/appendix-a-traceability.md | Mapping a requirement R01–R53 or R-HYG to its sections and acceptance criteria |

## Planning artefacts (docs/platform/)

`PLAN.md` (phases, tasks, phase exit map) · `REQUIREMENTS.md` (R-id → REQ-ID → AC register, notification matrix) ·
`adr/001..008` · `THREAT_MODEL.md` · `GATES.md` (human sign-offs) · `DECISIONS-NEEDED.md` (open questions) ·
`PROGRESS.md` (phase reports, `/cost` paste) · `tests_skip_linux.txt` · `checks/check_traceability.py` ·
`tasks/<REQ-ID>.md` (task cards, from Phase 1) · `research/` (cited research notes).

## Build workflow (every phase)
1. Context: query the graphify graph before searching files. Read only the docs/spec/ files the phase needs.
2. Plan: write a short plan for the phase before coding (task cards per REQ-ID).
3. Build: implement in small steps and commit after each; ≤3 implementers in worktrees; only `db-migrations` writes Alembic revisions.
4. Test: write tests for every acceptance test ID in the phase. All tests must pass.
5. UI (if the phase has screens): use the frontend-design skill, then the impeccable skill to polish, then Playwright screenshots at 375px and 1440px widths, fixing anything broken.
6. Browser bugs: use chrome-devtools for console, network and performance errors.
7. Review: run ECC's code review (`/code-review` if ECC is unavailable) on the phase's changes and fix every critical and high issue; `reviewer` PASS on every PR, `security-reviewer` PASS for `auth/`, `tenancy/`, `billing/`, `provenance/`, `engagements/`, `ux-reviewer` PASS on frontend PRs.
8. Report: write the phase report and update PROGRESS.md; run `python docs/platform/checks/check_traceability.py`.
9. Gate: stop at the phase's gate and wait for human approval in GATES.md.

## Build commands

```powershell
# Legacy local companion (unchanged; must stay green on windows-latest)
.venv\Scripts\python.exe -m unittest discover -s tests -t .
python scripts/run_legacy_tests.py            # Phase 1+: same suite, applies docs/platform/tests_skip_linux.txt off Windows

# Platform (Phase 1+; Makefile at repo root)
make dev                                      # seeded local stack: Postgres 16 + pgvector, Mailpit, MinIO, ClamAV, api, web, worker
make check                                    # ruff, ruff format, mypy --strict (backend); eslint, tsc, vitest (frontend); pytest; legacy tests; Playwright smoke
make check-backend / make check-frontend      # subsets of the above
uv run alembic upgrade head                   # inside backend/; migrations only via the db-migrations agent
python -m bridge.seed                         # idempotent seed: niches, plans, NDA v1, holidays, provisional directory (dev/test only)

# Traceability (every phase, before the report)
python docs/platform/checks/check_traceability.py
```

`make check` never reaches a real LLM, email, WhatsApp or payment provider; CI runs the same target on an
egress-blocked runner. Only `nightly.yml` may call `api.anthropic.com` (evals, ≤USD 5).

## Commits and PRs

- Small conventional commits (≤~300 changed lines, one concern) that name a REQ-ID or R-id:
  `feat(REQ-ENG-01): add engagement state machine`, `fix(R42): …`, `docs(platform): …`, `chore(REQ-HYG-06): …`.
- Every commit message and PR body ends with the attribution lines:

```
Co-Authored-By: Claude <noreply@anthropic.com>
```

- Never `--no-verify`; never delete or skip a test to go green; never edit `reminder/`, `adviser/`, `tests/` or
  `docs/spec/` unless the task card says so (spec changes need the human).
- PRs target `claude/eloquent-hypatia-aa3577`; merge only on `reviewer` PASS (plus `security-reviewer`/`ux-reviewer`
  where required) and green CI; remove the worktree after merge.

## Agents (.claude/agents/)

| Agent | Model / effort | Use for |
|---|---|---|
| impl-backend, impl-frontend, impl-integrations, impl-ai | opus / xhigh | one task card each, in a worktree |
| db-migrations | opus / xhigh | the only writer of Alembic revisions, RLS policies, grants |
| reviewer | opus / xhigh | adversarial review of every PR; reports, never fixes |
| security-reviewer | claude-fable-5-1 / xhigh | auth, tenancy, billing, provenance, engagements; Phase 8 audit |
| test-writer | sonnet / high | tests from Given/When/Then |
| ux-reviewer | opus / high | frontend PRs against docs/spec/07 |
| docs-writer | sonnet / medium | README, runbooks, help text; never legal text |
| researcher | sonnet / high | cited external facts into docs/platform/research/ |
| chore | haiku (default effort) | renames, lint autofix, dependency bumps |
| orchestrator | documentation only; the main session, never a sub-agent |

Effort is set per agent in frontmatter (Claude Code sub-agent docs; ADR-001). Never run an Opus agent at default
(medium) effort for code.

## graphify
- **graphify** (`~/.claude/skills/graphify/SKILL.md`) turns any input into a knowledge graph. Trigger: `/graphify`.
  When the user types `/graphify`, use the installed graphify skill before doing anything else.
