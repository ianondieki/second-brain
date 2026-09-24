# PLAN — Developer ⇄ Enterprise platform ("Bridge", working name)

Phase 0 output, 2026-09-24. Source spec: `docs/spec/` (indexed in `CLAUDE.md`). Requirements and acceptance tests:
`docs/platform/REQUIREMENTS.md`. Gates: `docs/platform/GATES.md`. Open questions: `docs/platform/DECISIONS-NEEDED.md`.
Progress and phase reports: `docs/platform/PROGRESS.md`.

## 1. Ground rules (apply to every phase)

- **Branch**: all work merges into `claude/eloquent-hypatia-aa3577`; `main` is touched only by the human at G8.
- **One phase per session**; the orchestrator (main session, Fable 5.1, `xhigh`; `max` in Phases 0 and 8) reads `CLAUDE.md`, the spec files the phase needs, `PROGRESS.md`, `REQUIREMENTS.md`, `DECISIONS-NEEDED.md`, then follows the build workflow in `CLAUDE.md` (context → plan → build → test → UI → browser bugs → review → report → gate).
- **Task cards** `docs/platform/tasks/<REQ-ID>.md` (REQ-IDs, files owned, acceptance criteria, agent, model, effort) are written by the orchestrator before any implementer starts. Overlapping file sets never run concurrently; ≤3 implementers at a time, each in `git worktree add ../sb-wt/<REQ-ID> -b feat/<REQ-ID>-<slug> claude/eloquent-hypatia-aa3577`.
- **Only `db-migrations`** creates Alembic revisions (one per PR, expand/contract, `alembic check`). `backend/openapi.json` is frozen before frontend and backend work on one feature in parallel.
- **Every PR**: `make check` green, `reviewer` PASS, `security-reviewer` PASS when it touches `auth/`, `tenancy/`, `billing/`, `provenance/`, `engagements/`; `ux-reviewer` PASS on frontend PRs from Phase 2 on; tests never deleted or skipped to go green; no `--no-verify`.
- **Commits**: small conventional commits naming a REQ-ID or R-id (`feat(REQ-ENG-01): add engagement state machine`), ending with the attribution lines in `CLAUDE.md`.
- **Secrets**: sandbox/test credentials only, in an untracked `.env`; `.env.example` files document every variable; the app fails closed when a secret is missing.
- **Stop and ask** (write to `DECISIONS-NEEDED.md`): outbound message to a non-test recipient, destructive migration, force-push, any spend or new vendor, MUST conflict, CI red after 3 genuine fixes, legal/claims copy, a gate, budget exceeded.
- **Phase exit** = every AC listed for the phase in §4 passes in CI on the integration branch, the phase report is in `PROGRESS.md`, the scripted demo is recorded, `docs/platform/checks/check_traceability.py` passes, and the human signs the gate (if any).

## 2. Phase 0 — Discovery & plan (this session, docs only)

Deliverables (all under `docs/platform/`, `.claude/agents/`, `CLAUDE.md`): `PLAN.md`, `REQUIREMENTS.md`, `adr/001..008`,
`THREAT_MODEL.md`, `GATES.md`, `DECISIONS-NEEDED.md`, `tests_skip_linux.txt`, `checks/check_traceability.py`,
`.claude/agents/*.md`, updated `CLAUDE.md`, `PROGRESS.md` Phase 0 report. Exit: every R01–R53 and R-HYG-01..06 maps to
≥1 REQ-ID and ≥1 AC; no phase exit depends on a later phase (both verified by the check script); human writes
`G0: APPROVED <date>` in `GATES.md`.

## 3. Phases 1–8

Each phase lists: goal, REQ-IDs in scope, ordered tasks (task id → REQ-IDs → agent), exit checks (AC ids are the
canonical list in §4; extra checks are named `X<phase>-<n>`), gates, demo. Agents: `impl-backend` (B),
`impl-frontend` (F), `impl-integrations` (I), `impl-ai` (A), `db-migrations` (M), `test-writer` (T), `reviewer` (R),
`security-reviewer` (S), `ux-reviewer` (U), `docs-writer` (D), `researcher` (Rs), `chore` (C).

### Phase 1 — Hygiene & foundation

Goal: a green CI on an empty but real platform skeleton, the legacy tool untouched, hygiene fixed.
Spec to read: `docs/spec/02`, `03`, `04`, `05` (plans table), `08`, `10`, `11`, `12`, `14`.
REQ-IDs: REQ-HYG-01..06, REQ-FND-01, REQ-FND-02, REQ-FND-03, REQ-AUTH-01, REQ-TEN-01, REQ-AUD-01, REQ-CON-01, REQ-BIL-01, REQ-NOT-01, REQ-REM-00.

