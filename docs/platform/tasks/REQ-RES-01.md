# REQ-RES-01 (with REQ-RES-02, prototype part)

- Task: P11 Research agent, backend (`docs/platform/PLAN.md` §8, prototype track M2, 4th to cut;
  `docs/platform/prototype-m2-plan.md` §1-§3). The admin screens and the problem card are a later P11-F task.
- Agent: impl-backend. Reviews: reviewer (checks that `public=True` is used only for saved public excerpts, P7 MINOR,
  Handoff re-check #37).
- Branch `feat/REQ-RES-02-research` from integration head `f609830` (revision 0005 merged), with
  `feat/REQ-RES-01-sources` (`0bb707d`: `backend/seed/research_excerpts.yaml`, 19 verbatim dated excerpts in 4
  niches, and `research/research-excerpts-2026-09.md`) merged `--no-ff` first (`27f309d`).
- Depends on: revision 0005 (`research_runs`, `research_runs_guard`, `app_create_research_candidate`, the AC-RES-1
  backstop `problems_research_guard`; REQ-SCOUT-01 card), revision 0002 (`app_moderate_problem`), P7 (LLM providers,
  `InputField(public=True)`, `demo_fallback()`), P9 (demo seed). No schema change, no new environment variable.
- Decisions applied: D-36 (zero spend), D-37 (free providers, demo data only), D-38 default (a) (excerpts local only),
  D-45 default (a) (a card naming an organisation needs an official source; the approval shows a checklist
  placeholder and the names).

## Files

| Area | Files |
|---|---|
| Research package | `backend/src/bridge/problems/research/{__init__,policy,sources,text,checks,synthesis,pipeline,review,tasks,runtime}.py` |
| Allowlist | `backend/src/bridge/problems/sources/ke.yaml`; test fixture `backend/tests/fixtures/sources/ug.yaml` (second country, AC-RES-4) |
| Numbers | `backend/config/policy.yaml` section `research`; `backend/ai/models.yaml` task `research_synthesis` |
| Job | `backend/src/bridge/jobs/research.py` (`research.run`), `IMPORT_PATHS` in `jobs/app.py` |
| Admin API | `backend/src/bridge/admin/research.py` (own router, registered in `main.py`) |
| Public API | `backend/src/bridge/problems/{router,service}.py`, `ProblemRef.label` description in `proposals/schemas.py` |
| Demo seed | `backend/src/bridge/seed/demo/research.py`, `DemoStaff`/`STAFF_ADMIN` in `seed/demo/data.py`, two steps in `seed/demo/__init__.py` |
| Generated | `backend/openapi.json`, `frontend/lib/api/schema.d.ts` |
| Tests | `backend/tests/unit/problems/research/`, `backend/tests/unit/demo/test_demo_research.py`, `backend/tests/integration/problems/{research_rig,conftest,test_research_pipeline,test_research_job,test_filters}.py`, `backend/tests/integration/admin/test_research_api.py`, `backend/tests/integration/demo/test_demo_seed.py` (one test), `backend/tests/evals/research/test_research_eval.py`, cassette `backend/tests/fixtures/cassettes/research_synthesis_eval.json` |

## What it does

**Saved excerpts and the allowlist** (`sources.py`). The research agent never searches or fetches at runtime: it
reads `backend/seed/research_excerpts.yaml` against the country's allowlist `problems/sources/<cc>.yaml`, and refuses
the whole file on the first bad excerpt. The KE allowlist is the researcher's list: `kilimo.go.ke`, `www.sasra.go.ke`,
`www.ca.go.ke` (official), `businessdailyafrica.com`, `capitalfm.co.ke`, `capitalfm.africa`, `standardmedia.co.ke`,
`the-star.co.ke`. A host matches a domain or a subdomain of it. Each domain names its publisher, which is the
independence key (Capital FM's two domains are one publisher), and an excerpt's publisher must be its domain's.
Official means an allowlisted government host (`.go.<cc>`); an excerpt's `source_type` is `official` exactly when its
domain is, so an excerpt never makes itself official. URLs are https on a plain ASCII host (no user info, port,
whitespace or control character: the definer's rule), dates real and retrieved on or after publication, quotes
whitespace-collapsed (never folded: curly apostrophes and en dashes stay), at most 60 words, no control character.
Freshness per docs/spec/06 6.5 (`policy.yaml`: stale at 12 months, archived at 18) on the shared clock's Nairobi date:
an archived excerpt is never sent and never counts. On 2026-09-29 the fixtures ke-tel-005 (2023) and ke-agr-004
(2025-02) are archived; a run gets 3 to 5 excerpts per niche (telecoms 4, agriculture 3, health 5, SACCOs 5).

**One call per niche** (`synthesis.py`). Task `research_synthesis` (docs/spec/09's card synthesis model: Sonnet 5 at
medium effort; free slots 1-3; Tier 1 only; no tools). The model gets the niche slug and, per excerpt, its id,
publisher, source type, date and quote, nothing else (no tenant, user or run data). Each is an
`InputField(public=True)`; `excerpt_fields` is the only code that marks a field public and takes saved `Excerpt`
objects of one niche only (an AST scan fails the build on any other). The answer, `ResearchSynthesis`, lists drafts
with title, statement, affected group, `named_orgs` and citations (excerpt id plus verbatim supporting text); its
`demo_fallback()` has no drafts and flags `injection_suspected`.

**Checks in code** (`checks.py`), in order: (1) whitespace collapsed (the revision 0005 operating rule), then no
control character left, title 1-90 characters, statement 1-120 words and at most 1500 characters, affected group at
most 200, at most 10 named organisations; (2) at least one citation, every cited id one the run sent (else the whole
draft is discarded), a citation counting only when its supporting text (at least 4 words) is verbatim in the quote;
(3) every number in title, statement and affected group inside a cited quote, with its scale (billion, million,
trillion, percent) when it has one; digits and the number words two to ninety; (4) D-45: the allowlist's
organisations found in the text (whole words, case-sensitive, plus every publisher) and the model's `named_orgs`
need an official cited source; (5) AC-RES-1: one official source or two independent publishers; (6) the confidence
`0.35 source_quality + 0.25 corroboration + 0.20 freshness + 0.20 extraction_agreement` (weights and tiers from
`policy.yaml`: official 1.0, filing 0.9, news/ngo 0.8, blog 0.4, social 0.3; corroboration = distinct publishers / 3,
at most 1; freshness = mean freshness score; extraction agreement = verified citations / cited excerpts), rounded
down to 3 decimals; below 0.40 discarded.

**A run** (`pipeline.py`, job `research.run`). `POST /api/admin/research/runs` inserts a running `research_runs` row
as the staff admin (national: county runs are Release 2) and queues the job in the same transaction; a second running
run of the niche is 409. The job binds the run's starter and runs only that admin's running run (idempotent;
anyone else: nothing), then: the excerpts; the caps before any call (searches and fetches stay 0, under the CHECK's
25 and 40, AC-RES-3; the input token estimate against `max_input_tokens`, 400k); one call through the routed
`LLMClient` (`CallContext(user_id=starter)`, `llm_calls` row, caps, D-37 rule: a non-demo admin's call gets the
fallback); the checks; candidates through `app_create_research_candidate` in savepoints, sources exactly as saved
with `excerpt_ref`. A demo fallback completes the run flagged `demo_fallback` with no card; `injection_suspected`
stops it (`injection_suspected`); a typed LLM error fails it with the error code; drafts over 3 are discarded. The
run records candidates, discarded, input tokens and cost.

**Admin API** (`admin/research.py`, `/api/admin/research`; staff admin, TOTP enrolled, second factor within 12 h;
404 for everyone else, 403 for moderators, 403 `step_up_required` when stale): `GET /sources` (excerpts with
freshness, allowlist), `POST /runs` (202), `GET /runs[/{run_id}]`, `GET /candidates` (sources, `named_orgs`,
`checklist` = the D-45 placeholder `[[COPY-REVIEW]]` when it names organisations, `seeded_example`),
`POST /candidates/{problem_id}/decision` `{decision, checklist_confirmed}`. Approval re-runs the publish checks in
code (`review.publish_violation`: every stored source is the saved excerpt exactly, URL on the allowlist, verbatim
quote; one source not archived; numbers, named organisations, source rule on the live sources; confidence at least
0.40), needs `checklist_confirmed` for a card naming organisations, then `app_moderate_problem(id, clear,
published)`, whose AC-RES-1 backstop maps to 409 `publish_check_failed`; rejection is `app_moderate_problem(id,
rejected, rejected)`. Serialised per card (advisory lock), 409 `already_decided`, audited `research.candidate_decided`.

**Public API** (REQ-RES-02 prototype part). `GET /api/problems/{problem_id}`: a published, clear card with its
citations (URL, publisher, type, dates, quote), region, `named_orgs`, confidence and label: "AI-drafted,
human-reviewed on <date>" `[[COPY-REVIEW]]` (the Nairobi day `app_moderate_problem` published it); a candidate is
404 for everyone, staff included (AC-RES-2). `GET /api/problems?country=&county=` filters exactly (AC-RES-4; a second
country, UG, is exercised with the `ug.yaml` fixture allowlist). The list's `label` carries the same research label.

**Demo seed** (`seed/demo/research.py`). A demo staff admin `admin@staff.example` ("Staff Admin (demo)"; listed with
the demo logins, demo password and TOTP helper): created as the app creates a user with the reminders consent, then
`staff_role` admin set by the owner role (no application path sets it), `demo_account` by `owner_facts`, and TOTP by
the seed's normal enrolment step (`accounts.enrol_totp`, which P17 switches to `service.seal_pending_secret`; this
module never writes a secret). Then one card per saved-excerpt niche through the real path: `start_run`,
`execute_run(origin=SEEDED_EXAMPLE)` with `SeededExampleClient`, a fixed answer written by hand in the module from the
saved excerpts (no model is called, no `llm_calls` row), every check in code, and approval by the staff admin signed
in to the in-process admin API. **How a seeded card is labelled:** its sources carry `excerpt_ref` `example:<id>`
(only the seeded path writes that prefix, and it refuses outside dev and test), so the problem API labels it "Seeded
example for the demo (not a live AI result), human-reviewed on <date>" `[[COPY-REVIEW]]` with `seeded_example: true`
(also in the admin candidates list); it is never labelled "AI-drafted". The seeded answers name no organisation.
P9's rules for a used database hold: a niche with a seeded card of any status gets nothing new, a seeded card still
awaiting review is approved, and a later run signs nobody in.

## Acceptance criteria and tests

| AC / rule | Tests |
|---|---|
| AC-RES-1 (one official source or two independent publishers; quotes verified verbatim in code) | `unit/problems/research/test_checks.py::test_ac_res_1_one_publisher_twice_is_not_enough`, `::test_supporting_text_is_compared_unicode_exact_after_collapsing`; `integration/admin/test_research_api.py::test_ac_res_1_approving_publishes_a_cited_card_through_app_moderate_problem`, `::test_a_tampered_source_fails_the_publish_checks`, `::test_one_publisher_fails_in_code_and_the_backstop_holds_without_the_code` |
| AC-RES-2 (a candidate is on no public endpoint) | `integration/problems/test_filters.py::test_ac_res_2_a_candidate_is_on_no_public_endpoint`; `integration/admin/test_research_api.py::test_ac_res_1_…` (list and detail, reader and staff) |
| AC-RES-3 (caps; stopped and logged with cost) | `integration/problems/test_research_pipeline.py::test_ac_res_3_a_run_over_the_search_or_fetch_cap_is_stopped`, `::test_too_few_excerpts_or_too_many_tokens_stop_the_run_before_any_call`; run rows record searches 0, fetches 0, tokens and cost; the CHECK itself is 0005's (`test_research_schema.py`) |
| AC-RES-4 (niche, country, county filters with a second country) | `integration/problems/test_filters.py::test_ac_res_4_cards_filter_by_niche_country_and_county`; `unit/problems/research/test_sources.py::test_a_second_country_allowlist_loads_from_its_own_file` |
| Allowlist refuses an excerpt URL off the list | `unit/problems/research/test_sources.py::test_a_url_is_allowed_only_on_an_allowlisted_https_host`, `::test_a_bad_excerpt_refuses_the_whole_file` |
| Cited ids exist; numbers inside quotes; D-45; confidence and 0.40; whitespace | `unit/problems/research/test_checks.py` (18 tests, 44 cases) |
| Injection in excerpts | `integration/problems/test_research_pipeline.py::test_an_injected_excerpt_stays_data_and_a_complying_answer_makes_no_card`, `::test_a_suspected_injection_stops_the_run_without_a_card`; eval |
| `public=True` only for saved excerpts | `unit/problems/research/test_synthesis.py::test_no_other_code_marks_a_field_public`, `::test_only_saved_excerpts_become_public_fields` |
| Staff only with TOTP and step-up | `integration/admin/test_research_api.py::test_every_route_is_staff_admin_only_with_a_fresh_second_factor`, `::test_a_stale_second_factor_is_refused_after_12_hours` |
| Approve and reject through `app_moderate_problem` | `integration/admin/test_research_api.py::test_ac_res_1_…`, `::test_rejecting_keeps_the_card_private`, `::test_d45_a_card_naming_an_organisation_needs_the_checklist` |
| A demo fallback creates no card | `integration/problems/test_research_pipeline.py::test_a_demo_fallback_creates_no_card`, `::test_a_non_demo_staff_admin_gets_the_fallback_on_a_free_provider` |
| The job | `integration/problems/test_research_job.py` (3) |
| The seed | `integration/demo/test_demo_seed.py::test_the_staff_admin_approved_one_seeded_research_card_per_niche` plus the module's idempotency, demo-flag, TOTP and used-demo tests (which now cover the staff admin); `unit/demo/test_demo_research.py` |
| Eval (cassette) | `evals/research/test_research_eval.py`: 4 niches, 8 drafts; kept 4, precision 1.0, citation validity 100%, unsupported numbers 0, injected cards 0 (synthetic labels until G-EVAL) |

REQUIREMENTS.md names `integration/problems/test_research_pipeline.py::test_publish_gate`, `test_public_endpoints.py`
and `test_research_caps.py` for AC-RES-1..3; the tests above cover them under the names shown (the orchestrator may
update the register's paths).

## Mutation proofs (each applied alone, the named tests run, the file restored with `git checkout`; 23 of 23 killed)

| # | Mutation | Killed by |
|---|---|---|
| M1 | an unknown cited id is not discarded | `test_checks.py`, `test_research_pipeline.py` |
| M2 | supporting text need not be verbatim | `test_checks.py`, the eval |
| M3 | numbers never checked | `test_checks.py`, `test_research_pipeline.py`, the eval |
| M4 | a number's scale ignored | `test_checks.py` |
| M5 | a named organisation allowed without an official source | `test_checks.py`, `test_research_pipeline.py`, the eval |
| M6 | organisations detected only when the model declares them | `test_checks.py`, `test_research_pipeline.py` |
| M7 | one publisher is enough | `test_checks.py`, `test_research_api.py` |
| M8 | a card below 0.40 kept | `test_checks.py` |
| M9 | the freshness term ignored | `test_checks.py` |
| M10 | whitespace not collapsed | `test_checks.py`, `test_sources.py` |
| M11 | archived excerpts sent | `test_sources.py`, `test_research_pipeline.py` |
| M12 | a host off the allowlist accepted | `test_sources.py` |
| M13 | an excerpt makes itself official | `test_sources.py` |
| M14 | a demo fallback treated as an answer | `test_research_pipeline.py` |
| M15 | `injection_suspected` ignored | `test_research_pipeline.py` |
| M16 | the publish checks skipped at approval | `test_research_api.py` |
| M17 | the D-45 checklist not required | `test_research_api.py` |
| M18 | a candidate on the public detail | `test_research_api.py`, `test_filters.py` |
| M19 | the country filter ignored | `test_filters.py` |
| M20 | a non-excerpt public field accepted | `test_synthesis.py` |
| M21 | a seeded card labelled "AI-drafted" | `test_filters.py` |
| M22 | any staff admin executes a run | `test_research_pipeline.py` |
| M23 | a tampered quote accepted at approval | `test_research_api.py` |

## Deviations and notes

- No search or fetch at runtime (PLAN §8 P11): the spec's planner, web tools, Haiku extraction batch, dedupe and
  clustering (bge-m3) are after the prototype; `research_runs.searches`/`fetches` stay 0. The extraction-agreement
  term of the confidence is the verified share of the model's citations (there is no second extraction pass).
- The call's `CallContext` carries the staff admin (so the ledger, the caps and the D-37 rule apply to that account);
  the prompt carries no tenant or user data.
- Seeded cards are identified by the `example:` prefix of `excerpt_ref` (the only research column the public API can
  read under RLS; `research_runs` is staff admin only). No schema change was needed.
- The admin research router is its own `APIRouter` (`/api/admin/research`), registered in `main.py`, not included in
  `admin/router.py`, so P15's sub-routers do not collide.
- The demo staff admin raises the demo login count from 11 to 12 (`unit/demo/test_demo_policy.py`).

## Open questions and follow-ups

1. **Poisoned saved excerpt (THREAT_MODEL §6, Medium).** A quote that carries its own figures lets a card citing it
   and a second publisher pass the code checks; the admin's review of quotes and URLs is the last gate. Excerpts are
   reviewed at build time (D-38); a heuristic screen at load (markup, "ignore previous instructions") was not added.
2. **Seeded cards age out.** The fixed answers cite excerpts from 2026; from 2027-07-16 (ke-tel-004 turns 18 months) some become archived and the
   seed step will fail its checks on a new database (it is guarded, so a used demo still starts). Refresh the excerpts
   (researcher) or the answers then.
3. **Number words.** "one", "hundred", "dozen", fractions and ordinals are not treated as numbers; a model writing a
   figure in words above ninety is not checked (fails open for those words only; digits are always checked).
4. **Organisation detection** is case-sensitive over the allowlist's names and publishers plus the model's own list;
   an organisation outside the list written by the model without declaring it passes the D-45 rule (the approval
   screen shows the text; widen `organisations:` in `ke.yaml` as excerpts grow).
5. **D-38 / D-45** remain open with their defaults; the checklist text is a placeholder `[[COPY-REVIEW]]`.
6. **Register paths**: REQUIREMENTS.md's AC-RES test paths differ from the files above (see the table).
7. **P17 conflict to watch:** `seed/demo/accounts.enrol_totp` is reused unchanged; when P17 merges (it rewrites
   `enrol_totp` to call `service.seal_pending_secret`), the staff admin follows automatically.
