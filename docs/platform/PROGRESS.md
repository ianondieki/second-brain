# PROGRESS — phase reports

One section per phase, written by the orchestrator at the end of the phase session. The human pastes `/cost` output
into the phase's "Cost" line and signs the gate in `GATES.md`.

## Phase 0 — Discovery & plan (2026-09-24)

Branch `claude/eloquent-hypatia-aa3577`, commits `349cae6..HEAD` on top of `bce9a87`. Documents only; no product code,
no dependency installs. Orchestrator: Fable 5.1 (`max`).

### Documents produced

| Path | Content |
|---|---|
| `docs/platform/PLAN.md` | Ground rules, Phases 1–8 with ordered task tables (T1.1 … T8.8), agents per task, exit checks, gates, demos; §4 phase exit map; §5 timing deviations; §6 order of work; §7 budget |
| `docs/platform/REQUIREMENTS.md` | §2 one row per R-id (59), §3 one row per REQ-ID (99; 94 R1, 5 DEFERRED), §4 one row per AC or AC clause (107; Given/When/Then copied from the spec tables, AC-HYG-01..06 derived as CI grep/ls/git checks), §5 notification matrix N01–N23 |
| `docs/platform/adr/001..008` | Repo layout & product boundary (incl. verified `effort` frontmatter), auth/tenancy/identity, authorship evidence, email & messaging, runtime LLMs & embeddings, payments, hosting & data residency, launch scope |
| `docs/platform/THREAT_MODEL.md` | STRIDE tables over auth, tenancy, provenance, payments, idea leakage, prompt injection; each mitigation cites the spec and the AC that verifies it; top residual risks for G0 |
| `docs/platform/GATES.md` | G0–G8 and G-EVAL, all PENDING, with inputs, what each blocks and the sign-off format |
| `docs/platform/DECISIONS-NEEDED.md` | D-01..D-23 open questions with options and recommended defaults; D-01, D-02, D-03 are G0 inputs |
| `docs/platform/tests_skip_linux.txt` | The 4 Windows-only legacy test ids (2 `ToolTests`, 2 `CheckTests`), marked unverified until Phase 1 CI |
| `docs/platform/checks/check_traceability.py` | Exit-criteria checker (stdlib only): R-id coverage, two-way links, phase-exit independence, spec alignment, AC universe read from `docs/spec` |
| `.claude/agents/*.md` | 13 role files per the `docs/spec/00` 0.2 table (impl-backend, impl-frontend, impl-integrations, impl-ai, db-migrations, reviewer, security-reviewer, test-writer, ux-reviewer, docs-writer, researcher, chore, orchestrator) with model and effort in frontmatter |
| `CLAUDE.md` | Session rules, spec index, planning artefacts, build workflow, build commands, commit attribution lines, agent roster (120 lines) |

### Check results

| Check | Result |
|---|---|
| `python docs/platform/checks/check_traceability.py` | PASS: 0 errors, 7 warnings (the intentional earlier-than-spec assertions listed in `PLAN.md` §5: AC-SEC-2/4/5/6, AC-SUB-1/5/7) |
| Every R01–R53 and R-HYG-01..06 → ≥1 REQ-ID and ≥1 AC | Yes (59/59), links verified in both directions; each R-id's Phase equals the latest phase of its linked REQ-IDs/AC clauses |
| No phase exit depends on a later phase | Yes: every AC in the exit map is built at or before its phase; every built AC is listed at its own phase; nothing asserted later than `docs/spec/11` |
| AC universe | 101 spec ACs (05: 7, 06: 74, 07: 5, 10: 7, read at run time) + 6 derived AC-HYG = 107 rows incl. 7 split clauses |
| Markdown table integrity | Every row in every table of the five platform documents has the header's column count |
| Script quality | `ruff check` clean; `mypy --strict` clean; 9 mutation tests in the scratchpad each produce a clean ERROR and exit 1 (removed exit-map AC, later phase, deleted R-id row, blank line inside a table, short exit-map row, duplicate REQ row with bad status, invalid UTF-8 byte, spec drift, loose id typo) |
| `effort` in sub-agent frontmatter | Supported per https://code.claude.com/docs/en/sub-agents.md (recorded in ADR-001 with fallbacks) |

### Review results

- **ECC document review** (`ecc:code-reviewer` over all 29 changed files vs `docs/spec/`): 0 CRITICAL, 3 HIGH, 2 MEDIUM, 1 LOW. All fixed: `PROGRESS.md` written (this file); `researcher` and `docs-writer` given `Bash` so they can commit; `PLAN.md` Phase 4 REQ list names the existing REQ-SCOUT ids (there is no REQ-SCOUT-04); `CLAUDE.md` defines ECC and the review command; AC-HYG-02/03/04 greps exclude `.git`.
- **ECC Python review** (`ecc:python-reviewer` on `check_traceability.py`): 0 CRITICAL, 5 HIGH, 4 MEDIUM, 3 LOW. All fixed in `34de8f9`: clean errors for short exit-map rows, non-UTF-8 input and malformed (split) tables; `main()` split into typed loaders and check functions; `find_table` typed; `TypedDict` rows; duplicate rows checked; name-indexed columns; spec AC universe re-read from `docs/spec` (snapshot drift fails the run); `isdecimal`; loose-id warnings; docstrings.
- **Adversarial verification workflow** (`verify-requirements`: 3 R-id coverage checkers, 4 phase-exit checkers, 2 spec-fidelity checkers; every finding refuted by two independent skeptics): see "Workflow result" below.