| Task | REQ-IDs | Agent | Order / notes |
|---|---|---|---|
| T1.1 Archive legacy into `legacy/` (one `git mv` commit + README), delete `reminder/second-brain.code-workspace`, fix docs/README channel text, `.env.example` trimmed (GMAIL_*, REMINDER_EMAIL_TO, GROQ_*, WA_*, ADVISER_*), `GROQ_MODEL=openai/gpt-oss-20b`, `TZ=Africa/Nairobi`, single `docs/10-*` | REQ-HYG-01..06, REQ-FND-01 | C then D | First; unblocks the AC-HYG grep checks |
| T1.2 `scripts/run_legacy_tests.py` (discover `tests`, drop ids from `docs/platform/tests_skip_linux.txt` when `sys.platform != 'win32'`, non-zero on failure); gitignore the `C:/` dir the suite creates on Linux; CI matrix ubuntu + windows-latest; verify or amend the skip list (DECISIONS-NEEDED D-12, D-13) | REQ-FND-01 | B, T | Runs on both OSes before anything else lands |
| T1.3 Scaffold `backend/` (uv, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, Procrastinate, structlog), `frontend/` (Next.js pinned per ADR-001, Tailwind, shadcn/ui, next-intl, openapi-typescript), `infra/docker-compose.dev.yml` (Postgres 16 + pgvector, Mailpit, MinIO, ClamAV), `Makefile` (`make dev`, `make check`), `.github/workflows/pr.yml` with scanners (gitleaks, pip-audit, npm audit, osv-scanner, Trivy, CodeQL) and egress-blocked runner, `backend/.env.example`, `frontend/.env.example` | REQ-FND-02, REQ-FND-03 | B, F, I | After T1.2; `make check` must be green on the empty skeleton |
| T1.4 Core schema v1 (users, auth_identities, sessions, api_tokens, organizations, memberships, invitations, niches, org_niches, developer_niches, developer_profiles, consents, audit_events + event_details, notification_preferences, notification_deliveries, in_app_notifications, plans, subscriptions, holidays, regions) with RLS policies, append-only triggers, separate owner role, `python -m bridge.seed` (niches, plans, holidays, KE + the 47 counties) | REQ-TEN-01, REQ-AUD-01, REQ-CON-01 | M (schema), B | One migration per PR; RLS test generator lands with the first org-scoped table |
| T1.5 Auth: signup/login (argon2id), magic links, GitHub + Google OAuth (test apps), sessions + CSRF, TOTP enrol/verify, step-up helper; roles + `require_role`; error semantics 404/403 | REQ-AUTH-01, REQ-TEN-01 | B, F, S review | Depends on T1.4 |
| T1.6 `plans.yaml` placeholders + entitlement middleware (402 with upgrade path), subscription rows for free plans | REQ-BIL-01 | B | Depends on T1.4 |
| T1.7 `EmailProvider` (Postmark adapter, Mailpit sink), `notification_deliveries` ledger, retry classification ported from `reminder/notify.py` | REQ-NOT-01 | I | Independent of T1.5 |
| T1.8 Port `classify`/`fallback_text`/policy to `bridge/reminders/{policy,compose}.py` with parity tests against `reminder/` fixtures; business-day calendar helper | REQ-REM-00 | B, T | Independent |
| T1.9 Signup/login E2E (Playwright, 360 px + desktop), axe on the auth pages; `docs/runbooks/dev-setup.md` | REQ-AUTH-01 | T, F, D | Last |

Exit checks: AC-HYG-01..06, AC-SEC-1/a, AC-SEC-4, AC-SEC-5, AC-REM-4/a; X1-1 signup/login E2E passes on the compose
stack; X1-2 `make check` green on ubuntu and windows (legacy suite full on windows, skip list on ubuntu); X1-3
`python -m bridge.seed` idempotent (run twice, same row counts). Gate: G1 inputs (region, domain, SMS vendor) are needed
only for deploy config, not for this exit. Demo: `make dev`, sign up as developer and as org, TOTP enrol, RLS test output.

### Phase 2 — Repository, directory, provenance

Goal: developers publish tiered proposals with a disclosure record; orgs browse, claim and receive NDA-gated Tier 2.
Spec to read: `docs/spec/03`, `04`, `05`, `06` (6.1–6.4, 6.12 moderation), `08`, `09`, `10`.
REQ-IDs: REQ-REPO-01..03, REQ-PROP-01..05, REQ-PROV-01..05, REQ-DIR-01..05, REQ-NOT-02, REQ-LLM-01, REQ-EMB-01, REQ-MOD-01, REQ-BIL-02, REQ-BIL-03, REQ-SEC-01.

