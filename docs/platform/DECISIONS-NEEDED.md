# DECISIONS-NEEDED — open questions for the human

Phase 0 output, 2026-09-24. Each entry: question, why it matters, options, the default the agents will use if you say
nothing, and what it blocks. Answer by editing the **Decision** line (`Decision: <option> — <date>`), or by writing your
answer under the entry. Entries stay here until decided; decided entries move to the "Decided" section at the bottom.
Items marked **G0** must be decided before `G0: APPROVED` in `GATES.md`.

## Open

None. D-01..D-23 were decided at G0 (2026-09-24). New questions start at D-24.

## Decided

| Id | Decision | Date | Recorded in |
|---|---|---|---|
| D-01 · Budget per phase (G0) | (c) Max subscription, no USD cap; report /cost usage per phase and stop if a phase would exhaust the weekly limit | 2026-09-24 | `PLAN.md` §7; `PROGRESS.md` (G0 sign-off) |
| D-02 · precision@5 target for the ranker offline eval (G0) | (a) 0.6, revisit at G-EVAL | 2026-09-24 | This entry; AC-PERS-4 test (Phase 5), revisited at G-EVAL |
| D-03 · Pre-approved vendor / free-tier list (G0) | (a) approve the list as-is | 2026-09-24 | This entry (vendor list); `GATES.md` G0 |
| D-04 · Orchestrator model for Phases 1–7 | (b) Opus 5.5 xhigh for Phases 1–7; Fable for security-reviewer and Phase 8 | 2026-09-24 | `CLAUDE.md` session rules; `PLAN.md` §7 |
| D-05 · REQ-ID scheme and commit references | (a) commits/PRs may cite either a REQ-ID or an R-id; task cards are per REQ-ID | 2026-09-24 | `CLAUDE.md` commits and PRs; commit lint (Phase 1) |
| D-06 · Notification ids for decline, withdraw and expiry | (a) keep sub-row model | 2026-09-24 | `REQUIREMENTS.md` §5 (unchanged) |
| D-07 · Asserting some acceptance tests earlier than the spec's exit lists | (a) accept (earlier, never later) | 2026-09-24 | `PLAN.md` §5 (unchanged) |
| D-08 · Next.js major version pin | (a) pin latest at Phase 1 kickoff | 2026-09-24 | ADR-001 addendum at Phase 1 kickoff (T1.3) |
| D-09 · Placeholder product name "Bridge" | (a) keep bridge as package name | 2026-09-24 | ADR-001 (unchanged) |
| D-10 · Hosting region, product domain, SMS vendor (G1) | (a) af-south-1 + Africa's Talking; domain to be chosen at G1 | 2026-09-24 | ADR-007; domain at G1 (`GATES.md`) |
| D-11 · Commit attribution lines | (a) keep the single `Co-Authored-By: Claude <noreply@anthropic.com>` trailer | 2026-09-24 | `CLAUDE.md` commits and PRs (unchanged) |
| D-12 · Linux skip list is unverified until Phase 1 CI | (a) T1.2 first runs the full suite on ubuntu without the skip list (non-blocking job), then amends the list to match reality | 2026-09-24 | `PLAN.md` T1.2 |
| D-13 · The two `CheckTests` also fail on windows-latest without a cloudflared binary | (a) dummy ADVISER_CLOUDFLARED file in CI | 2026-09-24 | `PLAN.md` T1.2; `scripts/run_legacy_tests.py` and the CI workflow (Phase 1) |
| D-14 · Named people for legal roles (G2) | (b) name DPO, custodian and advocate at G2 | 2026-09-24 | `GATES.md` G2 |
| D-15 · Accept the honest positioning on idea protection | (a) accept honest positioning | 2026-09-24 | `THREAT_MODEL.md` §8; approved phrasing in `docs/spec/04` 4.2 |
| D-16 · Timestamp authority providers | (a) free TSAs for Release 1 | 2026-09-24 | ADR-003 (unchanged) |
| D-17 · Postmark account (new vendor) | (a) Postmark account before Phase 8 | 2026-09-24 | ADR-004; account needed before Phase 8 |
| D-18 · Anthropic API key for the nightly evals (spend) | (c) cassettes only until launch, no API spend | 2026-09-24 | This entry; to apply to `PLAN.md` T4.6 and X4-2 before Phase 4 |
| D-19 · Who performs D2 KYC manual review and E2 entity review in the pilot | (a) I do the manual reviews in the pilot | 2026-09-24 | ADR-002; `docs/runbooks/verification.md` (Phase 2) |
| D-20 · OAuth test applications | (b) magic-link + password first, OAuth in Phase 2 | 2026-09-24 | Applied at Phase 1 kickoff: `PLAN.md` T1.5 and T2.12; `REQUIREMENTS.md` REQ-AUTH-02 (Phase 2) |
| D-21 · Provisional directory seed sources for fixtures | (a) agents build the provisional list from the registers in `docs/spec/06` 6.2, source URL and date per row | 2026-09-24 | REQ-DIR-02 (Phase 2) |
| D-22 · When to stand up staging | (a) staging in Phase 8 | 2026-09-24 | `PLAN.md` Phase 8 (unchanged) |
| D-23 · Python versions in CI | (a) legacy on 3.13, backend on 3.12 | 2026-09-24 | `PLAN.md` T1.2/T1.3 CI jobs |