### Workflow result

`verify-requirements` ran 79 agents (9 checkers, 2 refuters per finding): 35 findings raised, 9 confirmed by both
skeptics, 26 refuted. Every confirmed finding is fixed:

| Confirmed finding | Fix |
|---|---|
| BLOCKER AC-HYG-01: the grep over `docs/` could never return 0 (it matched `docs/spec` and `docs/platform`, which describe the defect) | AC-HYG-01..04 now use negated `git grep` over tracked files with `':!legacy' ':!docs/spec' ':!docs/platform'` pathspecs; positive README/`.env.example` assertions kept; AC-HYG-05/06 written as exit-0 shell tests |
| BLOCKER AC-HYG-02/03/04: same scoping defect, plus README's legacy section names the retired model | Same fix; REQ-HYG-03 code paths now include `README.md` (legacy section moves to `legacy/README.md`) |
| MAJOR AC-REPO-1 at Phase 2 needs the no-terminal-engagement and Master Enterprise Terms conditions | T2.1 adds the `engagements` skeleton table (fixture-driven until Phase 3); T2.6 adds MET acceptance with hash; REQ-REPO-01 and the AC-REPO-1 test note say so |
| MAJOR AC-REPO-2 at Phase 2 needs the `INTEREST_CONFIRMED` name switch | Covered by the same `engagements` skeleton fixture; noted on the AC row |
| MINOR AC-PERS-6 over-asserted "more Microfinance cards" for the platform-engagement pair | Then clause rewritten per pair, matching the spec text |
| MINOR "EM7 trending line unflagged" (spec Phase 5 exit) had no check | X5-2 added to PLAN.md Phase 5 exit; test listed under REQ-TREND-02 |
| MINOR R-id Phase column inconsistent with linked REQ/AC phases (R05, R06, R07, R13, R16, R20, R32 and five more) | Legend now defines the R-id Phase as the latest phase of its Release-1 REQ-IDs/AC clauses; 12 rows recomputed; `check_traceability.py` enforces it |

Refuted findings were mostly stricter readings the refuters showed to be satisfied elsewhere (clause rows, re-run links,
Phase 2 seeds); two refuted notes were still adopted as cheap improvements: 47 counties added to the Phase 1 seed
(T1.4) and the AC-SEC-5 workflow lint note about `main.yml` joining in Phase 8.

### REQ statuses

| Status | REQ rows | AC rows |
|---|---|---|
| TODO (Release 1) | 94 | 105 |
| DEFERRED (R2, ADR-003/004/008) | 4 | 2 |
| DEFERRED (R3, ADR-008) | 1 | 0 |
| DONE / IN-PROGRESS / NEEDS-HUMAN | 0 | 0 |

### Demo steps (Phase 0)

1. `python docs/platform/checks/check_traceability.py` → `PASS: 0 errors, 7 warning(s)`.
2. Open `docs/platform/PLAN.md` §4 and `REQUIREMENTS.md` §4 side by side: every AC listed at a phase has that phase (or an earlier one) in its row.
3. Open `GATES.md`: all rows PENDING; sign G0 by editing the Status cell.

### Test counts

Product tests: 0 (no product code in Phase 0). Planning checks: 1 script (9 checks), 9 mutation tests run in the scratchpad.
Legacy suite: unchanged (`tests/`), not run in Phase 0.

### Open decisions (see `DECISIONS-NEEDED.md`)

G0 inputs: D-01 budget per phase, D-02 precision@5 target, D-03 vendor list. Before Phase 1 starts: D-04 orchestrator
model, D-08 Next.js pin process, D-09 package name, D-12/D-13 legacy CI approach, D-20 OAuth test apps, D-23 Python
versions. The rest can wait for the phase that needs them (listed per entry).

### Risks

1. `tests_skip_linux.txt` is derived by reading, not running; the two `CheckTests` also need a cloudflared stand-in and the adviser dependencies on windows-latest (D-12, D-13). Mitigation: T1.2 runs the suite unfiltered on both OSes first.
2. Several ACs are asserted earlier than the spec's exit lists (`PLAN.md` §5); if the human prefers the spec's timing (D-07), the exit map moves them later and the check script must be updated in the same commit.
3. Budget: Phase 0 consumed more orchestration tokens than a typical phase because every document was written in one session; the per-phase budget (D-01) should assume Phases 2 and 3 are the largest.
4. External dependencies that only the human can create (OAuth test apps, Postmark, TSA, Anthropic key for nightly evals, AWS/G1 values) are listed in DECISIONS-NEEDED with the phase that needs them; none blocks Phase 1 local work.
5. The idea-protection promise is inherently limited to evidence and traceability (THREAT_MODEL §8 risk 1); copy and marketing must follow the approved phrasing.