| Task | REQ-IDs | Agent | Order / notes |
|---|---|---|---|
| T2.1 Schema v2: problems, problem_sources, problem_briefs, proposals, proposal_versions, proposal_confidential (+ embeddings table, DB roles `tier2_reader`, `provenance_worker`, `tier2_embed_worker`, `tier2_moderation`, `dsr_exporter`, `aggregate_worker`), proposal_attachments, provenance_records, attestations, tags, nda_templates, nda_acceptances, disclosure_grants, document_views, signal_events, moderation_cases, legal_templates, llm_calls, and the `engagements` skeleton (`proposal_id`, `org_id`, `origin`, `state` enum, unique(proposal_id, org_id); no transitions yet, fixture-driven so `can_view_tier2` and the render marks can be tested); `has_table_privilege` migration test | REQ-REPO-01, REQ-PROV-01, REQ-TEN-01 | M | First; freezes `openapi.json` after T2.2 |
| T2.2 LLM layer (`bridge/llm`: `LLMClient`, `AnthropicAdapter`, `ai/models.yaml`, ledger, caps, kill switch, sanitiser + nonce framing, fakes/cassettes) and embeddings (`bge-m3` worker + fixed-vector fake) | REQ-LLM-01, REQ-EMB-01 | A | Parallel with T2.1 |
| T2.3 Proposal model + editor wizard (Tier 0/1/2), linked Problem picker or "Describe a new problem", niche/maturity/ask, attachments (presigned, ClamAV, PDF re-render), Tier-1 sanitiser, moderation holds, over-disclosure warn-only check | REQ-PROP-01, REQ-PROP-02, REQ-MOD-01 | B, F, A | After T2.1/T2.2 |
| T2.4 Provenance: manifest canonicalisation, hash, Ed25519 (KMS or local key in dev), RFC 3161 client (local `openssl ts` test CA), certificate PDF, `/verify`, `/.well-known/provenance-keys.json`, banned-claims lint in CI, chain anchor job | REQ-PROV-01, REQ-PROV-02, REQ-AUD-01 | B, I, S review | After T2.1 |
| T2.5 `can_view_tier2` predicate, Evaluation NDA acceptance, disclosure grants + owner policy, unlock quota, watermarked server-side renders (overlay + metadata `view_id`), access log + "Who has seen this", step-up on policy changes, `FEATURE_TIER2_ENABLED` | REQ-REPO-01, REQ-PROV-03, REQ-BIL-03, REQ-SEC-01 | B, F, S review | After T2.3/T2.4 |
| T2.6 Directory: niche taxonomy + org types seed, `seed/ke_provisional.yaml` (E0, public sources only), browse/filter UI, badge copy, claim flow E1 (domain OTP + DNS TXT, free-mail/punycode/homoglyph blocks) and E2 (`ManualReviewVerifier`, admin queue, Master Enterprise Terms acceptance by the Signatory against a `[[LEGAL-PLACEHOLDER]]` template with its hash recorded), competing-claim dispute case, invitations policy + suppression, Problem Briefs | REQ-DIR-01..05, REQ-ADM-01 (queue only) | B, F, Rs (sources) | Parallel with T2.3 |
| T2.7 Pitch to company: picker grouped by niche with E0/E1/E2, multi-tag with plan cap, held tags, one open tag per (developer, org) 409, cooldown; EM1; tag privacy guarantees | REQ-PROP-03, REQ-REPO-03, REQ-NOT-02, REQ-BIL-02 | B, F, I | After T2.3, T2.6 |
| T2.8 Browse repo search + filters (Tier-1 only), Schemathesis contract tests for leakage | REQ-REPO-02 | B, T | After T2.3 |
| T2.9 Originality check (MinHash LSH + bge-m3 bands, ≤10/day) + Tier-2-vs-Tier-2 moderator job; submission assistant behind `tier2_llm_assistant` consent | REQ-PROP-04, REQ-PROP-05 | A | After T2.2/T2.3 |
| T2.10 Developer verification D1 (`SmsProvider` fake), D2 `ManualReview` KYC bucket + 72 h purge, attestations, delete-retains-evidence | REQ-PROV-04, REQ-PROV-05 | B, I | Parallel |
| T2.11 Frontend polish pass (frontend-design → impeccable → Playwright 375/1440 screenshots), `ux-reviewer` on every frontend PR from here | all frontend REQs | F, U | Last |

Exit checks: AC-SEC-1/b, AC-SEC-2, AC-SEC-6, AC-REPO-1, AC-REPO-2, AC-REPO-3, AC-REPO-4/a, AC-REPO-5, AC-REPO-6/a,
AC-DIR-1, AC-DIR-2, AC-DIR-3, AC-DIR-4, AC-DIR-5/a, AC-DIR-6, AC-DIR-7, AC-PROP-1/a, AC-PROP-2, AC-PROP-4, AC-PROP-5,
AC-PROP-6, AC-PROP-7, AC-IP-1, AC-IP-2, AC-IP-4, AC-IP-5, AC-IP-6, AC-IP-9, AC-SUB-1, AC-SUB-7; X2-1 `openapi.json`
drift check green; X2-2 coverage ≥95% on `provenance/`, `auth/`, `tenancy/`. Gates: none required (G6 only for
production directory). Demo: publish a proposal, download certificate, verify on `/verify`, claim a fixture org, accept
NDA, view watermarked Tier 2, see the view in "Who has seen this".

