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
run of the niche is 409 unless the first is older than `stale_run_minutes` (60: its job was lost, or its starter
lost the admin role, so it can never finish; see the REQ-SCOUT-01 follow-up on `research_runs_guard`). The job binds the run's starter and runs only that admin's running run (idempotent;
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

## Mutation proofs (each applied alone, the named tests run, the file restored with `git checkout`; 25 of 25 killed)

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
| M24 | a stale running run still blocks its niche | `test_research_pipeline.py` |
| M25 | a fresh running run no longer blocks its niche | `test_research_pipeline.py` |

## Fix round 1 (reviewer CHANGES_REQUIRED at `30c249a`: two MAJORs, six MINORs)

- **MAJOR 1, number scales** (`fbb07c7`). Any unknown scale used to be read as a bare number, so "Sh89m" passed on a
  quote saying "89 percent". Now letters glued to a number are its scale (m, mn, b, bn, k, tn, pc and % normalised;
  an unknown suffix such as "4G" is kept as `suffix:g` and matches only itself: fail closed); after a space the scale
  words percent, per cent, percentage points, thousand, million, billion, trillion and their abbreviations count;
  every (number, scale) of a card must appear in a cited quote, a bare number needing a bare one. Tests: the
  reviewer's Sh89m, Sh89B, Sh89 thousand, 89k and Sh11m, plus 89 mn, percentage points, an unknown suffix, a bare
  number against a scaled one, positives ("Sh15m" against ke-tel-003's "Sh15 million", "Sh11bn", "89%", "91pc"), and
  the publish gate.
- **MAJOR 2, hidden names and format characters** (`d13f77d`, `d803a84`). `collapse` normalises NFKC before
  collapsing whitespace; `has_control` refuses C0/C1 controls and every format character (Cf: soft hyphen,
  zero-width space and joiner, bidi overrides and isolates such as U+202E, BOM), refused, never repaired. NFKC maps
  no code point into those sets (a test over every code point), so `has_control` checks the text as given. Aliases
  match case-insensitively on the NFKC text with format characters ignored, a hyphen matching any dash (U+2010-U+2015,
  U+2212), a space or nothing. Tests: `M‑Pesa` (U+2011), em dash, minus, "M Pesa", "MPESA", lower-case `safaricom`,
  full-width letters, `Safari​com` (ZWSP), soft hyphen, ZWJ, and bidi and format characters in every field, at the
  draft checks and at the publish gate (the definer stores Cf characters, it refuses only C0 and DEL). The saved
  excerpts are NFKC-stable (tested). The bare "Treasury" alias is dropped (a common lower-case word).
- **(a)** `17c9c52`: with the shared test clock 366 days ahead (its limit), a card citing only ke-tel-002 and
  ke-tel-004 is refused at approval with 409 `publish_check_failed` (`sources_archived`) and approved on today's
  clock; kills the archived-filter mutant (Mm1).
- **(b)** `e933a86`: `InputField.public` is keyword-only; the AST guard also flags `InputField(**…)` and
  `replace(**…)`. Every caller already passed it by keyword. (This touches `bridge/llm/types.py`.)
- **(c)** `ef69558`: `start_run` takes `pg_advisory_xact_lock('research-run:<niche id>:<country>')` before counting,
  so two admins starting a niche at once get one run and a 409 (tested with two concurrent sessions);
  `execute_run` stops a run older than `stale_run_minutes` (`stop_reason = 'stale'`) without calling the model.
- **(d)** `7611847`: `GET /api/problems/{id}` returns `ai_generated = row.ai_generated and not seeded_example`.
- **(e)** `fbb07c7`: named organisations are part of the numbers check.
- **(f)** `7611847`: the synthesis docstring names `test_synthesis.py`.

Fix-round mutations (each applied alone by a private script that restores the original bytes; all killed):

| # | Mutation | Killed by |
|---|---|---|
| MA1 | glued letters not read as a scale | `test_checks.py` |
| MA2 | `m` not million | `test_checks.py` (the Sh15m positive) |
| MA3 | a bare number matches any scale (the old rule) | `test_checks.py` |
| MA4 | an unknown glued suffix read as bare | `test_checks.py` (4G) |
| MA5 | `k` mapped to percent | `test_checks.py` |
| MB1 | no NFKC in `collapse` | `test_checks.py` |
| MB2 | format characters allowed | `test_checks.py`, `test_research_api.py` |
| MB3 | aliases case-sensitive | `test_checks.py`, `test_research_api.py` |
| MB4 | a hyphen matches only `-` | `test_checks.py`, `test_research_api.py` |
| MB5 | format characters not ignored in detection | `test_checks.py` |
| Mm1 | archived sources count at approval | `test_research_api.py` |
| Mm2 | no niche lock at start | `test_research_pipeline.py` |
| Mm3 | a stale run still runs | `test_research_pipeline.py` |
| Mm4 | a seeded card reported `ai_generated` | `test_demo_seed.py` |
| Mm5 | named organisations outside the numbers check | `test_checks.py` |
| Mm6 | `public` positional again | `test_synthesis.py` |

With M1-M25 re-run on the fixed code: 41 of 41 killed. One mutant, NFKC inside `has_control`, was equivalent
(proved over every code point) and the NFKC call there was removed.

## Fix round 2 (re-review CHANGES_REQUIRED at `8f175b5`: one MAJOR, two MINORs)

- **MAJOR, the word after a number** (`75b80b4`, `e59b3c2`). An unrecognised scale after a hyphen, a space or a
  bracket was still a bare number: "Farmers lost Sh90-million." passed on ke-agr-002's "90-kilogramme", and so did
  "Sh90 millions", "Sh90 mln", "Sh90 (million)", "Sh2,000 crore", "50 per-cent" and "Sh50 billions". Now the word
  after a number decides its scale whatever joins it: glued letters, a dash-joined word ("90-kilogramme" is suffix
  `kilogramme`, "Sh90-million" 90 million, "four-year" suffix `year`), a bracketed word, or the next word after a
  space (a dash with a space on either side reads as a space). Known scales are normalised (plurals, `mln`, `bln`,
  `mio`, `pct`, `pp`, `bps`, "per cent" with any dash); **any other word becomes the number's suffix** and needs the
  same word after the same number in a quote. **Why a suffix rather than refusing:** the code cannot tell a magnitude
  ("crore", a typo, a unit) from a noun, so it asks the quote to carry the same word, which fails closed on every
  unknown magnitude while a figure copied with its quote's words ("Level 4 public", "90-kilogramme bags") still passes;
  refusing every figure followed by a word would discard nearly every card. The one exception is function words
  (a closed class that can never be a magnitude: "to", "per", "by", "and", ...), which leave the number bare, as in
  "Sh0.41 to Sh0.3 per minute by March 2029". The prompt now asks the model to copy the word that follows each figure.
  The seeded answers and the eval pass unchanged. Tests: every scenario above, "Sh90 [bn]", a spaced em dash,
  "Sh2,000crore", "Sh50 billions", positives ("25 millions of bags", "Sh11 billions", "for a 50 kilogram bag"), a
  unit that differs ("90 bags" against "90-kilogramme" fails), and the publish gate ("Sh90-million" gets 409).
- **MINOR 1, invisible and look-alike characters** (`6c6d7ad`, `e59b3c2`). `has_control` also refuses every
  Default_Ignorable_Code_Point (U+034F, U+FE00-FE0F, U+115F, U+1160, U+3164, tag characters, ...) and U+2800, in
  every card field and in the saved excerpts' quotes, and the D-45 detection ignores them. Look-alikes: a card's
  title, statement and affected group may hold only Latin letters, ASCII digits (after NFKC) and no combining marks
  (`non_latin_text`); chosen over a confusables skeleton as the simpler rule that cannot miss a script, since cards
  are English or Swahili. Tests: each character above, U+0430, U+0441, U+0405, Greek alpha, Arabic-Indic digits,
  Latin accents passing, the excerpt loader, and the publish gate.
- **MINOR 2, "Treasury"** (`f8f6394`). An alias may be `{text: Treasury, case_sensitive: true}`: matched only as
  written or in capitals. "the Treasury said" needs an official source; "treasury bills" does not.

Fix-round-2 mutations (all killed; the whole list re-run on `e59b3c2`: **55 of 55 killed**):

| # | Mutation | Killed by |
|---|---|---|
| MC1 | a dash-joined word ignored | `test_checks.py` |
| MC2 | a bracketed word ignored | `test_checks.py` |
| MC3 | an unknown dash-joined or bracketed word read as bare | `test_checks.py` |
| MC4 | any word after a space read as bare (the old rule) | `test_checks.py` |
| MC5 | function words taken as suffixes too | `test_checks.py`, the eval |
| MC6-MC8 | `millions`, `mln`, `billions` unknown | `test_checks.py` |
| MA4 | an unknown glued suffix read as bare (updated) | `test_checks.py` (`Sh2,000crore`) |
| MB2 | Cf characters that are not default-ignorable allowed | `test_checks.py` (U+0600, U+FFF9) |
| MB6 | default-ignorable characters allowed | `test_checks.py`, `test_sources.py`, `test_research_api.py` |
| MB7-MB9 | the Latin-only rule off, or letters or marks and digits unchecked | `test_checks.py` |
| MD1 | the case-sensitive flag ignored | `test_checks.py` |
| MD2 | a case-sensitive alias matched in any case | `test_checks.py` |

## Commit sizes

CLAUDE.md asks for commits of about 300 changed lines. Over it: `f1e7fd6` (+856: loader, policy and their tests),
`9b9f511` (+544, checks and tests), `838bc08` (+1129: pipeline, job, test rig and tests), `caf7230` (+903: review,
admin API and its tests), `a62d96a` (+330), `eda1086` (+421: seed module and tests), and `816a339` (+2924/-289,
generated `openapi.json` and `schema.d.ts` only). Each is one concern with its tests; the generated files are
regenerated, never hand-edited. The fix-round commits are 12-150 lines (round 2: 8 to 243 lines; `75b80b4` is the largest, mostly tests). `9b9f511` and `eda1086` went in with a lint
and a mypy error, fixed in `047b5e5` and `1de8ff5`.

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

## Round-3 review MINORs (2026-09-30; reviewer PASS on db03f39) — follow-ups

1. **Latin-script look-alikes** (`problems/research/text.py:63`): IPA alpha U+0251, small capital U+1D00 and script g
   U+0261 are Latin script and pass, so "Sɑfaricom" hides an allowlisted name. Fix: allow letters in U+0041–U+024F
   only (refuses IPA Extensions, Phonetic Extensions, Latin Extended-C/D/E).
2. **False refusals** (`text.py:63`): Swahili "ngʼombe" with U+02BC and "5µg" (NFKC → Greek mu) get `non_latin_text`
   (fail closed). Fix: allow U+02BC and U+02BB (or map them to U+2019), U+00B5 and U+03BC.
3. **Test gap** (`text.py:65`): removing the combining-mark refusal leaves the suite green. Add a test that a stray
   combining mark ("Safa̶ricom") gets `non_latin_text`.
4. **Slash and comma before a scale** (`checks.py:310`): "Sh2,000/mn", "Sh2,000/million" and "Sh2,000, million" read as
   bare numbers. Fix: treat `/` like a dash in `_DASHED`, or record it with the other residuals.

## P11-F: research screens and the problem card (frontend)

Branch `feat/REQ-RES-01-fe` from integration `84e0af0`; frontend only, against the frozen `backend/openapi.json`.

| Area | Files |
|---|---|
| Staff console shell | `frontend/app/(admin)/{error.tsx, admin/layout.tsx, admin/staff.ts, admin/AdminShell.tsx, admin/page.tsx}`, `frontend/components/{AdminNav.tsx, AdminNav.test.tsx, admin-icons.tsx}` |
| Research | `frontend/app/(admin)/admin/research/{page.tsx, Sections.tsx, StartRun.tsx, Decision.tsx, StepUp.tsx, PageStepUp.tsx, data.ts, calls.ts, research.ts, research.test.ts, research-screens.test.tsx}`, `…/research/candidates/[id]/page.tsx` |
| Problem card | `frontend/components/problem/{ProblemCard.tsx, Citations.tsx, data.ts, problem.ts, problem.test.ts}`, `frontend/app/(app)/problems/[id]/page.tsx` |
| Shared (one line or namespaced) | `frontend/lib/auth/routing.ts` (+ its test), `frontend/lib/i18n/client-strings.ts` (`adminResearch`), `frontend/locales/{en,sw}.json` (`admin.*`, `adminResearch.*`, `problem.*`, `_meta.reviewP11f`, appended at the end) |
| E2E | `frontend/e2e/research.spec.ts`, `frontend/e2e/support/research-scene.ts` |

**What it does.** Staff land on `/admin` (see fix round 1 for who), which opens the first section their role may use
(Research for staff admins); `AdminNav` lists sections by role, so P15 adds Moderation and Claims as rows. Before fix
round 1 the layout's gate rendered Next's not-found page for non-staff, which matched an unknown address only once
rendered (the raw response could differ before scripts ran); fix round 1 answers them with the unknown-address
response itself. Other staff roles are told Research is for staff admins. A stale second factor (403 `step_up_required`) shows a code form
in place of the page or of the action, which then repeats. `/admin/research`: "Start run" (the one primary action;
niches with saved Kenyan excerpts, country fixed to Kenya) posts the run and follows `GET …/runs/{id}` every 1.5 s
(40 polls at most, then "refresh later"), then refreshes the page; the cards waiting for review (AI-drafted or seeded
example, "Names an organisation": at most two tags); the five latest runs with a fixed outcome sentence per status and
stop reason (a failed run's error code is never shown); the saved excerpts folded by niche with their freshness.
`/admin/research/candidates/{id}`: the card as it would be published, every source through the shared `Citations`
(publisher, type, date, verbatim quote, https-only link), the D-45 names and the API's checklist text verbatim with
a confirm checkbox (checked on the page before the call), "Approve and publish" and "Reject" (asked twice). Every
refusal is a fixed sentence under `adminResearch.refusal.*` / `adminResearch.publish.*`; `refusalKey` is typed
against the locale keys. `/problems/{id}` (any signed-in side) renders `ProblemCard`: label in the page's language
(computed from `source`, `seeded_example`, `published_at`; never "AI-drafted" for a seeded card), statement, who is
affected, niche, region, confidence, named organisations and citations; a candidate, a rejected card and an unknown id
read "This problem is not available." (AC-RES-2). P12-F links to it with `problemHref(id)`.

**Tests.** Vitest: `problem.test.ts` (9: labels, dates, confidence, https-only links), `research.test.ts` (10: niche
options, run outcomes, publish reasons read only from the exact API sentence, refusal mapping, 404 never confirms),
`research-screens.test.tsx` (10: polling to refresh, resuming a running run, the 40-poll limit, refusals, step-up,
approve, checklist required, publish-check sentence, reject confirmation), `AdminNav.test.tsx` (2); routing test
updated for the staff home. Playwright `research.spec.ts` (both projects): the console is not found for signed-out
and non-staff visitors (same text and 404 as an unknown address); walkthrough step 3 (a staff admin signs in through
the login and MFA screens and lands on Research, starts a run that ends in the demo fallback and says so, a drafted
card naming SASRA is not visible to a developer, then is reviewed with its citations and checklist, approved, and read
by a developer with its sources; its review page then reads as gone); a stale second factor asks for a code; a
tampered source is refused with the `source_not_saved` sentence and never the API's words; rejecting keeps the card
private. `checkScreen` (axe, one `[data-primary]`, no horizontal scroll) on every screen. JS: `/admin/research` 143.7
KB, the review page 143.7 KB, `/problems/{id}` 140.1 KB gzipped (budget 150 KB).

**Open items (P11-F).**

1. **Publish-check reason (backend follow-up).** The API names the reason of a 409 `publish_check_failed` only inside
   its message ("This card cannot be published: <reason>."). The screen reads it from exactly that sentence and
   matches the known reasons (`research.ts` `publishReason`); any other wording falls back to the general sentence.
   Suggest `ApiError(409, "publish_check_failed", …, reason=violation)` in `review.decide` and `_refusal` so the web
   reads a key instead (no screen change beyond `publishReason`).
2. **No single-candidate route.** The review page finds its card in `GET /candidates` (at most 200). A
   `GET /candidates/{id}` would remove the list read.
3. **Runs on the dev stack make no card.** The fake LLM gives the demo fallback (D-37), so the E2E writes the drafted
   card as the database owner, as `app_create_research_candidate` would (research_agent, candidate, sources exactly
   as saved with their excerpt ids); approval goes through the real publish checks. The dev stack's seed has no staff
   account (the demo seed's `admin@staff.example` exists only after `python -m bridge.seed --demo`), so the E2E makes
   its own staff admin (owner sets `staff_role` and `demo_account`; TOTP through the API).
4. **Staff home** (superseded by fix round 1): `homeFor` is the side's portal again; `homeOf` sends only staff with a
   console section and TOTP to `/admin`.
5. **Signed-out `/admin` is 404, not a login redirect**, so the console is not discoverable (the API's rule); staff
   sign in at `/login` and land on it.
6. **Problem page has no portal navigation** yet: `DevNav` has no Discover row to mark until P12-F; the page carries
   a "Back to home" link. County is shown as its code (no regions lookup on this page).
7. **Copy.** All new strings are `[[COPY-REVIEW]]` (`_meta.reviewP11f`); Swahili is a draft (`[[SW-REVIEW]]`). The
   D-45 checklist text is the API's placeholder until the G2 legal pack. `problem.label.*` mirrors the backend labels.
8. **Mobile tab bar with one item** until P15 adds sections. The `impeccable` skill is not installed here; the polish
   pass was done by hand against docs/spec/07 with screenshots at 375 and 1440 px.
9. **Commit sizes** over about 300 lines: `c6f0573` (+334, both locale files), `56aa389` (+320, with tests),
   `35f8379` (+511, StartRun, Decision and their tests), `996eb6e` (+414, E2E spec and scene).

### P11-F fix round 1 (reviewer PASS with 7 MINORs; ux-reviewer CHANGES_REQUIRED, 2 MAJORs and 8 MINORs)

- **UX MAJOR 1, the Reject flow's focus** (`7cf0411`). Reject opens a question that takes focus (a `role="group"`
  labelled by the question, `tabIndex=-1`); Cancel returns focus to Reject. Vitest checks both with the focused
  element; the E2E checks `toBeFocused` and runs `checkScreen` in the confirm state.
- **UX MAJOR 2, the run status region** (`e4bc2c5`). The `role="status"` line stays in the tree while empty (no
  `display:none`) and outside the part a step-up replaces, so it is the same node before and after (tested).
- **UX MINORs** (`e4bc2c5`, `7cf0411`, `baec7fb`). After a step-up, focus goes to Start run (inline) or the page's h1 (whole page; `PageStepUp` focuses it
  when the refreshed page replaces the form). The step-up reason is the `OtpInput` hint (`aria-describedby`). After a
  failed publish check (any reason: the card's text and sources cannot change) Reject is the one primary action and
  Approve is `aria-disabled` and secondary; after `already_decided` or `not_found` only "Back to Research" remains, as
  the primary. Candidate title links are 44 px targets (`expectSeparateTargets` in the E2E). With one section there is
  no bottom tab bar on phones (the rail from 1024 px). Excerpt freshness has an icon; the saved-excerpts `<summary>`
  holds an h2. `adminResearch.runs.demoFallback` is "No card: this run used the demo fallback (no live model answer)."
  and `admin.noSection` links to the person's portal home [[COPY-REVIEW]].
- **Reviewer MINOR 1, not-found before scripts run** (`d56bd77`). `frontend/proxy.ts` (Next 16 Proxy, matcher `/admin`, `/admin/:path*`) asks `GET /api/admin/me`
  with the session cookie only: 200 or 403 `step_up_required` go on; anything else (signed out, not staff, staff
  without TOTP, a slow or failed answer: fail closed) is rewritten to an unmatched path, so the response is the
  unknown-address 404 itself. The E2E compares the raw responses (status, `<html lang>`, `<title>`) and the rendered
  text for signed-out visitors, a developer and staff without TOTP. Cost: one API call per `/admin` request. No
  THREAT_MODEL residual is needed.
- **MINOR 2.** A 409 `checklist_required` (the API found a name the card does not list) shows the checklist text (when
  the API sent one) and the checkbox; the next approval sends `checklist_confirmed: true`.
- **MINOR 3.** Render tests `components/problem/problem-render.test.tsx`: `Citations` and `SavedExcerpts` draw no
  `<a>` for `javascript:`, `data:` or http URLs; `ProblemCard` with `seeded_example: true` shows the seeded sentence
  and never "AI-drafted"; freshness marks carry an icon.
- **MINOR 4, staff who are also developers or members** (`c33b89e`). `homeFor(side)` is the side's portal again (staff: `/dev`, as
  before P11-F; nothing redirects staff away from the portals). `homeOf(me)` / `destinationFor` send a staff member to
  `/admin` only when the role has a console section (`CONSOLE_ROLES`, kept equal to `ADMIN_SECTIONS`' roles by a test)
  and TOTP is on. The API still reports `side: "staff"` for any staff account, so a staff member who is also an
  organisation member cannot use `/org` (unchanged from before P11-F). Suggested DECISIONS-NEEDED entry: whether staff
  accounts must be separate from developer and organisation accounts (docs/spec/03 roles), since the `side` rule
  hides a staff member's organisation portal.
- **MINOR 5.** The gate (`staff.ts`) uses `GET /api/admin/me`: staff without TOTP get the not-found answer like the
  API; the "turn on two-step sign-in" prompts inside the console are gone (unreachable). Such staff land on `/dev`.
- **MINOR 6.** `frontend/.env.example` names `e2e/support/research-scene.ts` for `E2E_DATABASE_OWNER_URL`.
- **MINOR 7.** The "What it does" paragraph above no longer claims the pre-fix gate matched an unknown address.
- **Merge prep.** The `admin`, `adminResearch` and `problem` namespaces now sit right after `verifyFile`, and
  `_meta.reviewP11f` first in `_meta`: against `84e0af0` both locale files change by pure insertions, away from the end
  where P14-F appends its billing block.
- Commit `baec7fb` is larger than about 300 lines because it moves the locale block (both files).

### P11-F round-2 review MINORs (2026-09-30; reviewer PASS and ux-reviewer PASS on 1911acb)

1. `frontend/proxy.ts:42`: rewritten `/admin` answers carry `x-middleware-rewrite: /_bridge-unmatched` (and
   `x-nextjs-rewrite` on `_next/data`), which a real unknown address lacks; strip them at the edge (Phase 8 Caddy) or keep
   as a residual, then assert headers in the e2e's `rawAnswer`.
2. `proxy()` itself is untested (only `admitsStaff`): a mutation forwarding the whole Cookie header survived; add a unit
   test with a `NextRequest` carrying several cookies.
3. After a failed publish check, the `aria-disabled` Approve still looks enabled; give it an unavailable style or drop it.
4. Merge note: on the merged tree one full vitest run failed `recovery-codes.test.tsx` ("clears the codes at the end of
   setup too"); it passed alone and in two further full runs (860/860), a timing flake under load (P17-F's test).
