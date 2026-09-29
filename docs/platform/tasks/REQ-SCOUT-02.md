# REQ-SCOUT-02 (with REQ-SCOUT-01's API, REQ-SCOUT-03 and the stage-0 half of REQ-ENG-04)

- Task: P10 Scout agent, backend (`docs/platform/PLAN.md` §8, prototype track M2, never cut;
  `docs/platform/prototype-m2-plan.md` §1 P10, §3 P10 routes, walkthrough step 1). The screens are P10-F.
- Agent: impl-backend (xhigh). Reviews: reviewer; security-reviewer (P10-B is on `prototype-m2-plan.md` §5:
  `bridge/engagements/interest.py`, the Tier-2 share, the signals).
- Branch `feat/REQ-SCOUT-02-scouts`, from `feat/REQ-SCOUT-01-schema-0005` (revision 0005, merged again at `1da7349`
  after its review fix round). No Alembic revision.
- Files owned: `bridge/matching/{config,pipeline,rationale,scan,digest,scouts,matches,schemas,tasks,runtime,__main__}.py`,
  `bridge/jobs/scouts.py`, `bridge/engagements/{interest,interest_router}.py`, `bridge/tenancy/signals.py`,
  `bridge/notifications/n17.py`, `bridge/notifications/templates/{em3,n17}.*.j2`, `backend/config/matching/weights_v1.yaml`,
  the `scout_fit_rationale` task in `backend/ai/models.yaml`, the tests below. Touched: `bridge/main.py` (three
  routers), `bridge/jobs/app.py` (`IMPORT_PATHS`), `bridge/proposals/service.py` and `bridge/admin/moderation.py`
  (one `defer_on_new` line each), `bridge/engagements/notify.py` (N17), `bridge/engagements/schemas.py` (two
  shapes), `backend/openapi.json`, `frontend/lib/api/schema.d.ts`.
- Card of the schema: `tasks/REQ-SCOUT-01.md` (revision 0005 and its operating rules, which this code follows).

## Scope and design