### Phase 3 — Core loop: tracker, approval email, reminders

Goal: the full engagement lifecycle from `SUBMITTED` to `CLOSED`, EM2, notifications N01–N23 (except N02), reminders.
Spec to read: `docs/spec/03`, `04`, `06` (6.3 tail, 6.9, 6.10, 6.11), `08` (jobs), `10` (sector rules).
REQ-IDs: REQ-ENG-01..12, REQ-BD-01, REQ-NOT-03..06, REQ-REM-01, REQ-REM-02, REQ-SEC-01 (deals flag).

| Task | REQ-IDs | Agent | Order / notes |
|---|---|---|---|
| T3.1 Schema v3: engagements (extend the Phase 2 skeleton: health, stage_deadline_at, lock_version, end_reason), engagement_events (hash chain, INSERT-only), endorsements, milestones, agreements, signatures, threads/messages, internal_notes, disputes, legal_holds, agent_matches (fixture use), wa_contacts/wa_inbound (schema only) | REQ-ENG-01, REQ-ENG-02 | M | First |
| T3.2 `engagements/state_machine.py` transition table + `policy.yaml` deadlines, generated role matrix, 409/403 guards, business-day calendar with holidays file, test clock (staging/test only, excluded from prod image) | REQ-ENG-01, REQ-BD-01, REQ-ENG-12 | B, T (Hypothesis) | Core; everything else depends on it |
| T3.3 Stage 0 (`ORG_INTEREST` from `org_agent_match`/`org_browse`), stages 1–3 incl. Approve to proceed (contact fields), Decline reason codes with attestation, Request info, expiries, responsiveness score, `PROCUREMENT_ROUTE` | REQ-ENG-04, REQ-ENG-05, REQ-ENG-06 | B, F | After T3.2 |
| T3.4 Notification dispatch generated from the state machine (N01–N23 except N02), preferences, 🔒 rules, in-app bell; EM2 (exact copy, dedupe, `tier2_status`, public-entity addendum), EM4/EM5/EM6/EM8, status-change layout; copy-lint fixtures | REQ-NOT-03, REQ-NOT-04, REQ-NOT-05, REQ-NOT-06 | I, B | After T3.2 |
| T3.5 Stages 4–7: contact confirmation, mutual NDA send/upload/waive, deal room (Tier 3), negotiation versions, exclusivity term sheet → siblings `ON_HOLD (EXCLUSIVITY_GRANTED)` with auto-resume | REQ-ENG-07 | B, F | After T3.3 |
| T3.6 Stages 8–13: agreement Final form (IP terms, milestones, deemed acceptance), `SignatureProvider` internal e-signature with step-up, "Signed outside", milestone sub-tracker, delivery, sign-off, payment recorded/confirmed, mismatch → `DISPUTED`, `CLOSED` + IP record and provenance event | REQ-ENG-08, REQ-ENG-09 | B, F, S review | After T3.5 |
| T3.7 Side branches: `WITHDRAWN` (revokes Tier 2), `ON_HOLD`, `DISPUTED` skeleton (opens legal hold), `TERMINATED`, `INFO_REQUESTED`; Messages thread gated by stage; Internal notes | REQ-ENG-10, REQ-ENG-11 | B, F | After T3.3 |
| T3.8 Tracker UI: 5-group stepper, dual-endorsement rows, whose-turn banner, chips, History tab, identical canonical JSON for both parties; visual snapshots 360/1280 | REQ-ENG-03, REQ-ENG-02 | F, U | Parallel from T3.3 |
| T3.9 Reminders: health rules in code (`bridge/reminders/policy.py`), `reminders.dispatch` */15 min with `send_after_hour`, EM7 developer version (Haiku wording + fallback), `reminders.org_digest` 08:30 with fact tuples, `engagements.sla_check` hourly | REQ-REM-01, REQ-REM-02 | B, A, I | After T3.6 |
| T3.10 Trace tool (staff-only, inside an open dispute) recovering `view_id` from metadata + overlay | REQ-PROV-03 | B | Parallel |
| T3.11 E2E happy path Submitted → Closed + Decline/Withdraw/Expiry/On hold/Dispute/ORG_INTEREST (Playwright, test clock) | REQ-ENG-* | T | Last |

Exit checks: AC-TRACK-1..7, AC-TRACK-8/a, AC-TRACK-9, AC-TRACK-10, AC-MAIL-1, AC-MAIL-2, AC-MAIL-3, AC-MAIL-5,
AC-REM-1, AC-REM-2, AC-REM-3, AC-REM-4/b, AC-PROP-1/b, AC-PROP-3, AC-IP-3/a, AC-IP-8, AC-SEC-7, AC-SUB-5; X3-1 E2E
happy path reaches `CLOSED`; X3-2 coverage ≥95% on `engagements/`. Gates: none. Demo: tag → approve (EM2 in Mailpit)
→ NDA → agreement → milestones → close, both parties' timelines side by side; developer EM7 and org digest from the test
clock.

