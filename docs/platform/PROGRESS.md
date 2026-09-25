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

## Phase 1 — Hygiene & foundation (2026-09-24 → 2026-09-25)

Started 2026-09-24. Orchestrator: Opus 5.5 (`xhigh`, D-04). Branch `claude/eloquent-hypatia-aa3577`.
Commits `4541267..HEAD` on top of `fb6131d` (165 commits, 155 non-merge). Every task is done; the phase waits for the
human's approval of this report.

| Item | Status | Notes |
|---|---|---|
| Housekeeping: orchestrator agent → Opus 5.5 `xhigh` (Phases 1–7), Fable 5.1 `max` (Phase 8) (D-04) | done | `.claude/agents/orchestrator.md`, `PLAN.md` §1 |
| Housekeeping: OAuth moved from T1.5 to T2.12 / REQ-AUTH-02 (D-20) | done | `PLAN.md`, `REQUIREMENTS.md`, `DECISIONS-NEEDED.md` |
| Local tool check (Docker Desktop, make, uv, Node, gh) | done | Docker 29.5.3 (4 GB), GNU Make 4.4.1, uv 0.12.18 + CPython 3.12.14, Node 22.17.1, gh logged in. Local TLS interception: uv needs `UV_NATIVE_TLS=1` |
| T1.1 Legacy archive + hygiene (REQ-HYG-01..06, REQ-FND-01) | done | `d60a920` git mv into `legacy/` + README; workspace file deleted; root `.env.example` trimmed; README legacy section moved; AC-HYG-01..06 commands exit 0 locally (CI job lands in T1.2) |
| T1.2 `scripts/run_legacy_tests.py` + CI legacy matrix (REQ-FND-01) | done | CI green on `0cff6ca` (run 36017610734): hygiene, legacy windows-latest (full), legacy ubuntu (skip list, egress-locked). Skip list verified: 6 Linux-only ids (2 ToolTests, 4 TurnTests); the 2 CheckTests pass with the cloudflared stub (D-12, D-13, D-25) |
| T1.3 Scaffold backend/frontend/infra, Makefile, `pr.yml` (REQ-FND-02, REQ-FND-03) | done | every pr.yml job green on `ca49816` incl. Playwright on the compose stack (after `API_ORIGIN` build arg, seed data in the image); CodeQL green |
| T1.4 Core schema v1, RLS, audit chain, seed (REQ-TEN-01, REQ-AUD-01, REQ-CON-01) | done (merge `af3a115`) | reviewer PASS, security-reviewer (Fable) PASS after a BLOCKER (definer search_path) and a MAJOR (admin could mint owner); 84 migration/RLS tests; seed idempotent (X1-3) |
| T1.5 Auth: password, magic link, sessions, CSRF, TOTP, roles (REQ-AUTH-01, REQ-TEN-01) | done (`4d500bb`) | four review rounds: security-reviewer (Fable) PASS on round 3, reviewer PASS on round 4 (mutation-checked tests); fixes include pre-hijacking binding, one email throttle with daily cap, `RECOVERY_CODE_PEPPER`, `__Host-` cookies, OpenAPI-driven 404 sweep; CI green on `932865a` |
| T1.6 `plans.yaml` + entitlement middleware (REQ-BIL-01) | done (`62f3e35`, `af1b348`) | 402 offers the next plan up (null at the top); catalogue validated; seed retires plans and moves the default (`test_seed_sync.py`); same review rounds as T1.5 |
| T1.7 `EmailProvider`, Mailpit sink, deliveries ledger (REQ-NOT-01) | done (merges `28b8af1`, `a78eaa9`) | reviewer PASS; SqlDeliveryStore PostgreSQL tests (races, suppression, resume, RLS) merged |
| T1.8 Reminder policy/compose port + parity tests, business-day helper (REQ-REM-00) | done (merge `de6548d`) | 48 parity fixtures from `reminder/`, 100% coverage, reviewer mutation run 67/69 killed, survivors fixed in `6d71e30` |
| T1.9 Signup/login UI + Playwright E2E + axe, dev-setup runbook (REQ-AUTH-01) | done (PR #10, merge `63bc78d`) | reviewer PASS (3 rounds, mutation-checked), security-reviewer PASS (2 rounds), ux-reviewer PASS (2 rounds); impeccable polish `126d39a`; CI green on `b0877bf` (22 Playwright tests) |
| Task cards `docs/platform/tasks/` (16), research note, ADR-001 addendum (Next.js 16.3.6), D-24 (MinIO withdrawn) | done | `50f7082`, `44d0a46`, `ccc2354` |
| ECC code review, security-reviewer, traceability check, Phase 1 report | done | ECC `ecc:code-reviewer` APPROVE (0 findings; its one low-confidence note fixed in `15562b0`); security-reviewer PASS on every `auth/`, `tenancy/`, `billing/` change and on the web client; traceability PASS; report below |

### Exit checks (`PLAN.md` Phase 1)

| Check | Result | Evidence |
|---|---|---|
| AC-HYG-01..06 | PASS | `pr.yml` hygiene job (`scripts/check_hygiene.sh`), green on every run since `0cff6ca` |
| AC-SEC-1/a (RLS generator + cross-tenant 404) | PASS | `backend/tests/integration/test_rls.py` (parametrised from table metadata); `test_auth_security.py::test_every_org_route_answers_404_to_a_non_member` sweeps every `{org_id}` route from the OpenAPI document, first as a developer with no second factor, then as another org's owner with a fresh one |
| AC-SEC-4 (scanners block on high/critical) | PASS | `pr.yml` scanners job (gitleaks, pip-audit, npm audit, osv-scanner, Trivy; images pinned by digest) and `codeql.yml` with `infra/ci/sarif_gate.py` (fails closed on unresolved rules); `backend/tests/unit/ci/test_workflows.py` asserts no `continue-on-error` |
| AC-SEC-5 (no real provider calls; egress-blocked runner) | PASS | `infra/ci/egress-lock.sh` + `egress_probe.py` in CI; `backend/tests/egress.py` guard in pytest; workflow lint allows `api.anthropic.com` only in the `nightly.yml` evals job |
| AC-REM-4/a (legacy suite unchanged and green) | PASS | CI: windows-latest full suite 313 tests OK; ubuntu 307 tests OK with the 6-id skip list (D-25); `reminder/`, `adviser/`, `tests/` untouched |
| X1-1 signup/login E2E on the compose stack | PASS | `pr.yml` "Playwright against the compose stack": 22 tests at 360 px and desktop (developer and org signup, link and password login, TOTP enrolment, recovery codes, `/auth/mfa`, no-password journey, JavaScript-disabled submit, security headers, axe) |
| X1-2 `make check` green on ubuntu and windows | PASS | CI (ubuntu) runs the same targets as jobs, green on `b0877bf`; windows-latest runs the full legacy suite; locally on Windows 10: `make check-legacy check-frontend check-backend` on `63bc78d` all exit 0 (legacy 313 OK, 2 self-skipped; Vitest 105; ruff, format, mypy --strict, OpenAPI drift, pytest 579). `check-e2e` needs the compose stack and ran in CI |
| X1-3 `python -m bridge.seed` idempotent | PASS | `test_seed.py` (seed twice, same counts) and `test_seed_sync.py::test_the_seed_command_runs_twice_with_the_same_counts` (the CLI) |
| Traceability | PASS | `python docs/platform/checks/check_traceability.py`: 0 errors, 7 warnings (the planned earlier-than-spec assertions) |

### What was built

- **Hygiene (T1.1–T1.2):** n8n/Docker material archived under `legacy/`; README and docs fixed; root `.env.example` trimmed; `scripts/run_legacy_tests.py` with `tests_skip_linux.txt`; legacy suite blocking on windows-latest (full) and ubuntu (skip list), plus an informational full ubuntu run.
- **Platform skeleton (T1.3):** `backend/` (FastAPI, SQLAlchemy async, Alembic, Procrastinate, structlog, uv), `frontend/` (Next.js 16.3.6, React 19, Tailwind 4, next-intl, openapi-typescript), `infra/docker-compose.dev.yml` (Postgres 16 + pgvector, Mailpit, SeaweedFS as the S3 stand-in per D-24, ClamAV under a profile, api, worker, web, migrate), `Makefile`, `pr.yml`, `codeql.yml`, `nightly.yml`.
- **Core schema v1 (T1.4):** one frozen revision with RLS on every org-scoped table, four database roles, SECURITY DEFINER helpers with pinned `search_path`, column-scoped grants, append-only hash-chained `audit_events` with per-scope chains and an independent verifier; reference seed (47 counties, 2026–2027 holidays, 16 niches, plans).
- **Auth (T1.5):** argon2id in a bounded 4-thread pool, magic links in the URL fragment, server-side sessions, CSRF double-submit bound to the session, TOTP with a replay counter and peppered recovery codes, step-up (12 h), mandatory TOTP for org owner/admin/signatory/reviewer and staff, pre-hijacking defence (browser binding cookie), one email throttle (3 per address and IP and 6 per address per 15 minutes, 20 a day), `__Host-` cookies, proxy-aware client IPs.
- **Billing foundation (T1.6):** `backend/config/plans.yaml` placeholders (until G3), a validated catalogue with an upgrade ladder, entitlement checks returning 402 with the next plan, free subscriptions at signup.
- **Email (T1.7):** `EmailProvider` (Postmark adapter, SMTP/Mailpit sink, Fake), `notification_deliveries` ledger with dedupe, retries and suppressions.
- **Reminders port (T1.8):** `bridge/reminders/{policy,compose}.py` with 48 parity fixtures generated from `reminder/`; business-day helper.
- **Auth screens (T1.9):** landing, signup, login, check-email, `/auth/link`, `/auth/mfa`, `/settings/security`, `/dev`, `/org`; English only until G5 (the Swahili file stays in sync); security headers; forms that never submit natively before hydration; `docs/runbooks/dev-setup.md`.

### Review results

- **reviewer (Opus):** PASS on every merged task. Auth, tenancy and billing took four rounds (a generated 404 sweep that could not fail, an unverified-login email flood, a password cleared on resend, recovery codes tied to the rotating key, audit property-test gaps, a stale OpenAPI file). T1.9 took three (copy that promised emails, a shortened access claim, sign-out ignoring failures, an untested fragment scrub, a password field that disappeared while typing). The reviewer mutation-checked the key tests.
- **security-reviewer (Fable):** PASS on T1.4 (after a BLOCKER, definer functions without a pinned `search_path`, and a MAJOR, an admin could mint an owner), on auth, tenancy and billing (round 3), and on the T1.9 web client (after a MAJOR, cookie-header injection on the server-side `/me` call).
- **ux-reviewer:** PASS on T1.9 after a BLOCKER (credentials in the URL when a form was submitted before hydration) and Swahili being served before G5. axe: 0 violations on 22 scenes at 360 and 1280 px; Lighthouse accessibility and best practices 100.
- **ECC code review** (`ecc:code-reviewer`, `fb6131d..HEAD`): APPROVE with 0 findings; its one low-confidence note (SARIF rule resolution) was fixed anyway in `15562b0`.
- **impeccable polish:** one refinement (recovery codes in five even rows, tighter code tracking); design detector clean.
- **chrome-devtools:** no console errors and no failed requests on landing, signup, link sign-in, `/dev` and `/settings/security`; `/login` LCP 596 ms and CLS 0 on an idle machine (a first trace taken while the API was hashing a password showed 4.2 s of render delay).
- Every finding is recorded in `THREAT_MODEL.md` with the test that verifies it.

### REQ statuses

| Status | Count | Phase 1 REQ-IDs |
|---|---|---|
| DONE | 15 | REQ-HYG-01..06, REQ-FND-01..03, REQ-AUTH-01, REQ-TEN-01, REQ-CON-01, REQ-BIL-01, REQ-NOT-01, REQ-REM-00 |
| IN-PROGRESS | 1 | REQ-AUD-01 (chain, triggers and verifier done; the hourly RFC 3161 anchor and nightly Merkle root arrive with provenance in Phase 3) |

AC rows DONE: AC-HYG-01..06, AC-SEC-1/a, AC-SEC-4, AC-SEC-5, AC-REM-4/a. R-HYG-01..06 DONE.

### Demo steps

1. `make dev` (the first run builds the images; see `docs/runbooks/dev-setup.md`), then open http://localhost:3000.
2. Sign up as a developer; open the link from Mailpit (http://localhost:8025); you land on `/dev`.
3. In a second browser profile, sign up as an organisation; set up two-step sign-in on `/settings/security` (QR, code, recovery codes); log out and back in: `/auth/mfa` asks for the code.
4. RLS output: `cd backend && uv run pytest tests/integration/test_rls.py -q` (needs `TEST_DATABASE_ADMIN_URL`, or Docker for a throwaway Postgres).
5. `python docs/platform/checks/check_traceability.py` → PASS.

### Test counts

| Suite | Count | Where |
|---|---|---|
| Backend pytest (unit + integration: migrations, RLS, Hypothesis audit chain, auth security, seed) | 579 passed | CI on `b0877bf`; locally on Windows on `63bc78d` |
| Frontend Vitest | 105 passed (16 files) | CI |
| Playwright E2E + axe (360 px and desktop) | 22 passed | CI compose stack |
| Legacy suite | 313 OK on windows-latest; 307 OK on ubuntu (6 Linux-only ids skipped, D-25) | CI |
| Legacy runner tests | 10 (`scripts/test_run_legacy_tests.py`) | CI |

### Deviations

- **Commit size:** 25 of 155 non-merge commits exceed about 300 changed lines, excluding generated and lock files (the initial scaffolds, the schema revision, the seed data, the first auth and UI drops, and two large regression-test commits). The review-fix commits stayed within the limit. No history was rewritten.
- **MinIO → SeaweedFS** in the dev stack (D-24, open): the MinIO image was withdrawn; nothing in Phase 1 uses S3.
- **OAuth** moved from T1.5 to T2.12 / REQ-AUTH-02 (D-20).
- **Cookie names** are fixed in code (`__Host-bridge_{session,csrf,signup}` with Secure cookies, bare names without) instead of being settings. The web server reads `COOKIE_SECURE` from `infra/.env` and the API from `backend/.env`; a mismatch fails closed (signed-in pages redirect to `/login`).
- **Consent texts** moved to version `2026-09-25.1` because users could see the review markers; the wording is unchanged.
- **gitleaks allow-list** now holds the public RFC 6238 test vector and one reviewed test-token fingerprint (`.gitleaksignore`).

### Open decisions (see `DECISIONS-NEEDED.md`)

D-24 (S3 stand-in; SeaweedFS applied as the default; must be final before T2.3) and D-25 (four adviser TurnTests on the Linux skip list; option (a) applied). G1 inputs (region, domain, SMS vendor) are needed only for deploy config.

### Follow-ups (not blocking; picked up in Phase 2 unless the human says otherwise)

1. `/login` and `/signup` sit at the 150 KB JS budget line (150,378 gzipped bytes of scripts on `/signup`): send CSP and Permissions-Policy on page responses only (not on `/_next/static`), drop 14.4 kB of legacy polyfills with a modern browserslist target, and state whether the budget means KB or KiB.
2. E2E with parallel local workers can time out on argon2 hashing in the single API process (CI is green); pin `workers: 1` or a longer server step for local runs.
3. Password forms: add a hidden `autocomplete="username"` field so password managers save the right account (Chrome hint on `/settings/security`).
4. The Password section stays visible during two-step enrolment (visual noise; the labels are already distinct).
5. The staff dependency (staff role + enrolled TOTP) ships with the first `/admin` route.
6. The report-only CSP has no report endpoint yet; the enforced nonce CSP and HSTS arrive with Caddy in Phase 8 (REQ-SEC-03).

### Risks

1. One legacy test, `test_two_threads_cannot_speak_the_same_check_in`, failed once locally under load; CI is stable.
2. This machine intercepts TLS: uv needs `UV_NATIVE_TLS=1`, and Playwright's bundled Chromium lagged Playwright 1.63, so local runs used system Chrome (`channel: "chrome"`).
3. The recorded residuals are in `THREAT_MODEL.md` §1 (the per-address email budget can delay a real magic link for up to a day; the web server's cookie mode must match the API's; audit tail deletion is detectable only once anchors exist in Phase 3).

### Cost

`/cost` (pasted by the human): _pending_

### Next session

After the human approves Phase 1: `Read CLAUDE.md, PROGRESS.md, REQUIREMENTS.md, DECISIONS-NEEDED.md, GATES.md and the docs/spec files Phase 2 needs; execute Phase 2.` Phase 2 needs D-24 decided before T2.3, and the G6 directory seed inputs.

### Phase 1 sign-off

_Awaiting the human's approval._