The full entries (why, options, default, what they blocked) are kept below for the record.

### D-01 · Budget per phase (G0)
- Why: `docs/spec/12` 12.4 makes budget a G0 input; exceeding a phase budget is a stop-and-ask condition (`docs/spec/12` 12.5).
- Options: (a) one total for Phases 1–8 with a per-phase cap = total × phase weight (weights proposed: 1: 8%, 2: 18%, 3: 20%, 4: 12%, 5: 14%, 6: 8%, 7: 8%, 8: 12%); (b) a flat cap per phase; (c) no cap, report `/cost` only.
- Recommended default: (a). Record the numbers in `PLAN.md` §7.
- Blocks: G0.
- Decision: (c) Max subscription, no USD cap; report /cost usage per phase and stop if a phase would exhaust the weekly limit — 2026-09-24

### D-02 · precision@5 target for the ranker offline eval (G0)
- Why: AC-PERS-4 asserts "target precision@5 agreed at G0" against ≥30 human-labelled pairs supplied at G-EVAL.
- Options: (a) 0.6 (reasonable for a hybrid ranker with cold-start personas); (b) 0.7 (stretch); (c) report only, no gate, until 200 active developers.
- Recommended default: (a) 0.6, revisited at G-EVAL when the labelled set exists.
- Blocks: G0 (value), Phase 5 exit (test).
- Decision: (a) 0.6, revisit at G-EVAL — 2026-09-24