### Phase 4 — Scout agents

Goal: every org plan has a working, safe scout with digests; injection suite green; G-EVAL signed.
Spec to read: `docs/spec/05` (scout frequencies), `06` (6.8, 6.10 EM3), `08` (jobs, LLM layer), `09`.
REQ-IDs: REQ-SCOUT-01, REQ-SCOUT-02, REQ-SCOUT-03, REQ-SCOUT-05, REQ-SCOUT-06, REQ-SCOUT-07 (there is no REQ-SCOUT-04; the feedback loop is part of REQ-SCOUT-01), REQ-EVAL-01.

| Task | REQ-IDs | Agent | Order / notes |
|---|---|---|---|
| T4.1 Schema v4: scout_agents, agent_runs, agent_matches (real), recommendations/impressions placeholders | REQ-SCOUT-01 | M | First |
| T4.2 Scout config form + Preview (last 30 days), recipients among Reviewer seats, `entitlement_tier` from subscription, feedback loop (`min_fit` ±5 after 5 signals, suggested exclusions to admin) | REQ-SCOUT-01 | B, F | After T4.1 |
| T4.3 Pipeline: SQL hard filters → bge-m3 top-200 → Haiku screen → Sonnet rubric `FitAssessment` → deterministic blend (`matching/weights_v1.yaml`); scout DB role without Tier-2 grants; one tenant per run; incremental cursor; cron/`on_new` scheduling per plan; Message Batches | REQ-SCOUT-02 | A, B | After T4.1 |
| T4.4 Digest EM3/N02 rendered by code (escaped, defanged, authenticated links, no state change on GET), niche label on items, sent only to verified opted-in Reviewer seats; below-E2 behaviour | REQ-SCOUT-03, REQ-SCOUT-07 | I, B | After T4.3 |
| T4.5 Cost ledger + per-tenant caps, degrade to embedding-only at 100%, soft-cap email at 80% | REQ-SCOUT-05 | B | Parallel |
| T4.6 Injection defences + `backend/tests/evals/` harness (cassettes per PR, nightly live ≤USD 5), injection gold set with clean twins (`synthetic=true`), scout gold set scaffolding for G-EVAL labels | REQ-SCOUT-06, REQ-EVAL-01 | A, T, S review | Parallel; blocks exit |
| T4.7 Stage-0 flow on a real digest (AC-TRACK-8/b), Reviewer 403, `org_browse` origin | REQ-ENG-04 | B, T | After T4.4 |

Exit checks: AC-SCOUT-1..8, AC-TRACK-8/b, AC-REPO-4/b, AC-DIR-5/b; X4-1 injection eval gates pass on cassettes
(recall ≥0.95, FPR ≤2%, score shift ≤5, zero injected links); X4-2 `nightly.yml` evals job runs once within budget.
Gate: **G-EVAL** (human labels for research, scout, ranker, judge sets) must be signed at this exit. Demo: configure a
scout, preview, run with the test clock, open the digest in Mailpit, express interest, developer accepts.

### Phase 5 — Research, trending, personalisation

Goal: cited problem cards, honest trending, an explained "what to pursue" list with the LTR pipeline in shadow mode.
Spec to read: `docs/spec/06` (6.5–6.7), `08` (jobs, embeddings), `09`, `05` (liked vs followed).
REQ-IDs: REQ-RES-01, REQ-RES-02, REQ-TREND-01, REQ-TREND-02, REQ-PERS-01..04.

| Task | REQ-IDs | Agent | Order / notes |
|---|---|---|---|
| T5.1 Schema v5: research_runs, problem card fields (confidence, cluster_id, ai_generated, status), recommendations (features jsonb, ranker_version, explanation), impressions, linked_repos | REQ-RES-01, REQ-PERS-01 | M | First |
| T5.2 Research agent: `sources/ke.yaml` allowlist (+ `ug.yaml` fixture), plan → search/fetch with citations → Haiku extraction (Batch) → validation in code → dedupe/cluster → synthesis → confidence → moderator approval; caps and cost logging; stale/archive jobs | REQ-RES-01, REQ-RES-02 | A, B, Rs | Core |
| T5.3 Trend scoring (`trends.recompute` 02:00): half-lives, per-niche z-scores, anti-gaming (unique verified accounts, 1 event/day, burst detector, ≥3 actors, Wilson bound), cold start; `signal_events` writer under `aggregate_worker` | REQ-TREND-01 | B | Parallel with T5.2 |
| T5.4 Discover UI: Trending Problems with sources and Why chips, Trending Projects beside problems, Opportunity Gap, niche/county filter, "Start a proposal from this problem"; badges never show org names; EM7 trending line unflagged | REQ-TREND-02 | F, B, U | After T5.3 |
| T5.5 Hybrid ranker f1–f10 (`ranking/weights_v1.yaml`), MMR, labels, pursuit recommendation in code, Why/Why-not chips, cold start, personalisation opt-out, `recommendations.recompute` 03:00; opt-in GitHub import for f9 | REQ-PERS-01, REQ-PERS-02, REQ-PERS-03 | A, B, F | After T5.1 |
| T5.6 Impressions/outcomes logging, LambdaMART pipeline (feature/label logging, IPS correction, offline NDCG harness, shadow scoring flag), offline eval set from G-EVAL labels with the G0 precision@5 target | REQ-PERS-04, REQ-EVAL-01 | A, T | After T5.5 |

