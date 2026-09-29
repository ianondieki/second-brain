# REQ-SCOUT-01 (with REQ-SCOUT-02, REQ-SCOUT-03, REQ-ENG-04)

- Task: P10 Scout agent (`docs/platform/PLAN.md` §8, prototype track M2; `docs/platform/prototype-m2-plan.md`). This
  card starts with the schema of M2, revision 0005, which also carries P11 research (REQ-RES-01), P12 trends
  (REQ-TREND-01) and P14 fake payments (REQ-BIL-08, the REQ-BIL-04 interface); the P10 implementer's sections follow.
- Agent: db-migrations (xhigh) for revision 0005; security-reviewer (0005 is on its list, `prototype-m2-plan.md` §5),
  reviewer.
- Files owned (revision 0005): `backend/alembic/versions/20260929_0005_schema_v4.py`, `bridge/matching/{__init__,models}.py`,
  `Payment` in `bridge/billing/models.py`, `ResearchRun` and the new columns in `bridge/problems/models.py`, the new
  enums in `bridge/models/enums.py`, `bridge/models/all.py`, `backend/tests/integration/{schema_v4,world,test_migrations}.py`,
  `backend/tests/integration/matching/`, `backend/tests/integration/problems/`,
  `backend/tests/integration/billing/test_payments_{schema,serialisation}.py`.
- Depends on: integration head `9b0f5f5` (revisions 0001 to 0004). D-43 (no scout database role in the prototype):
  no schema change, as asked.

## Scope

P10 (from `prototype-m2-plan.md` §1): org sets niches and keywords; matching by niche and keyword rules with the fake
embedder; the LLM writes the "why this matches" line; Express interest → `ORG_INTEREST` → the developer accepts →
`INTEREST_CONFIRMED` (EM2). Revision 0005 is the schema of §2 of that plan, exactly its list, nothing from its "Not in
0005" line (`webhook_events`, stored recommendations or trend scores, the `proposal_versions` policy tightening,
`users.totp_pending_since`, claim-decision fixes).

## Revision 0005 (db-migrations, 2026-09-29)

Branch `feat/REQ-SCOUT-01-schema-0005`. One revision, `0005` (revises `0004`), additive. The revision file is about
1100 lines, more than the usual commit size: it is one commit with the ORM models (`alembic check` needs both).

**Enums (5).** `scout_frequency` (daily, weekly, on_new; also an agent run's `trigger`), `agent_run_status` (running,
completed, failed), `match_feedback` (relevant, not_relevant), `research_run_status` (running, completed, stopped,
failed), `payment_status` (pending, succeeded, failed, cancelled). The payment provider is `varchar(16)` with
`CHECK (provider IN ('fake'))`.

**Tables.** UUIDv7 keys, `timestamptz`, KES in `bigint` minor units; RLS enabled (not forced) on all five.