**Rules first, the model second (docs/spec/04 plain code decides).** `pipeline.candidates` reads, under the run's
tenant, the current registered version (`proposals.current_version_id` only) of published, clear proposals and
applies the hard filters in SQL: the niche (or a child of a parent niche the scout chose), the counties, the maturity,
the exclude keywords (case-insensitive substring, AC-SCOUT-5; the code checks again), not the organisation's own
members' proposals, not already matched by this scout, the publication window. `pipeline.score` is deterministic
(`config/matching/weights_v1.yaml`): 50 points of include-keyword overlap (the prototype's stand-in for the fake
embedder's meaningless cosine: **simulated**, README), 30 of niche (exact 1.0, through the parent 0.7), 10 for a
delivered tag to this organisation, 10 of Tier-1 evidence (impact claims, a linked published problem). `select_top`
keeps `min_fit` and the top 50. The model (`scout_fit_rationale`, Sonnet 5 / free slots, no tools, Tier 1 only) writes
"why this matches" and a 0-100 fit for the top 10 only; `final = 0.6·deterministic + 0.4·fit` when it answered
cleanly. A demo fallback, `injection_suspected`, a schema failure or an error keeps the deterministic score and the
code's "Matched on ..." line (`rule_breakdown.why_source` `code`, the reason kept). The model never adds or drops a
match, so Preview (rules only) equals the first digest.

**Runs (`scan.py`, `jobs/scouts.py`).** `scouts.scan` every 15 minutes from 07:00 EAT on the shared clock;
`app_scouts_due` (unbound) names each due scout and its acting member; the run binds that member and the organisation
(one tenant per run), re-reads the scout (paused: skipped), re-checks the plan's frequencies (skipped `plan`), commits a
`running` run, then in one transaction writes the matches (`ON CONFLICT DO NOTHING`, server ids), a `scout_match`
signal each, the cursor and the completed run; a failure marks the run `failed` (`scan_failed`) and moves nothing.
Window: the first scan covers 30 days (Preview's window); later scans continue from the cursor with a one-hour overlap
(a publication whose transaction committed after the previous read; already matched proposals are left out in SQL);
after a run that hit `limits.scan_per_run` the next continues strictly after its last proposal. `scouts.on_new` runs the
on_new scouts of one publication, queued by the publication's own transaction in a savepoint
(`matching.tasks.defer_on_new`): from `publish` when the teaser is visible and from a moderator's approval of a held
proposal; a failure to queue is logged and never fails the publication. `python -m bridge.matching run [--now]
[--proposal ID]` runs a pass now (dev and test only).

**EM3 (`digest.py`, N02).** After a completed run: the scout's undigested matches (current teaser, still published and
clear), at most 10 (3 on a `top_3` plan) with the niche label, fit, the why and who wrote it ("AI-drafted from the
teaser", "Matched by the scout's rules", or the demo-fallback label), the rest summarised as "N more in your inbox";
recipients re-checked at send time (active reviewer, active user, verified address at the verified domain, E1 or E2,
not suspended); in-app always, email per the `em3` preference, once per run; every match read is then marked
`digest_sent_at`. Code-rendered, defanged, links to signed-in pages only (`/org/inbox/matches/{id}?org=`,
`/org/inbox?org=&tab=matches`, for P10-F), nothing changes on GET.

**APIs.** `GET|POST /api/orgs/{org_id}/scouts` (members read; owner or admin create; 402 beyond `scout_agents` or for a
frequency the plan lacks; 422 for unknown niches (inactive ones too), counties, budget bands or non-reviewer
recipients), `GET|PATCH|DELETE .../scouts/{id}` (PATCH pauses and resumes; resuming re-checks the plan),
`POST .../scouts/preview` (owner or admin; 30 days, rules only: no model, no write, nothing queued; pending
organisations too), `GET /api/orgs/{org_id}/matches[/{id}]` (members; current teaser, niche label, score, why,
`why_source`, `demo_fallback`; the detail adds the rules, the organisation's engagement and whether the caller may
express interest, with the reason when not), `POST .../matches/{id}/feedback` (owner, admin, signatory or reviewer;
relevant or not relevant with a reason code; a feedback stays its author's: 409 `feedback_given`). Stage 0:
`POST /api/orgs/{org_id}/interest` and `GET|POST /api/engagements/{id}/share-tier2` (`tasks/REQ-ENG-04.md`).

**D-43 (a).** No scout database role in the prototype: `unit/matching/test_no_tier2_imports.py` (the scout's modules
never import `as_role`, a Tier-2 or decrypting module or model, nor name a Tier-2 role or table in a string) and
`integration/matching/test_redteam_isolation.py` (AC-SCOUT-3: Tier-2 markers, an older and a newer draft version and
another organisation's scout; the captured prompts, ledger rows, matches and digest carry none of them, one tenant per
model call). Every new output schema (`ScoutFit`) has `demo_fallback()` with `injection_suspected=True`, and the flag
is honoured; every `InputField` has its owner (the scout's creator, the proposal's owner), so the D-37 rule sends only
demo accounts' text to a free provider.

**Signals (for P12).** `scout_match` (actor: the organisation's pseudonym; the scout acts for it) and `org_interest`
(actor: the signatory's salted digest), both with `org_hash = HMAC-SHA-256(k, org_id)`, `k` derived from
`SECRET_KEY` (`bridge.tenancy.signals`).

## Deviations and decisions to note

1. Cosine replaced by keyword overlap (simulated; `prototype-m2-plan.md` §6). No Haiku screen or Message Batches: one
   call per top match, at most 10 per run, cached by the match row (a proposal is matched once per scout).
2. **Budget band not applied**: proposals carry no budget. The band is validated against `weights_v1.yaml` and stored.
   To apply it, a later revision (db-migrations) would add `budget_band varchar(32)` (the scout's CHECK pattern) to
   `proposals` and `proposal_versions`, set by the editor and copied at publish; then one more hard filter.
3. A held proposal approved later reaches on_new scouts (the approval queues `scouts.on_new`) but not daily or weekly
   ones whose cursor has passed its `published_at` (only the one-hour overlap). Follow-up: a moderation-cleared time
   in the window.
4. Not built (REQ-SCOUT-01, -05, -06, -07 depth): the `min_fit` ±5 feedback loop and suggested exclusions, the
   80%/100% cost ledger degradation note (the LLM layer's caps apply), the injection eval suite, recipients "capped per
   plan" (no plan key: 20 by the schema), a count check at scan time after a downgrade (the plan's frequency is
   re-checked; the count is checked at create and resume).
5. **Blocked here: item 7 (demo seed) and `make demo-scouts`.** The P9 code they extend (`bridge/seed/demo/`,
   `infra/demo/demo.py`, the Makefile's demo targets) is on the integration branch (`af977ef`), not on this branch;
   merging the integration branch into this branch was refused twice by the session's permission check (once before
   the orchestrator asked for it, once after), so it needs the owner's permission or the orchestrator's own merge.
   After that merge: a `bridge/seed/demo/scouts.py` step (a scout per E2 fixture with its reviewer seats as
   recipients, one untagged published proposal in each scout's niche, Telco A on `org_growth`, keeping what people
   changed) registered in the demo `__init__`, and `demo-scouts: $(DEMO) scouts` with `cmd_scouts` running
   `python -m bridge.matching run --now` in the worker.

## Tests

Unit (`tests/unit/matching/`): `test_config.py` (weights load and fail closed), `test_pipeline_rules.py` (points,
selection, final score, the code line), `test_rationale.py` (clean answer, `injection_suspected`, demo fallback,
errors, owners and tiers of the input), `test_digest_render.py` (`test_niche_label` AC-REPO-4/b; escaping and
defanging AC-MAIL-5; platform links only; the cap; determinism), `test_jobs_and_cli.py`, `test_no_tier2_imports.py`
(D-43), `test_refusals.py` (the database's backstop refusals); `tests/unit/notifications/test_n17.py`; `tests/unit/engagements/test_notify.py::test_an_organisations_interest_tells_the_developer_n17`.

Integration (`tests/integration/matching/`): `test_scan.py` (AC-SCOUT-5 filters and the SQL exclusion before the
limit, the parent niche, the model's top N, no model, injection, AC-SCOUT-6 cursor and truncated runs, on_new, the
plan's frequency, a failed run, AC-SCOUT-1/AC-SCOUT-7 recipients, the email preference, the `top_3` digest, signals,
AC-SCOUT-8 pending organisations, the scan time, the digest on matches with another member's feedback, a scout paused
or gone since it was due, a failed delivery),
`test_scout_config.py` (`test_filters_and_preview` AC-SCOUT-5, `test_admin_niche` AC-DIR-5/b, roles, 402s, 422s,
pending organisations), `test_matches_api.py` (reads without side effects, tenancy, feedback, held proposals, E1),
`test_on_new_hook.py`, `test_redteam_isolation.py` (AC-SCOUT-3), `test_stage0_from_digest.py` (AC-TRACK-8/b);
`tests/integration/engagements/test_stage0.py`, `test_share_tier2.py` (`tasks/REQ-ENG-04.md`).

## Mutation proofs

Each proof broke one guard in a copy of `backend/`, ran the named tests (red) and restored the file byte for byte;
the copy was then compared with the worktree (identical).

| Proof | Guard broken | Test (red) |
|---|---|---|
| P1 | pipeline: the exclude keywords' SQL filter | `integration/matching/test_scan.py::test_exclusions_filter_in_sql_before_the_limit` |
| P2 | pipeline: the county filter | `test_scan.py::test_filters_niche_county_maturity_and_exclusions` |
| P3 | pipeline: a parent niche covers its children | `test_scan.py::test_a_parent_niche_matches_its_children_and_scores_them_lower` |
| P4 | pipeline: the current version only (read version 1 instead) | `test_redteam_isolation.py` (the older version's marker reaches the prompt) |
| P5 | pipeline: a scout's earlier matches left out in SQL | `test_scan.py::test_the_cursor_includes_each_new_proposal_exactly_once` (scanned counts) |
| P6 | pipeline: `min_fit` | `unit/matching/test_pipeline_rules.py::test_selection_keeps_min_fit_and_orders_by_score_then_age` |
| P7 | rationale: `injection_suspected` honoured | `unit/matching/test_rationale.py::test_injection_suspected_is_honoured`, `test_scan.py::test_injection_suspected_keeps_the_rules_and_is_recorded` |
| P8 | rationale: a demo fallback is no answer | `test_rationale.py::test_the_demo_fallback_is_no_answer` |
| P9 | digest: recipients at the verified domain | `test_scan.py::test_the_digest_goes_to_verified_reviewer_seats_only` |
| P10 | digest: recipients still reviewers | the same |
| P11 | digest: the why defanged | `unit/matching/test_digest_render.py::test_party_and_model_text_is_escaped_and_defanged` |
| P12 | scouts API: 402 beyond `scout_agents` | `test_scout_config.py::test_plan_limits_answer_402` |
| P13 | scouts API: 402 for a frequency the plan lacks | the same |
| P14 | scan: the run binds the scout's acting member | `test_scan.py::test_filters_niche_county_maturity_and_exclusions` |
| P15 | scan: the plan's digest size (`top_3`) | `test_scan.py::test_the_free_plan_digest_lists_three_and_marks_all` |
| P16 | D-43: `as_role` imported into the scan | `unit/matching/test_no_tier2_imports.py` |
| P17 | matches API: feedback by acting members only | `test_matches_api.py::test_feedback_is_recorded_as_the_caller` (the UPDATE policy silently changed nothing) |
| P18 | on_new: the defer's savepoint | `test_on_new_hook.py::test_a_publication_never_fails_because_its_scouts_could_not_be_queued` |
| P19 | on_new: queued by a clear publish | `test_on_new_hook.py::test_a_clear_publication_queues_the_on_new_scouts` |
| E1 | interest: a signatory only | `integration/engagements/test_stage0.py::test_a_signatory_expresses_interest_from_a_scout_match_and_the_developer_accepts` (the database refused with another code) |
| E2 | interest: step-up | `test_stage0.py::test_refusals` |
| E3 | interest: E2 only | `test_stage0.py::test_an_e1_organisation_gets_403_until_e2` (the database refused with another code) |
| E4 | interest: the match is of that proposal | `test_stage0.py::test_refusals` |
| E5 | interest: the contact is an active member | the same (the database refused with 409) |
| E6 | share: the developer only | `test_share_tier2.py::test_only_the_developer_with_step_up_shares` |
| E7 | share: step-up | the same |
| E8 | share: organisation-origin engagements only | `test_share_tier2.py::test_nothing_is_shared_on_a_tagged_or_ended_engagement` |
| E9 | share: not on an ended engagement | the same |
| E10 | share: `counts_as_unlock` for an untagged proposal | `test_share_tier2.py::test_the_developer_shares_tier2_with_an_interested_organisation` |
| E11 | N17: the interest's genesis tells the developer | `unit/engagements/test_notify.py::test_an_organisations_interest_tells_the_developer_n17`, `test_stage0.py` (no N17) |

All 30 killed; every file restored byte for byte (compared after each proof). The target tests ran green unmutated
first (47 passed). Not proved separately, because a second layer answers the same: the code's re-check of the exclude
keywords (`pipeline.excluded`, behind the SQL filter of P1) and the feedback author pre-check (behind
`agent_matches_feedback_guard`, both 409 `feedback_given`).

## Open questions and follow-ups

1. security-reviewer round on `bridge/engagements/interest.py`, the N17 change in `notify.py` and `bridge/tenancy/signals.py`.
2. The orchestrator merges the integration branch here (or lets this branch merge first) so item 7 and
   `make demo-scouts` can be built (deviation 5).
3. Budget band (deviation 2) and held-then-approved proposals for periodic scouts (deviation 3): accept for the
   prototype, or schedule.