Exit checks: AC-RES-1..4, AC-TREND-1..3, AC-PERS-1..7, AC-REPO-6/b; X5-1 research eval gates on cassettes (citation
validity 100%, unsupported numbers 0, injected card never created); X5-2 EM7 trending line unflagged: `reminders.dispatch`
renders the trending-problem line for a developer with followed niches with the Phase 3 feature flag removed
(`backend/tests/unit/reminders/test_trending_line.py`). Gates: G-EVAL labels (from Phase 4) feed AC-PERS-4.
Demo: run research for (Microfinance & SACCOs, KE) with cassettes, approve a card, see it trend and be recommended with
a pursuit chip, start a proposal from it.

### Phase 6 — Subscriptions & billing

Goal: paid plans work end to end in sandbox; callbacks are verified; grace and downgrade behave; invoices issued.
Spec to read: `docs/spec/05`, `08` (payments row, jobs), `10` (item 6), ADR-006.
REQ-IDs: REQ-BIL-04..08.

| Task | REQ-IDs | Agent | Order / notes |
|---|---|---|---|
| T6.1 Schema v6: payments, webhook_events, invoices; subscription state machine columns | REQ-BIL-06, REQ-BIL-07 | M | First |
| T6.2 `researcher`: current Daraja STK Push/Query API fields, Paystack webhook/verify, KRA eTIMS requirements, with citations into `docs/platform/research/billing.md` | REQ-BIL-04, REQ-BIL-05, REQ-BIL-07 | Rs | Parallel; never invent API fields |
| T6.3 Daraja adapter (STK Push, Query confirmation, unguessable callback path, reconciliation jobs), `respx` cassettes | REQ-BIL-04 | I, S review | After T6.2 |
| T6.4 Paystack hosted checkout + HMAC-SHA512 + verify, tokenised recurring, stored fields only | REQ-BIL-05 | I, S review | After T6.2 |
| T6.5 Subscription lifecycle (`trialing → active → past_due → downgraded \| cancelled`), renewal reminders (`billing.renewal_reminders` 09:00), grace, downgrade effects (scouts pause, quotas hidden, no deletion), one-click cancel, admin refunds | REQ-BIL-06 | B | After T6.1 |
| T6.6 `InvoiceIssuer` (sequential numbers, VAT rules, eTIMS adapter with Fake), invoice/LPO flow for Enterprise, receipts | REQ-BIL-07 | B, I | After T6.2 |
| T6.7 Plan & billing UI (Plan & billing menu, upgrade paths from 402, Student verification, Social Impact request, anchor coupon), `plans.yaml` with G3 values if signed | REQ-BIL-08 | F, B | Last |

Exit checks: AC-SUB-2, AC-SUB-3, AC-SUB-4, AC-SUB-6 (AC-SUB-1/5/7 re-run); X6-1 `security-reviewer` PASS on
`billing/`; X6-2 live keys untouched (no production values in repo or `.env.example`). Gates: G3 values before exit
values are final; G4 before any live payment (can follow launch). Demo: upgrade a developer to Pro via Daraja sandbox,
replay the callback (no-op), forge a Paystack signature (401), let an org lapse into grace and downgrade with the test clock.

### Phase 7 — UX consolidation

Goal: both portals are uncluttered, fast at 360 px, accessible, Swahili-ready.
Spec to read: `docs/spec/04` (4.6), `07`, ADR-001.
REQ-IDs: REQ-UX-01..07.

| Task | REQ-IDs | Agent | Order / notes |
|---|---|---|---|
| T7.1 Nav audit: ≤5 items per portal, bottom tabs / left rail, portal switcher, bell, avatar menu; admin console separate | REQ-UX-01 | F, U | First |
| T7.2 One primary action per screen (`[data-primary]`), ≤2 chips per card, whose-turn banner everywhere | REQ-UX-02 | F | Parallel |
| T7.3 Onboarding ≤3 steps per side, skippable after step 1; empty states one sentence + one action | REQ-UX-03, REQ-UX-04 | F, D (copy `[[COPY-REVIEW]]`) | Parallel |
| T7.4 Performance: SSR, ≤150 KB JS gz per route, LCP ≤2.5 s Slow 4G/Moto G, system font, image-free tracker, Data-saver toggle | REQ-UX-05 | F | After T7.1 |
| T7.5 Accessibility: WCAG 2.2 AA (stepper `<ol>`/`aria-current`, icon+text+colour status, 44 px targets, focus, pasteable OTP, contrast, reduced motion), axe zero serious/critical, Lighthouse ≥90 | REQ-UX-06 | F, U | After T7.1 |
| T7.6 i18n: complete `en.json`/`sw.json` keys (ICU, no concatenation, 30% expansion), UTC store / EAT display, `KES 1,250,000`, E.164 phones | REQ-UX-07 | F | Parallel |
| T7.7 Screenshot sweep at 375 px and 1440 px of every core page, chrome-devtools console/network/perf check, fix list | all | F, U | Last |

