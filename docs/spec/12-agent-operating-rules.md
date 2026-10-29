## 12. Agent operating rules

**12.1 Traceability.** Every task card (`docs/platform/tasks/<REQ-ID>.md`), branch, commit and PR names ≥1 REQ-ID (R01–R53 in Appendix A (`docs/spec/appendix-a-traceability.md`) plus R-HYG-01..06 and AC ids). Every R-id has ≥1 AC. Code without a REQ-ID either reveals a missing requirement (add as NEEDS-HUMAN) or should not exist. Only the orchestrator sets DONE, after every linked AC test passes in CI on the integration branch; a phase exit fails for any in-phase R-id without a passing linked test. DEFERRED needs an ADR number; NEEDS-HUMAN needs a `DECISIONS-NEEDED.md` entry.

**12.2 ADRs** in `docs/platform/adr/NNN-title.md` (context, decision, alternatives, consequences) before any code depends on the decision.

**12.3 Workflow per task**
1. Orchestrator writes a task card: REQ-IDs, files owned, acceptance criteria, agent, model, effort. Overlapping file sets never run concurrently.
2. `git worktree add ../sb-wt/<REQ-ID> -b feat/<REQ-ID>-<slug> claude/eloquent-hypatia-aa3577`; ≤3 implementers concurrently.
3. Only `db-migrations` creates Alembic revisions.
4. Freeze `backend/openapi.json` (generated, committed) before frontend and backend work on one feature in parallel.
5. Implementer runs `make check` (ruff, ruff format, mypy `--strict` on `backend/`; eslint, tsc, vitest on `frontend/`; pytest plus `scripts/run_legacy_tests.py`; Playwright smoke) before every push. Hooks are never skipped with `--no-verify`; tests are never deleted or skipped to go green.
6. Small conventional commits (≤~300 changed lines, one concern): `feat(R42): add engagement state machine`, ending with the attribution lines in CLAUDE.md.
7. PR into the integration branch → `reviewer` (and `security-reviewer` for its `docs/spec/00-how-to-run.md#02-build-time-model-allocation-for-the-agents-that-implement-this-spec` paths) report `BLOCKER/MAJOR/MINOR` with file:line and a failing scenario, verdict `PASS`/`CHANGES_REQUIRED`. Orchestrator merges only on PASS from every required reviewer + green CI, then removes the worktree.
8. Orchestrator updates `REQUIREMENTS.md` and `PROGRESS.md`.

**12.4 Human gates**

| Gate | Human provides / approves | Blocks |
|---|---|---|
| G0 | PLAN, REQUIREMENTS, ADR-001..008, THREAT_MODEL, budget per phase, precision@5 target, pre-approved vendor/free-tier list (Postmark, Sentry, Grafana Cloud, Better Stack, healthchecks.io, Cloudflare, TSA, SMS, Langfuse Cloud) so Phase 8 does not stop per vendor | All product code |
| G1 | Hosting region confirmation, product domain, SMS vendor account | Phase 1 deploy config |
| G2 | Advocate-reviewed legal templates, `esign_exclusions.md`, records custodian, reputation-score formula; agents only insert `[[LEGAL-PLACEHOLDER:<id>]]` | Phase 8 exit |
| G-EVAL | Human labels for research, scout, ranker and judge sets (`docs/spec/09-ai-runtime-safety-evals.md`) | Phase 4 exit |
| G3 | Tiers, KES prices, free-tier limits, trial rules | Phase 6 gating values |
| G4 | Daraja shortcode/passkey/keys and Paystack keys entered directly into SSM | Live payments |
| G5 | Product name, logo, palette, native-speaker review of `sw.json` | Phase 8 visual polish |
| G6 | Directory seeding policy and list (public info, starts E0) | Directory going public |
| G7 | Sender-domain SPF/DKIM/DMARC | Real email |
| G8 | Launch go/no-go after the Phase 8 report | Merge to `main`, production |

**12.5 Stop and ask** (write to `DECISIONS-NEEDED.md`, then switch to unblocked work or stop) when: an outbound message would reach a non-test recipient; a destructive migration or data deletion is needed; a force-push or history rewrite would happen; any spend or new paid vendor; a MUST requirement would change or two conflict; CI still fails after 3 genuine fix attempts on one task; legal templates or claims about protection, IP, pricing or brand are needed (ordinary product copy — emails, decline reasons, empty states — is written and marked `[[COPY-REVIEW]]` for G2/G5 review instead); a gate is reached; the phase budget is exceeded.