### Cost

`/cost` (pasted by the human): _pending_

### Next session

After `G0: APPROVED <date>` in `GATES.md`: `Read CLAUDE.md (and the docs/spec/ files Phase 1 needs: 02, 03, 04, 05,
08, 10, 11, 12, 14), PROGRESS.md, REQUIREMENTS.md, DECISIONS-NEEDED.md; continue with Phase 1.` Phase 1 starts with
T1.1 (legacy archive + hygiene) and T1.2 (legacy test runner on both OSes) before any scaffold.

### G0 sign-off

G0 approved 2026-09-24 in `GATES.md`. Decisions D-01..D-23 are recorded in `DECISIONS-NEEDED.md` (Decided table).
Usage is tracked by the Max plan via `/cost`, with no USD cap (D-01).

## Phase 1 — Hygiene & foundation (in progress)

Started 2026-09-24. Orchestrator: Opus 5.5 (`xhigh`, D-04). Branch `claude/eloquent-hypatia-aa3577`.
Checklist updated after every task (done / in progress / remaining).

| Item | Status | Notes |
|---|---|---|
| Housekeeping: orchestrator agent → Opus 5.5 `xhigh` (Phases 1–7), Fable 5.1 `max` (Phase 8) (D-04) | done | `.claude/agents/orchestrator.md`, `PLAN.md` §1 |
| Housekeeping: OAuth moved from T1.5 to T2.12 / REQ-AUTH-02 (D-20) | done | `PLAN.md`, `REQUIREMENTS.md`, `DECISIONS-NEEDED.md` |
| Local tool check (Docker Desktop, make, uv, Node, gh) | done | Docker 29.5.3 (4 GB), GNU Make 4.4.1, uv 0.12.18 + CPython 3.12.14, Node 22.17.1, gh logged in. Local TLS interception: uv needs `UV_NATIVE_TLS=1` |
| T1.1 Legacy archive + hygiene (REQ-HYG-01..06, REQ-FND-01) | done | `d60a920` git mv into `legacy/` + README; workspace file deleted; root `.env.example` trimmed; README legacy section moved; AC-HYG-01..06 commands exit 0 locally (CI job lands in T1.2) |
| T1.2 `scripts/run_legacy_tests.py` + CI legacy matrix (REQ-FND-01) | done | CI green on `0cff6ca` (run 36017610734): hygiene, legacy windows-latest (full), legacy ubuntu (skip list, egress-locked). Skip list verified: 6 Linux-only ids (2 ToolTests, 4 TurnTests); the 2 CheckTests pass with the cloudflared stub (D-12, D-13, D-25) |
| T1.3 Scaffold backend/frontend/infra, Makefile, `pr.yml` (REQ-FND-02, REQ-FND-03) | done | every pr.yml job green on `ca49816` incl. Playwright on the compose stack (after `API_ORIGIN` build arg, seed data in the image); CodeQL green |
| T1.4 Core schema v1, RLS, audit chain, seed (REQ-TEN-01, REQ-AUD-01, REQ-CON-01) | done (merge `af3a115`) | reviewer PASS, security-reviewer (Fable) PASS after a BLOCKER (definer search_path) and a MAJOR (admin could mint owner); 84 migration/RLS tests; seed idempotent (X1-3) |
| T1.5 Auth: password, magic link, sessions, CSRF, TOTP, roles (REQ-AUTH-01, REQ-TEN-01) | in review | backend green in CI (unit + integration: auth flows, AC-SEC-1/a RLS generator, cross-tenant 404); reviewer and security-reviewer running |
| T1.6 `plans.yaml` + entitlement middleware (REQ-BIL-01) | in review | 402 with upgrade path, free subscriptions, self-serve limited to default plans at the DB; in the same review round as T1.5 |
| T1.7 `EmailProvider`, Mailpit sink, deliveries ledger (REQ-NOT-01) | done (merges `28b8af1`, `a78eaa9`) | reviewer PASS; SqlDeliveryStore PostgreSQL tests (races, suppression, resume, RLS) merged |
| T1.8 Reminder policy/compose port + parity tests, business-day helper (REQ-REM-00) | done (merge `de6548d`) | 48 parity fixtures from `reminder/`, 100% coverage, reviewer mutation run 67/69 killed, survivors fixed in `6d71e30` |
| T1.9 Signup/login UI + Playwright E2E + axe, dev-setup runbook (REQ-AUTH-01) | in progress | design plan `d766199`; runbook merged `a2fa003`; UI with impl-frontend |
| Task cards `docs/platform/tasks/` (16), research note, ADR-001 addendum (Next.js 16.3.6), D-24 (MinIO withdrawn) | done | `50f7082`, `44d0a46`, `ccc2354` |
| ECC code review, security-reviewer, traceability check, Phase 1 report | remaining | |