### D-03 · Pre-approved vendor / free-tier list (G0)
- Why: any new paid vendor is a stop-and-ask; pre-approval lets Phase 8 proceed. Every account is created by you; agents never sign up for services.
- Proposed list (all free tiers or pay-as-you-go, ADR-007): AWS (af-south-1 + eu-west-1 backups), Cloudflare (free), Postmark (developer tier), Sentry (developer), Grafana Cloud (free), Better Stack (free), healthchecks.io (free), DigiCert public TSA + FreeTSA (free), an SMS vendor (Africa's Talking or equivalent, D-10), Langfuse Cloud (optional, free), GitHub Actions (included), GHCR (included).
- Options: (a) approve the list as-is; (b) approve with removals; (c) approve per vendor at Phase 8 (slower).
- Recommended default: (a).
- Blocks: G0.
- Decision: (a) approve the list as-is — 2026-09-24

### D-04 · Orchestrator model for Phases 1–7
- Why: `docs/spec/00` 0.2 offers a cheaper alternative (Opus 5.5 at `xhigh` for Phases 1–7; Fable kept for Phase 0, `security-reviewer` and the Phase 8 audit).
- Options: (a) Fable 5.1 `xhigh` throughout (highest quality, highest cost); (b) Opus 5.5 `xhigh` for Phases 1–7 (2.5× cheaper on orchestration tokens).
- Recommended default: (a) if D-01 allows it; otherwise (b).
- Blocks: nothing until Phase 1 starts.
- Decision: (b) Opus 5.5 xhigh for Phases 1–7; Fable for security-reviewer and Phase 8 — 2026-09-24

### D-05 · REQ-ID scheme and commit references
- Why: `docs/spec/12` 12.1 says commits name "≥1 REQ-ID (R01–R53 plus R-HYG and AC ids)"; `REQUIREMENTS.md` introduces finer `REQ-<MODULE>-<nn>` rows and task cards per REQ-ID.
- Options: (a) commits/PRs may cite either a REQ-ID or an R-id; task cards are per REQ-ID (current plan); (b) commits must cite the REQ-ID only; (c) drop REQ-IDs and use R-ids as task cards (coarser, 59 cards).
- Recommended default: (a).
- Blocks: nothing; affects the commit lint added in Phase 1.
- Decision: (a) — 2026-09-24

### D-06 · Notification ids for decline, withdraw and expiry
- Why: the spec's matrix N01–N23 has no dedicated ids for `DECLINED` (EM4 🔒), `WITHDRAWN` and the `EXPIRED` variants; `REQUIREMENTS.md` §5 folds them into the stage where they occur (sub-rows) and lists EM8 as a side row.
- Options: (a) keep the sub-row model (no new ids); (b) add N24 decline, N25 withdraw, N26 expiry, N27 verification result (spec change).
- Recommended default: (a); the dispatch code keys on (state, event) anyway.
- Blocks: nothing; cosmetic until Phase 3.
- Decision: (a) keep sub-row model — 2026-09-24

### D-07 · Asserting some acceptance tests earlier than the spec's exit lists
- Why: `PLAN.md` §5 asserts AC-SEC-2/4/5/6 and AC-SUB-1/5/7 as soon as the feature exists (Phases 1–3) and re-runs them at the spec's phase. The check script flags these as warnings only.
- Options: (a) accept (earlier, never later); (b) assert only at the spec's phase.
- Recommended default: (a).
- Blocks: nothing.
- Decision: (a) — 2026-09-24

### D-08 · Next.js major version pin
- Why: `docs/spec/08` says "current stable major, pinned in ADR-001"; ADR-001 item 4 defers the exact number to the `researcher` at Phase 1 kickoff (npm `latest`).
- Options: (a) pin whatever `latest` is at Phase 1 kickoff and record it as an ADR-001 addendum; (b) you name the major now.
- Recommended default: (a).
- Blocks: T1.3 scaffold.
- Decision: (a) pin latest at Phase 1 kickoff — 2026-09-24

### D-09 · Placeholder product name "Bridge"
- Why: ADR-001 uses `Bridge` for the Python package (`bridge`), i18n namespace and UI working title until G5. Renaming the package later is a code change; renaming the UI title is a config change.
- Options: (a) keep `bridge` as the permanent package name regardless of the G5 brand; (b) choose the final name before Phase 1 so the package matches; (c) use a neutral package name (`platform`) now.
- Recommended default: (a).
- Blocks: T1.3 scaffold (package name).
- Decision: (a) keep bridge as package name — 2026-09-24

### D-10 · Hosting region, product domain, SMS vendor (G1)
- Why: ADR-007 defaults to AWS `af-south-1` behind Cloudflare; D1 phone OTP needs an SMS vendor; the sender domain is needed for G7.
- Options: region (a) `af-south-1` (default) or (b) a Kenyan data centre; SMS (a) Africa's Talking or (b) another CA-licensed aggregator; domain: your choice.
- Recommended default: `af-south-1`, Africa's Talking (Fake provider in CI regardless).
- Blocks: G1 (deploy config only).
- Decision: (a) af-south-1 + Africa's Talking; domain to be chosen at G1 — 2026-09-24

### D-11 · Commit attribution lines
- Why: `docs/spec/00` says commits end "with the attribution lines in CLAUDE.md"; none existed. `CLAUDE.md` now defines the trailer `Co-Authored-By: Claude <noreply@anthropic.com>` (used on every Phase 0 commit).
- Options: (a) keep that single trailer; (b) add `🤖 Generated with [Claude Code](https://claude.com/claude-code)`; (c) different wording.
- Recommended default: (a).
- Blocks: nothing.
- Decision: (a) — 2026-09-24

### D-12 · Linux skip list is unverified until Phase 1 CI
- Why: `docs/platform/tests_skip_linux.txt` was derived by reading `tests/`, not by running on ubuntu. Phase 1 T1.2 must confirm that exactly those four ids fail on ubuntu and nothing else.
- Options: (a) T1.2 first runs the full suite on ubuntu without the skip list in a non-blocking CI job, then amends the list to match reality (any extra failure is reported here, not silently added); (b) accept the list as-is.
- Recommended default: (a).
- Blocks: nothing.
- Decision: (a) — 2026-09-24

### D-13 · The two `CheckTests` also fail on windows-latest without a cloudflared binary
- Why: `adviser.__main__.check()` returns non-zero unless `tools/cloudflared.exe` (gitignored), `cloudflared` on PATH, or `ADVISER_CLOUDFLARED` exists, and unless `edge_tts`, `soundfile`, `langgraph`, `langchain_groq` import. The spec requires the full suite to pass on windows-latest, which will not hold on a clean runner.
- Options: (a) in CI set `ADVISER_CLOUDFLARED` to a small dummy file created by the workflow (the check only tests `os.path.isfile`) and install `requirements.txt`; (b) download the real cloudflared binary in CI; (c) skip the two tests on Windows too (contradicts the spec).
- Recommended default: (a), documented in `scripts/run_legacy_tests.py` and the workflow.
- Blocks: Phase 1 T1.2.
- Decision: (a) dummy ADVISER_CLOUDFLARED file in CI — 2026-09-24

### D-14 · Named people for legal roles (G2)
- Why: `docs/spec/10` needs a DPO (s.24), a records custodian (s.106B certificates), and a Kenyan advocate for template review; ADR-003 relies on the custodian.
- Options: (a) you name them now; (b) name them at G2.
- Recommended default: (b), but the advocate engagement should start during Phase 2 so G2 does not delay Phase 8.
- Blocks: G2.
- Decision: (b) name DPO, custodian and advocate at G2 — 2026-09-24

### D-15 · Accept the honest positioning on idea protection
- Why: `THREAT_MODEL.md` §8 risk 1: screenshots of Tier 2 cannot be prevented; the product offers evidence + controlled disclosure + traceability + a dispute path. Copy must never say "theft-proof" (AC-IP-4).
- Options: (a) accept and use the approved phrasing from `docs/spec/04` 4.2; (b) request additional controls (DRM-style viewers were rejected in ADR-003).
- Recommended default: (a).
- Blocks: nothing technically; affects marketing copy at G5.
- Decision: (a) accept honest positioning — 2026-09-24

### D-16 · Timestamp authority providers
- Why: ADR-003 uses DigiCert's public RFC 3161 TSA as primary and FreeTSA as fallback; both are free but offer no SLA.
- Options: (a) accept free TSAs for Release 1; (b) budget for a paid TSA with an SLA.
- Recommended default: (a); the hourly anchor job retries and the UI shows "Timestamp pending".
- Blocks: nothing.
- Decision: (a) free TSAs for Release 1 — 2026-09-24

### D-17 · Postmark account (new vendor)
- Why: ADR-004 picks Postmark; creating the account is a human action and a potential spend (developer tier is free for 100 emails/month). SES is the fallback adapter.
- Options: (a) create a Postmark account before Phase 8 (staging uses Mailpit until then); (b) use SES instead.
- Recommended default: (a).
- Blocks: G7 / real email only.
- Decision: (a) Postmark account before Phase 8 — 2026-09-24

### D-18 · Anthropic API key for the nightly evals (spend)
- Why: `nightly.yml` runs live evals capped at USD 5 per run with a separate key; any spend needs approval (`docs/spec/12` 12.5). All PR/`main` jobs use cassettes and fakes.
- Options: (a) approve ≤USD 5 per nightly run (≈USD 150/month worst case) and provide a dedicated key in GitHub secrets at Phase 4; (b) run evals weekly instead (≈USD 20/month); (c) cassettes only until launch.
- Recommended default: (b) weekly until Phase 5, nightly from Phase 8.
- Blocks: Phase 4 X4-2.
- Decision: (c) cassettes only until launch, no API spend — 2026-09-24

### D-19 · Who performs D2 KYC manual review and E2 entity review in the pilot
- Why: ADR-002 uses `ManualReview` by staff `admin`; someone must look at ID images and BRS/CR12/KRA documents within 2 BD.
- Options: (a) you; (b) a named ops person; (c) defer D2 (no deal rooms/signing) until a KYC vendor in Release 2.
- Recommended default: (a) for the anchor pilot.
- Blocks: nothing until Phase 2 staging use; affects `docs/runbooks/verification.md`.
- Decision: (a) I do the manual reviews in the pilot — 2026-09-24

### D-20 · OAuth test applications
- Why: REQ-AUTH-01 needs GitHub and Google OAuth apps (test credentials in `.env`). Creating them requires your accounts.
- Options: (a) create test apps before Phase 1 T1.5; (b) Phase 1 ships magic-link + password only and OAuth lands in Phase 2.
- Recommended default: (a); fall back to (b) without blocking.
- Blocks: T1.5 OAuth part only.
- Decision: (b) magic-link + password first, OAuth in Phase 2 — 2026-09-24

### D-21 · Provisional directory seed sources for fixtures
- Why: REQ-DIR-02 builds `seed/ke_provisional.yaml` from public registers (CA licensees, CBK banks/MFBs, SASRA SACCOs, CUE/TVETA, 47 counties, MDAs, PBO registry). Phase 2 fixtures only need the wedge niches, telecom licensees and counties; G6 approves the production list.
- Options: (a) agents build the provisional list from the registers in `docs/spec/06` 6.2 with source URL and date per row; (b) you supply a list.
- Recommended default: (a).
- Blocks: nothing.
- Decision: (a) — 2026-09-24

### D-22 · When to stand up staging
- Why: `PLAN.md` deploys staging in Phase 8; an earlier staging (Phase 3) would let you try the tracker with real emails in Mailpit but needs G1 values and AWS spend.
- Options: (a) Phase 8 (default, no cloud spend before then); (b) Phase 3.
- Recommended default: (a).
- Blocks: nothing.
- Decision: (a) staging in Phase 8 — 2026-09-24

### D-23 · Python versions in CI
- Why: the legacy suite runs locally on Python 3.13; the backend is specified as Python 3.12 (`docs/spec/08`).
- Options: (a) two jobs: legacy on 3.13, backend on 3.12; (b) run both on 3.12; (c) move the backend to 3.13.
- Recommended default: (a).
- Blocks: T1.2/T1.3.
- Decision: (a) legacy on 3.13, backend on 3.12 — 2026-09-24