| Table (tenancy) | Columns | Rules (bridge_app) |
|---|---|---|
| `scout_agents` (ORG) | org_id, niches uuid[] (1-5 distinct), counties text[] (≤47 codes ≤8), include/exclude_keywords text[] (≤20 distinct × ≤60, non-blank), maturity proposal_maturity[] (≤4), budget_band (a code), min_fit (0-100, 60), frequency (weekly), language (en/sw), recipients uuid[] (≤20 distinct), paused_at, cursor_at, cursor_proposal_id, created_by, timestamps | UNIQUE (id, org_id). SELECT members; INSERT (as `created_by`), UPDATE, DELETE the owner or admin; UPDATE column-scoped to the form, pause, cursor and `updated_at`. Recipients: active reviewers of the organisation when written (`scout_agents_recipients`, AFTER, every role). Deleting a scout deletes its runs and matches (ON DELETE CASCADE) |
| `agent_runs` (ORG) | scout_id + org_id (composite FK to the scout, CASCADE), trigger, status, started_at (`app_clock_now()` default), finished_at, window_start, window_end, scanned_count, matched_count, error_code | SELECT members; INSERT a running run (no finish, no error) and UPDATE (status, finish, counts, error code) by acting members (owner, admin, signatory, reviewer); no DELETE. CHECKs: finished exactly unless running; a failed run carries a code (`^[a-z][a-z0-9_]{0,39}$`), no other does; window in order; counts ≥ 0 |
| `agent_matches` (ORG) | scout_id + org_id (composite FK, CASCADE), proposal_id + version_id (composite FK to `proposal_versions`), niche_id, score (0-100), rule_breakdown jsonb (object ≤4 KB), rationale (≤600, non-blank), rationale_demo_fallback, injection_suspected, digest_sent_at, feedback, feedback_reason (a code), feedback_by, feedback_at, created_at | UNIQUE (scout_id, proposal_id). SELECT members; INSERT by acting members, only for the current registered version of a published, clear proposal (read under the caller's RLS), with no feedback or digest time; UPDATE only the feedback columns (as oneself) and `digest_sent_at` |
| `research_runs` (STAFF) | niche_id, country (KE), county_code, status, started_by, created_at (the start), finished_at, searches, fetches, input_tokens, candidates, discarded, cost_usd numeric(12,6) (0-100), stop_reason (a code), demo_fallback, updated_at | Staff admin only: SELECT, INSERT a running run as `started_by`, UPDATE (status, finish, counts, cost, stop reason, demo flag). CHECK searches 0-25 and fetches 0-40 (AC-RES-3); a stopped or failed run carries a stop reason, no other does |
| `payments` (ORG_OR_USER) | user_id xor org_id (no CASCADE: records outlive their subject), plan_id, amount_kes_minor (> 0), provider, provider_ref (UNIQUE, `^[A-Za-z0-9_-]{16,64}$`, platform-generated), status, initiated_by, settled_at, subscription_id (UNIQUE), failure_code (a code), timestamps; no phone column | SELECT the user, or the organisation's owner, admin or finance member; INSERT pending (as `initiated_by`) for an active, non-default plan of the subject's side at exactly its price; no UPDATE, no DELETE. CHECKs: settled exactly unless pending; a failure code only when failed or cancelled; linked only when succeeded |
| `problems` (new columns) | research_run_id (FK, index; only on `research_agent` rows, CHECK), named_orgs text[] (≤10 × ≤200, CHECK) | Written only by `app_create_research_candidate`: bridge_app's INSERT on `problems` is now column-scoped to every other column (restored table-wide on downgrade); no UPDATE grant on them |
| `problem_sources` (new column) | excerpt_ref varchar(32) (`^[A-Za-z0-9_.:-]{1,32}$`) | The same: bridge_app's INSERT column-scoped to every other column |

**SECURITY DEFINER functions** (pinned `search_path = pg_catalog, public, pg_temp`, EXECUTE revoked from PUBLIC and
granted to bridge_app only; each checks its caller in SQL):

- `app_scouts_due(p_now timestamptz, p_trigger scout_frequency, p_proposal uuid DEFAULT NULL)` →
  `TABLE(scout_id, org_id, act_as_user_id)`: refused while a user is bound (the scouts.scan job runs unbound);
  refused without a time or trigger, or for on_new without a proposal (or a scheduled scan with one). Unpaused scouts
  of `p_trigger`'s frequency of E1 or E2 organisations that are not suspended. `act_as_user_id` is the scout's creator
  while an active owner or admin (and an active user), else the organisation's earliest such member; none, not due.
  daily and weekly: not already run (running or completed; a failed run may be retried) in the Africa/Nairobi day or
  ISO week of `p_now`. on_new: only for a published, clear proposal the scout has not matched yet.
- `app_create_research_candidate(run, title, statement, affected_group, county, confidence, named_orgs, sources jsonb)`
  → the card's id: staff admin only; the caller's own running run (read FOR SHARE); confidence 0.40 to 1; a title of 1
  to 90 characters and a statement of 1 to 120 words; a county run's card is of its county; 1 to 10 sources, each an
  object of strings with an https URL (no whitespace or user info, ≤1000), a published date (YYYY-MM-DD, a real date),
  a retrieval time, a non-blank quote (≤2000), optionally a publisher, a source type of the 6.5 tiers (official,
  filing, news, ngo, blog, social) and an excerpt ref, nothing else (`app_research_source_is_valid`, internal); an
  official source when the card names organisations. Inserts a `research_agent` candidate (ai_generated, `created_by`
  NULL, niche and country from the run) and its sources in one call.
- `app_settle_payment(payment, status, failure_code DEFAULT NULL)` → boolean: the subject only (`app_is_payment_subject`,
  internal; one refusal, the same for a payment that does not exist, taken before any lock); pending → succeeded,
  failed or cancelled; a failure code (a code) only for failed or cancelled; the same outcome again is a no-op (false);
  another outcome is refused.
- `app_activate_paid_subscription(payment)` → the subscription id: the subject only; per-subject advisory lock, then
  the payment's row lock; a linked payment returns its subscription (idempotent); only a succeeded payment whose plan
  is of the subject's side at the amount paid; cancels the subject's live subscription (trialing, active, past_due) and
  inserts the new one active from `app_clock_now()` for a month or a year (open-ended for `none`), then links it.
- `app_trend_aggregates(p_since, p_now)` → `TABLE(item_id, kind, day, events, actors, orgs)`: signal_events in
  `[p_since, p_now)` (≤400 days) per item, kind and Africa/Nairobi day; `events` counts each actor once per item and day
  (actor-less signals once a day); `actors` the item and kind's distinct actors over the window; `orgs` its distinct
  organisations only when ≥ 3, else NULL. No hash and no organisation id is returned.

**Triggers.** `payments_guard` (BEFORE INSERT, UPDATE, DELETE; every role) and `payments_no_truncate`
(`block_mutation`); `problems_research_guard` (BEFORE INSERT, UPDATE on `problems`, SECURITY DEFINER; every role): a
`research_agent` row reaches `published` only with one official source or two distinct publishers (lower-cased,
trimmed) among sources that carry a quote and a date (AC-RES-1), and with an official source when it names
organisations; `scout_agents_recipients` (AFTER INSERT, UPDATE, SECURITY DEFINER); `agent_runs_0_visible` and
`agent_matches_0_visible` (`scout_row_visible()`, SECURITY INVOKER, first BEFORE INSERT trigger by name).

**CHECK helpers** (IMMUTABLE, EXECUTE bridge_app because a CHECK runs them as the writer): `app_uuid_set_is_valid(uuid[],
min, max)` and `app_text_set_is_valid(text[], max, len)`: one-dimensional, distinct, non-NULL (non-blank, bounded).

### Owner of `app_trend_aggregates`: `bridge_owner`

docs/spec/08 has cross-organisation aggregates read under `aggregate_worker`. The migration role cannot make that role
the owner: probed on the test server, `ALTER FUNCTION … OWNER TO aggregate_worker` as `bridge_owner` fails with "must
be able to SET ROLE aggregate_worker" (`roles.sql` gives `bridge_owner` no membership in it), and `aggregate_worker`
would also need CREATE on schema `public`, which `prepare_db.sql` gives nobody but the owner. Granting either would
give a runtime role an owned object (`test_runtime_roles_own_nothing`) and a path to CREATE, and bridge_app cannot
switch to `aggregate_worker` (it is a member of the Tier-2 roles only, `test_bridge_app_membership_is_set_only_for_the_tier2_roles`).
So the definer is owned by `bridge_owner`, reads only `signal_events`, and returns counts only: its body is the whole
of its privilege and changes only by migration. The revision's docstring says the same. EXECUTE is bridge_app's only
(P12 computes trends on read in the API); a later `trends.recompute` job running as `aggregate_worker` would need a
grant in a later revision.

### Additions to the plan's list (reported for the orchestrator and the security-reviewer)

1. `scout_row_visible()` on `agent_runs` and `agent_matches` (found by the tests: another organisation naming a scout's
   id under its own `org_id` hit the unique (scout, proposal) key before the composite foreign key, so the refusal told
   it whether that scout had matched the proposal). Same pattern as 0003's `tracker_engagement_visible` (`600c927`).
2. `scout_agents_recipients` (recipients are active reviewers of the organisation when written; spec 6.8, AC-SCOUT-7).
3. The named-organisation rule (spec 6.5: "cards naming an org require an official source") in both the definer and the
   backstop. It holds under every option of D-45; the checklist wording stays D-45's.
4. `app_scouts_due` details the plan left open: refused while a user is bound; period de-duplication per Nairobi day or
   ISO week (failed runs retried); on_new only for a published, clear proposal not matched yet; the acting-member rule.
5. `app_settle_payment`: "pending → final once" read as: the same outcome again is a no-op returning false (a repeated
   provider query or callback, AC-SUB-2's shape), a different outcome is refused.
6. `payments`: no ON DELETE CASCADE (a subject with payments cannot be hard-deleted; erasure pseudonymises, REQ-SEC-02),
   `subscription_id` UNIQUE, `payments_no_truncate`, and the guard's INSERT rule (pending, unsettled, unlinked) for
   every role; activation serialised per subject (advisory lock) so two checkouts never both miss the live subscription.
7. `research_runs` counts beyond searches and fetches (`input_tokens`, `candidates`, `discarded`) and the stop reason as
   a code; `agent_runs.trigger` reuses `scout_frequency` (no new enum); `agent_runs.started_at` defaults to
   `app_clock_now()` so due-ness follows the test clock.
8. bridge_app's INSERT on `problems` and `problem_sources` column-scoped (the plan said "not updatable by the app"; a
   table-wide INSERT would still let the app write them).

### Operating rules for P10, P11, P12 and P14

- Scan job: call `app_scouts_due(app_clock_now(), trigger[, proposal])` unbound, then `bind_tenant(user_id=act_as_user_id,
  org_id=org_id)` per scout; write the run, the matches and the cursor under that binding; leave `started_at` out.
  Insert matches with `ON CONFLICT (scout_id, proposal_id) DO NOTHING` and the proposal's `current_version_id`.
  `app.org_id` narrows every scout predicate: bind the scout's organisation.
- Map "no scout of the caller's with that id" (insufficient_privilege) to 404, like any cross-tenant reference.
- The digest re-checks each recipient's membership, reviewer role and verified domain at send time; `recipients` is
  only validated when written.
- Research: bind the staff admin who started the run; create cards only through `app_create_research_candidate`
  (send `confidence` as a Decimal or numeric); approval is `app_moderate_problem(id, 'clear', 'published')`, whose
  AC-RES-1 refusal (check_violation) maps to 409.
- Payments: insert pending at the plan's price with a platform-generated `provider_ref`; query the provider; then
  `app_settle_payment` and `app_activate_paid_subscription` (refresh the ORM rows afterwards). Nothing else writes a
  payment.
- Trends: `SELECT * FROM app_trend_aggregates(since, now)`; apply the display rules (≥3 actors before "Trending",
  no organisation counts on project badges) in code.

### Tests (123 new; full backend suite 3048 → 3173 collected)

- `integration/test_rls.py` (generated from model `info`): tenant isolation for `scout_agents`, `agent_runs`,
  `agent_matches`, `payments` (with and without an org context, a forged context) and staff-only `research_runs`
  (+14). Fixtures in `integration/world.py` (`add_scout_rows`, a pending payment per subject, a stopped research run
  per tenant).
- `integration/test_migrations.py`: grant matrix and column UPDATEs, the function catalog (definer, EXECUTE, pinned
  path), the trigger catalog, the column-scoped INSERT on `problems` and `problem_sources`, what bridge_app may not
  change, the pg_temp shadowing check over the new definers, the enum freeze (automatic), and the round trip, which now
  checks that 0005 leaves 0004 exactly as it found it and runs `alembic check` at head (+31).
- `integration/matching/test_scout_schema.py` (23), `integration/matching/test_trend_aggregates.py` (4),
  `integration/problems/test_research_schema.py` (40), `integration/billing/test_payments_schema.py` (10),
  `integration/billing/test_payments_serialisation.py` (1, own database: two activations of one subject).
- Each definer's refusals: wrong role (developer, moderator, nobody, a non-paying member), wrong organisation (another
  organisation, a forged context), wrong run (another admin's, finished, none), bad sources (22 cases), low confidence
  (0.39, 0.3999), a second settle with another outcome, amount or side mismatch at activation, a bound user for
  `app_scouts_due`, bad windows for `app_trend_aggregates`. Cross-tenant reads return nothing (generated and explicit).

### Mutation proofs

Each proof breaks one guard in the revision file, runs the named test (red), and restores the file byte for byte
(`git status` clean after every batch); the restored tree then ran every test used here green (610 passed). Command (in
`backend/`; the fixtures build a fresh database from the revision file on every run):
`TEST_DATABASE_ADMIN_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/postgres .venv/bin/python -m pytest -q -p no:cacheprovider <test>`.

| Proof | Guard broken | Test (red) |
|---|---|---|
| M1 | payments INSERT policy: the plan's price | `billing/test_payments_schema.py::test_a_payment_starts_pending_for_a_paid_plan_of_the_subjects_side_at_its_price` |
| M2 | payments INSERT policy: the subject's side | the same |
| M3 | `payments_guard`: never deleted | `::test_the_guard_keeps_every_payment_for_every_role` |
| M4 | `payments_guard`: subject, plan, amount, reference fixed | the same |
| M5 | `payments_guard`: settled once | the same |
| M6 | `payments_guard`: starts pending for every role | the same (the CHECK then refuses with its own message) |
| M7 | `app_settle_payment`: the subject only | `::test_a_payment_is_settled_once_by_its_subject` |
| M8 | `app_settle_payment`: once | the same (a repeated settle returned true) |
| M9 | `app_activate_paid_subscription`: idempotent | `::test_activation_is_idempotent_and_replaces_the_live_subscription` (the guard refused the relink) |
| M10 | activation: side and amount match the plan | `::test_activation_needs_a_succeeded_payment_matching_its_plan` (2 cases) |
| M11 | activation: the subject only | `::test_activation_is_idempotent_and_replaces_the_live_subscription` |
| M12 | activation: per-subject advisory lock | `billing/test_payments_serialisation.py::test_two_activations_of_one_subject_are_serialised` (unique violation on the live subscription) |
| M13 | `app_create_research_candidate`: staff admin only | `problems/test_research_schema.py::test_only_a_staff_admin_creates_candidates_on_their_own_running_run` (the run check still refused, with another message) |
| M14 | the caller's own run | the same |
| M15 | sources: https only | `::test_every_source_needs_an_https_url_a_date_and_a_quote[http]` |
| M16 | confidence ≥ 0.40 (lowered to 0.30) | `::test_a_candidate_is_refused_below_its_bounds` (0.39, 0.3999) |
| M17 | an official source for named organisations (definer) | the same (named case) |
| M18 | backstop: one official source or two publishers | `::test_a_research_card_publishes_only_with_…` and `::test_the_backstop_holds_…` (3 failed) |
| M19 | backstop: publishers compared lower-cased and trimmed | `::test_a_research_card_publishes_only_with_an_official_source_or_two_publishers[one_publisher_twice]` |
| M20 | backstop: an official source for named organisations | `::test_the_backstop_holds_for_every_role_and_every_way_in` |
| M21 | `app_scouts_due`: E1 and E2 only | `matching/test_scout_schema.py::test_only_active_scouts_of_verified_unsuspended_organisations_are_due` |
| M22 | `app_scouts_due`: not suspended | the same |
| M23 | `app_scouts_due`: unpaused | the same |
| M24 | `app_scouts_due`: no user bound | `::test_due_scouts_are_asked_for_by_the_scan_job_only` |
| M25 | `app_scouts_due`: once per Nairobi day or ISO week | `::test_a_scheduled_scout_is_due_once_per_nairobi_day_or_week` |
| M26 | `app_trend_aggregates`: organisations only from 3 | `matching/test_trend_aggregates.py::test_organisations_are_counted_only_from_three` |
| M27 | `app_trend_aggregates`: once per actor, item and day | `::test_events_count_each_actor_once_per_item_and_day` |
| M28 | `scout_agents` UPDATE: owner or admin only | `::test_members_read_and_only_the_owner_or_admin_configures_a_scout` |
| M29 | `agent_runs` INSERT: a run starts running | `::test_runs_are_written_by_acting_members_and_never_deleted` |
| M30 | `agent_matches` INSERT: current version of a published, clear proposal | `::test_matches_name_the_current_version_of_a_published_clear_proposal` |
| M31 | `agent_matches_0_visible` dropped | the same (the unique-key error came back) |
| M32 | `scout_agents_recipients` dropped | `::test_recipients_are_active_reviewers_of_the_organisation` |
| M33 | `research_runs` SELECT: staff admin only | `test_rls.py::test_staff_tables_are_read_by_staff_only[research_runs]` |
| M34 | `research_runs` CHECK: 25 searches, 40 fetches | `problems/test_research_schema.py::test_research_runs_are_staff_admin_only_and_capped` |
| M35 | payments SELECT and INSERT: owner, admin or finance | `billing/test_payments_schema.py::test_only_the_subject_reads_a_payment` |
| M36 | `problems` INSERT column-scoped | `test_migrations.py::test_bridge_app_inserts_every_column_but_the_research_ones[problems-…]` |

Result on the branch: full backend suite 3173 passed (3048 at `9b0f5f5`); `ruff check`, `ruff format --check`,
`mypy --strict`, `python -m bridge.openapi --check` (no drift) and `check_traceability.py` (0 errors) clean;
`alembic check` clean at head in the round trip.

### Open questions (for the orchestrator)

1. Security-reviewer round on 0005 (it is on the §5 list): especially the owner of `app_trend_aggregates` and the
   payment definers.
2. The database cannot tell a paid checkout from a claimed one: a subject can settle their own payment as succeeded
   through `app_settle_payment`; the provider query is the application's (spec 05). Acceptable with the
   FakePaymentProvider only (D-36); before any real provider (REQ-BIL-04, after G4) settlement should move to a
   platform path (`webhook_events`, the STK Push Query, a job with no user bound). Not in 0005.
3. A price change in `plans.yaml` between a payment and its activation (G3, D-44) blocks the activation (the amount no
   longer matches); P14 shows "contact us" or re-prices. Fine for the prototype?
4. `agent_runs.started_at` is insertable by the app (table-wide INSERT), so a buggy job could backdate a run and skip
   its organisation's own next scan; only that organisation is affected. Narrow the INSERT later if wanted.
5. A staff admin can reopen a finished research run (`status = 'running'`, `finished_at = NULL`) and add candidates;
   staff admin only, every candidate still needs approval and the backstop. Accept, or add a transition guard later.
6. Pointers from the REQ-RES-01, REQ-TREND-01 and REQ-BIL-08 cards: those cards do not exist yet; their implementers
   (P11, P12, P14) start from this section.
