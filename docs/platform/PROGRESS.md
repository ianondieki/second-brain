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
| Every R01–R53 and R-HYG-01..06 → ≥1 REQ-ID and ≥1 AC | Yes (59/59), links verified in both directions |
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

(pending at the time of writing; updated when the run completes)

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
