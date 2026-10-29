# Prototype M2 build plan (P10–P17)

Written 2026-09-29 from a read-only planning pass over `PLAN.md` §8, the Handoff carry-forward notes, REQUIREMENTS.md,
docs/spec/05, 06, 08, 09 and the schema of revisions 0001–0004. It is the working plan for M2; `PLAN.md` §8 stays
the scope and cut order. Decisions it raised: D-43 (scout Tier-2 isolation), D-44 (sample prices), D-45 (research
cards naming organisations), D-39 item 6 (assistant consent wording).

## 1. What exists and what each task adds

| Task | Already there | To build |
|---|---|---|
| P10 Scout (REQ-SCOUT-01..03, REQ-ENG-04) | Stage-0 `accept_interest` (step-up) and `decline_interest` (`engagements/state_machine.py:247-263`, `commands.py:377-396`); EM2 from stage 0; RLS lets a signatory insert `ORG_INTEREST` for an E2 org (0003:307-319); `GrantSource.ORG_INTEREST`; plan limits `scout_agents`, `scout_frequencies`, `scout_digest`; `GET /api/niches`; Browse `GET /api/proposals`; fake embedder by default | `bridge/matching/` (`scouts.py`, `pipeline.py` rules + LLM "why this matches", `digest.py` EM3); `engagements/interest.py` (Express interest, N17 to the developer); developer "Share Tier 2" command (re-check #21); `jobs/scouts.py` (`scouts.scan`, `on_new` from publish); `templates/em3.*`; `scout_fit_rationale` task in `models.yaml`; `config/matching/weights_v1.yaml`; tables `scout_agents`, `agent_runs`, `agent_matches` (0005); demo seed (a scout per E2 fixture, an untagged proposal in each scout's niche, Growth plan for Telco A); org Inbox "Scout matches" tab, configure scout, match page with Express interest |
| P11 Research (REQ-RES-01/02) | `problems` has `research_agent` source, `candidate` status, `ai_generated`, `confidence`; `problem_sources` (url, publisher, type, date, quote); RLS hides candidates except from staff; `app_moderate_problem`; `GET /api/problems`; excerpts on `feat/REQ-RES-01-sources` (`0bb707d`, 19 excerpts, 4 niches); `InputField(public=True)` | merge the excerpts branch; `research_runs` table and `app_create_research_candidate` definer (0005); `bridge/problems/research/` (load excerpts, one synthesis call per niche, code checks: cited ids exist, numbers inside quotes, one official source or two publishers, confidence formula, discard below 0.40, named-organisation rule D-45); `problems/sources/ke.yaml` allowlist; `jobs/research.py`; `research_synthesis` task (no tools); admin research API; problem detail with citations; country/county filters; a demo staff admin (`staff_role`, TOTP, `demo_account=true`); the `/admin` console shell |
| P12 Trending + ranker (REQ-TREND-01/02, REQ-PERS-01) | `signal_events` (insert-only for `bridge_app`, read by `aggregate_worker` only); `proposal_published` and `proposal_version_published` signals; `developer_niches` (RLS, no API); `profiling` consent (default off) | `app_trend_aggregates` definer (0005); `matching/{trending,ranker,discover}.py` computed on read; `config/ranking/weights_v1.yaml`; liked-niches API; `org_interest` and `scout_match` signals (from P10); demo signals, liked niches, profiling consent; `/dev/discover`, Home "Recommended for you", Discover in DevNav |
| P13 Submission assistant (REQ-PROP-05) | `submission_assistant` task (free slots), per-session consent helpers (`llm/guard.py:45-73`), Tier-2 demo-only rule, `DemoFallbackFlag`, the editor | `proposals/assistant.py` + `assistant_router.py`; consent endpoints (text version, audit event); drop `tier2_llm_assistant` from `PUT /api/me/consents`; new consent text version (D-39 item 6); fixed message on the global budget error (T2.2 security MINOR 3); editor panel. No schema change |
| P14 Subscriptions (REQ-BIL-08, REQ-BIL-04 interface) | `plans`, `subscriptions`, `plans.yaml` (placeholder prices, D-44), plan ladder, 402 → `/billing/upgrade?plan=`, free subscription at signup, entitlements routes | `billing/providers/{base,fake}.py` (`PaymentProvider`: initiate, query, verify_callback; `FakePaymentProvider`, refused outside dev/test); `payments` table, `app_settle_payment`, `app_activate_paid_subscription`, `payments_guard` (0005); billing router; `PAYMENT_PROVIDER` setting; `/billing`, `/billing/upgrade` (simulated M-Pesa steps), avatar-menu entry |
| P15 Admin (REQ-ADM-01, REQ-MOD-01, REQ-DIR-03 queue) | staff access dependency; moderation queue routes (`admin/router.py:145-163`); staff read `org_claims` | read-only claims queue API; admin screens on P11's shell; demo staff moderator. Staff do not decide claims in the prototype (no `app_decide_claim` change) |
| P16 Packaging | `make demo` (P9), README "Run the demo" | polish at 375/1440 px, Playwright walkthrough video + screenshots into `docs/demo/`, README Demo section, "real vs simulated vs planned" table |
| P17 Auth follow-ups 7–8 | WIP `feat/REQ-AUTH-01-followups-7-8` `97b9454` (BLOCKER) | fix per the laptop Handoff, security-reviewer + reviewer, then frontend halves |

## 2. Revision 0005 (db-migrations only; one revision)

- Enums: `scout_frequency` (daily, weekly, on_new), `agent_run_status`, `match_feedback` (relevant, not_relevant),
  `research_run_status`, `payment_status` (pending, succeeded, failed, cancelled); payment provider `varchar` with
  `CHECK (provider IN ('fake'))`.
- Tables:
  - `scout_agents` (ORG): niches uuid[] 1–5, counties, include/exclude keywords (≤20 × 60 chars), maturity[],
    budget band, `min_fit` 0–100 default 60, frequency, language, recipients uuid[], `paused_at`, cursor columns,
    `created_by`; SELECT members; INSERT/UPDATE/DELETE owner or admin under `app.org_id`; column-scoped UPDATE.
  - `agent_runs` (ORG): composite FK (scout_id, org_id); trigger, status, counts, cursor window, `error_code` (code,
    no free text); SELECT members; INSERT/UPDATE acting members; no DELETE.
  - `agent_matches` (ORG only): composite FKs to the scout and to `proposal_versions`; UNIQUE (scout_id,
    proposal_id); score, rule breakdown jsonb, rationale ≤600, `rationale_demo_fallback`, `injection_suspected`,
    niche_id, `digest_sent_at`, feedback columns; SELECT members; INSERT acting members; UPDATE feedback and
    `digest_sent_at` only.
  - `research_runs` (STAFF): niche, country/county, status, `started_by`, counts, cost, stop reason,
    `demo_fallback`; `CHECK (searches <= 25 AND fetches <= 40)` (AC-RES-3); staff admin only.
  - `payments` (ORG_OR_USER): exactly one of user_id/org_id; plan_id, `amount_kes_minor` > 0, provider,
    `provider_ref` UNIQUE (platform-generated), status, `initiated_by`, settled time (DB clock), `subscription_id`,
    `failure_code`; no phone column; SELECT the user or org owner/admin/finance; INSERT pending only, active
    non-default plan of the subject's side at its price; no UPDATE grant.
- Columns: `problems.research_run_id` (FK), `problems.named_orgs text[]` (≤10), `problem_sources.excerpt_ref
  varchar(32)`; not updatable by the app.
- SECURITY DEFINER (pinned search_path, EXECUTE only to `bridge_app`): `app_scouts_due(p_now, p_trigger, p_proposal)`
  → (scout_id, org_id, act_as_user_id); `app_create_research_candidate(...)` (staff admin, own running run,
  `created_by NULL`, https URL + date + quote per source, confidence ≥0.40); `app_settle_payment(payment, status,
  failure_code)` (subject only, pending → final once); `app_activate_paid_subscription(payment)` (succeeded,
  unlinked, matching side and amount; cancels the live subscription, inserts the new one from `app_clock_now()`,
  idempotent); `app_trend_aggregates(p_since, p_now)` (per item and kind: once per actor/item/day, distinct actors,
  distinct orgs only when ≥3; never hashes or org ids; OWNER `aggregate_worker` if the migration role can, else
  `bridge_owner`; security-reviewer rules on it).
- Triggers: `payments_guard` (no DELETE; subject, plan, amount, ref immutable; status once; subscription once);
  `problems` backstop: a `research_agent` row cannot reach `published` without one official source or two distinct
  publishers (AC-RES-1).
- Not in 0005: `webhook_events`, stored recommendations/trend scores, the `proposal_versions` policy tightening
  (P10/P12 read `current_version_id` only), `users.totp_pending_since` (P17 decides; 0006 if needed), claim-decision
  fixes.
- Tests: generated RLS tests from model `info`, privileges, up/down/up + `alembic check`, enum freeze, each definer
  (search_path, EXECUTE, refusals), mutation proofs.

## 3. Routes and screens

- P10: `GET|POST /api/orgs/{org_id}/scouts` (402 over the plan), `GET|PATCH|DELETE …/scouts/{id}` (PATCH pauses),
  `POST …/scouts/preview` (30 days, rules only, no LLM, no writes), `GET /api/orgs/{org_id}/matches[/{id}]`,
  `POST …/matches/{id}/feedback` (optional), `POST /api/orgs/{org_id}/interest` (signatory, E2, step-up; reviewer
  403), `POST /api/engagements/{id}/share-tier2` (developer, step-up); `make demo-scouts`. Screens: Inbox "Scout
  matches" tab, configure scout (Preview, Pause), match page with Express interest; developer "Share Tier 2".
- P11: `GET /api/admin/research/sources`, `POST|GET /api/admin/research/runs[/{id}]`, `GET
  /api/admin/research/candidates`, `POST …/candidates/{problem_id}/decision`, `GET /api/problems/{id}`, `GET
  /api/problems?country=&county=`. Screens: `/admin` shell, `/admin/research`, the problem card with sources.
- P12: `GET /api/discover/trending`, `GET /api/discover/opportunity-gap`, `GET /api/me/recommendations`, `GET|PUT
  /api/me/niches`. Screens: `/dev/discover`, Home "Recommended for you", liked-niches picker.
- P13: `POST|DELETE /api/me/proposals/{id}/assistant/consent`, `POST /api/me/proposals/{id}/assistant/suggestions`.
  Screen: editor panel with consent dialog and labels.
- P14: `GET /api/plans?side=`, `POST /api/billing/checkouts`, `GET /api/billing/checkouts/{id}` (query, settle,
  activate; idempotent). Screens: `/billing`, `/billing/upgrade?plan=`, avatar-menu entry.
- P15: `GET /api/admin/claims[/{id}]` (read-only). Screens: `/admin/moderation`, `/admin/claims`.
- M2 walkthrough: (1) P10 scout → EM3 → Express interest → developer accepts with step-up → EM2 → Share Tier 2 → org
  views it; (2) P14 402 → fake M-Pesa upgrade → publish; (3) P11 research run → approve a cited card; (4) P12 Discover
  and Home show it with chips; (5) P13 teaser suggestion; (6) P15 moderation queue. Steps 2–6 drop in cut order.

## 4. Order (at most 3 implementers; reviewers do not count)

| Stage | Slot 1 | Slot 2 | Slot 3 |
|---|---|---|---|
| 0 | P8 part 5 | P9 fix round | 0005 (db-migrations) |
| Gate | M1 exit (`prototype-m1`); then 0005 merges | | |
| 1 | P10-B | P14-B | P11-B (merge the excerpts branch first) |
| 2 | P10-F | P14-F | P17-B |
| 3 | P11-F | P12-B | P17-F |
| 4 | P12-F | P13-B | P15-B |
| 5 | P13-F (after P12-F; both edit the editor) | P15-F | P16 README (docs-writer) |
| 6 | P16 polish | P16 walkthrough | — |

A queue: a slot refills as its task merges. Hot spots: `main.py` routers (one line each), `openapi.json` and
`schema.d.ts` (regenerate after merging, never hand-merge), `config.py` / `.env.example` / demo `x-demo-env`,
`models.yaml`, `jobs/app.py` `IMPORT_PATHS`, `proposals/service.py` publish path (P10 first), `admin/router.py`
(sub-routers), `bridge/seed/demo/*` (one module per task), Makefile, locales (namespaced keys), `DevNav.tsx` and
`TopBar.tsx`, editor files and `refusals.ts` (one task at a time), `org/inbox/page.tsx`, `app/(admin)` layout,
`dev/page.tsx`, `tests/integration/world.py`.

## 5. Reviews

Every task: `reviewer`, `pr.yml` and `codeql.yml` dispatch (D-42). security-reviewer: 0005, P10-B, P14-B, P17-B,
P13-B (Tier-2 text to an LLM under per-session consent), P12-B only if it writes a Tier-2 view signal, P15 only if
claims can be decided. ux-reviewer: every frontend part and P16.

## 6. Demo budget and zero spend

- Memory: P9 limits total about 2.3 GB running; add no containers or heavy dependencies (no sentence-transformers,
  numpy, lightgbm or LangGraph); trends and ranker computed on read in plain Python; scout, research and reminder jobs
  share the worker; measure the web build after P12 and P16.
- No bge-m3: with the fake embedder, scores use keyword and niche overlap (README lists it as simulated).
- No real payment: `FakePaymentProvider` only, refused outside dev/test; no Daraja or Paystack code; no phone numbers.
- No runtime fetching: research has no tools and uses the saved excerpts.
- LLM: fake by default; free slots under their caps; Anthropic only with `LLM_PROVIDER=anthropic` (USD 1/day, USD 5
  total). Bounded calls (scout top N cached per scout and version; one research call per niche; one assistant call
  per click). Staff admin and fixture seats need `demo_account=true`. Every new output schema has `demo_fallback()`
  with `injection_suspected=True`, treated as "no answer" (scout: a code-written "Matched on …" line with the label;
  assistant: no suggestion; research: no card).
- Deviations to record: LangGraph (spec 08) is not used in the prototype; the unlock quota (REQ-BIL-03) is
  rescheduled, but P10 sets `counts_as_unlock` and `billing_month` on grants for untagged proposals.