Exit checks: AC-UX-1..5; X7-1 `ux-reviewer` PASS on the consolidated portals. Gate: G5 native-speaker review of
`sw.json` is needed only for Swahili going live, not for this exit. Demo: walk both portals on a 360 px emulator with
Slow 4G throttling; Lighthouse and axe reports attached to the phase report.

### Phase 8 — Hardening & launch readiness (Fable audit)

Goal: no BLOCKER/MAJOR findings, staging E2E passes, legal/brand/DNS gates signed, report for G8.
Spec to read: `docs/spec/08` (non-functional, CI/CD, deploy), `10`, `12`, `14`, ADR-002/003/006/007.
REQ-IDs: REQ-SEC-02, REQ-SEC-03, REQ-ADM-01..03, REQ-LEG-01, REQ-OPS-01.

| Task | REQ-IDs | Agent | Order / notes |
|---|---|---|---|
| T8.1 Full security review (Fable `security-reviewer`) of every module + scanners at high/critical; fix BLOCKER/MAJOR | REQ-SEC-03 | S, B | First; may loop |
| T8.2 DSR endpoints: export (JSON + certificate PDFs ≤72 h via SLA job), rectification, erasure with legal-hold exceptions and pseudonymisation; `audit.verify_chain` still passes | REQ-SEC-02 | B, S review | Parallel |
| T8.3 Admin console complete: claims queue SLA, moderation, research approval, invitations, directory editing, plans/prices, refunds, feature flags, audit viewer, dead-letter queue, LLM cost ledger; support impersonation audited + owner notified; harvesting heuristics | REQ-ADM-01 | B, F | Parallel |
| T8.4 Disputes A–F: automatic legal hold, evidence pack (hashed, TSA-stamped, chain proof, s.106B certificate), takedown/counter-notice 48 h SLA, Report button everywhere | REQ-ADM-02, REQ-ADM-03 | B, F, S review | After T8.2 |
| T8.5 Legal placeholders (`DRAFT — NOT LEGAL ADVICE …` headers, `[[LEGAL-PLACEHOLDER:<id>]]`), `docs/legal/LAUNCH_GATE.md`, `lawful_basis.md`, `/subprocessors`, ODPC number slot, DPIA outline; replace with G2 texts when supplied | REQ-LEG-01 | D | Parallel; never legal text by agents |
| T8.6 Ops: Terraform + `docker-compose.prod.yml` + Caddy, `main.yml` (GHCR, staging, manual-approval production), SSM secrets, backups + restore drill, observability (OTel, Sentry, Better Stack, healthchecks.io), load test on digest/reminder workers, runbooks (incident, rollback, breach 72 h, DSR, secret rotation) | REQ-OPS-01 | I, B, D | After G1 values |
| T8.7 Brand (G5) and email DNS (G7) applied; production directory seed per G6; staging deploy; `docs/spec/14` E2E scenarios (a)–(e) on staging | REQ-OPS-01 | F, I, T | Last |
| T8.8 Phase 8 report: cost per phase, known limitations, G8 submission | — | orchestrator | Last |

Exit checks: AC-SEC-3, AC-ADM-1..4, AC-IP-7; re-run AC-SEC-1/b, AC-SEC-2, AC-SEC-4, AC-SEC-5, AC-SEC-6, AC-SEC-7;
X8-1 `docs/spec/14` E2E (a)–(e) pass on staging; X8-2 no open BLOCKER/MAJOR; X8-3 restore drill logged; X8-4 banned-claims
lint passes on the final copy. Gates: G2, G5, G6, G7 signed before exit; G8 after the report. Demo: the staging E2E run,
recorded.

## 4. Phase exit map

Canonical list of acceptance tests asserted at each phase exit. Clause ids (`AC-X/a`, `AC-X/b`) are defined in
`REQUIREMENTS.md` §4; an AC listed at a phase must be built no later than that phase (checked by
`docs/platform/checks/check_traceability.py`). Re-runs of earlier ACs are not listed; CI runs the whole suite every time.

| Phase | Acceptance tests asserted at exit |
|---|---|
| 1 | AC-HYG-01, AC-HYG-02, AC-HYG-03, AC-HYG-04, AC-HYG-05, AC-HYG-06, AC-SEC-1/a, AC-SEC-4, AC-SEC-5, AC-REM-4/a |
| 2 | AC-SEC-1/b, AC-SEC-2, AC-SEC-6, AC-REPO-1, AC-REPO-2, AC-REPO-3, AC-REPO-4/a, AC-REPO-5, AC-REPO-6/a, AC-DIR-1, AC-DIR-2, AC-DIR-3, AC-DIR-4, AC-DIR-5/a, AC-DIR-6, AC-DIR-7, AC-PROP-1/a, AC-PROP-2, AC-PROP-4, AC-PROP-5, AC-PROP-6, AC-PROP-7, AC-IP-1, AC-IP-2, AC-IP-4, AC-IP-5, AC-IP-6, AC-IP-9, AC-SUB-1, AC-SUB-7 |
| 3 | AC-TRACK-1, AC-TRACK-2, AC-TRACK-3, AC-TRACK-4, AC-TRACK-5, AC-TRACK-6, AC-TRACK-7, AC-TRACK-8/a, AC-TRACK-9, AC-TRACK-10, AC-MAIL-1, AC-MAIL-2, AC-MAIL-3, AC-MAIL-5, AC-REM-1, AC-REM-2, AC-REM-3, AC-REM-4/b, AC-PROP-1/b, AC-PROP-3, AC-IP-3/a, AC-IP-8, AC-SEC-7, AC-SUB-5 |
| 4 | AC-SCOUT-1, AC-SCOUT-2, AC-SCOUT-3, AC-SCOUT-4, AC-SCOUT-5, AC-SCOUT-6, AC-SCOUT-7, AC-SCOUT-8, AC-TRACK-8/b, AC-REPO-4/b, AC-DIR-5/b |
| 5 | AC-RES-1, AC-RES-2, AC-RES-3, AC-RES-4, AC-TREND-1, AC-TREND-2, AC-TREND-3, AC-PERS-1, AC-PERS-2, AC-PERS-3, AC-PERS-4, AC-PERS-5, AC-PERS-6, AC-PERS-7, AC-REPO-6/b |
| 6 | AC-SUB-2, AC-SUB-3, AC-SUB-4, AC-SUB-6 |
| 7 | AC-UX-1, AC-UX-2, AC-UX-3, AC-UX-4, AC-UX-5 |
| 8 | AC-SEC-3, AC-ADM-1, AC-ADM-2, AC-ADM-3, AC-ADM-4, AC-IP-7 |

Not in any build phase (Release 2, DEFERRED with an ADR): AC-MAIL-4 (ADR-004), AC-IP-3/b (ADR-003).

## 5. Timing deviations from the spec's exit lists (earlier, never later)

`docs/spec/11-delivery-phases.md` lists some ACs at a later phase than the phase that builds the feature. This plan
asserts them as soon as the feature exists and re-runs them at the spec's phase, which keeps every phase exit
independent of later phases:

| AC | Spec phase | Asserted from | Reason |
|---|---|---|---|
| AC-SEC-4, AC-SEC-5 | 8 | 1 | Scanners and the egress-blocked runner are part of the Phase 1 CI; retrofitting is costlier. |
| AC-SEC-2 | 8 | 2 | `FEATURE_TIER2_ENABLED` and the Tier-2 endpoints exist in Phase 2. |
| AC-SEC-6 | 3 | 2 | The first LLM tasks (moderation, over-disclosure, originality explainer, assistant) ship in Phase 2; the fixture assertion grows with every later task. |
| AC-SUB-1, AC-SUB-7 | 6 | 2 | Entitlement middleware (Phase 1) plus proposals/grants (Phase 2) make them testable; billing rails are not needed. |
| AC-SUB-5 | 6 | 3 | Needs NDA, tracker and messaging (Phase 3), not payment rails. |

## 6. Order of work across phases (dependency summary)

1 (auth, tenancy, audit, email, CI) → 2 (proposals, provenance, directory, LLM layer, embeddings) → 3 (engagements,
notifications, reminders) → 4 (scouts, evals) → 5 (research, trending, ranker) → 6 (billing) → 7 (UX) → 8 (hardening).
Billing (6) is scheduled after the AI phases because Release 1 launches with free and anchor plans plus manual invoicing;
UX consolidation (7) waits until every screen exists; the Fable audit (8) is last so it reviews the final code. Frontend
work is incremental from Phase 1 (`ux-reviewer` from Phase 2) so Phase 7 is consolidation, not construction.

## 7. Budget and cost tracking

Budget (DECISIONS-NEEDED D-01, decided at G0 on 2026-09-24): Max subscription, usage tracked via `/cost`, no USD cap.
After every phase the human pastes `/cost` output into `PROGRESS.md`. Stop and ask if a phase would exhaust the
weekly usage limit. Orchestrator (D-04): Opus 5.5 at `xhigh` for Phases 1–7; Fable 5.1 for the `security-reviewer`
and the Phase 8 audit.
