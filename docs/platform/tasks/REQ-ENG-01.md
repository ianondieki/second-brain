# REQ-ENG-01 (with REQ-ENG-02)

- Task: P1 Schema v3 (prototype) (`docs/platform/PLAN.md` §8, M1); the schema half of REQ-ENG-01 and REQ-ENG-02. The
  state machine, the routes, the test-clock router, `events.py` and `history.py` are P5's.
- Agent: db-migrations (xhigh); security-reviewer (one round, `engagements/`), reviewer.
- Files owned: `backend/alembic/versions/20260929_0003_schema_v3.py`, `bridge/engagements/{models,chain}.py`, the new
  enums in `bridge/models/enums.py`, `users.demo_account` in `bridge/auth/models.py`, the test-clock step in
  `bridge/seed/reference.py`, `backend/tests/integration/engagements/`, and the schema v3 parts of
  `backend/tests/integration/{test_migrations,world,test_seed}.py`.
- Depends on: schema v2 (revision 0002, `feat/REQ-REPO-01-schema-v2` at `7fb11bf`).

## Scope

The thinnest schema that carries the M1 main path `SUBMITTED` → … → `CLOSED`, the `DECLINED` and `WITHDRAWN` branches,
and `ORG_INTEREST` for M2's scout (docs/spec/06 6.9), plus the D-37 demo-data flag and the dev/test clock shared by the
API and the worker. One revision, `0003` (revises `0002`), additive only.

## Design (revision 0003)

**Enums (10 new).** `engagement_actor_role` (developer, owner, admin, reviewer, signatory, finance, system),
`engagement_party` (developer, org), `endorsement_method` (click, totp, passkey, auto), `contact_channel` (email,
phone, whatsapp, video_call, in_person), `ip_terms` (the five of 6.9 stage 8), `agreement_status` (draft, final,
signed), `milestone_state` (the sub-tracker's five codes), `signature_document_kind` (mutual_nda, agreement,
acceptance_certificate, milestone_confirmation), `step_up_method` (totp, passkey), `payment_method` (mpesa, bank, other).

**Tables.** Every tracker table is Tenancy ORG_OR_USER with `via: engagements`: RLS, and a row is visible exactly when
its engagement is (the developer; members of the organisation, narrowed by `app.org_id`; staff admin through the new
`bridge_app_select_staff` policy on `engagements`). UUIDv7 keys, `timestamptz`, KES in `bigint` minor units.

| Table | Columns | Rules |
|---|---|---|
| `engagements` (new columns) | `stage_entered_at` (NOT NULL), `stage_deadline_at`, `ended_at`, `lock_version` (int, 0), `contact_user_id`, `contact_channel`, `contact_by` (date) | The chain's projection (below). CHECKs: `ended_at` set exactly in a terminal state; DECLINED and EXPIRED carry their reason codes (0002's CHECK replaced by a NULL-safe one); contact person, channel and date together; the contact is an active member of the organisation (guard). bridge_app: INSERT; UPDATE of the contact columns and `updated_at` only |
| `engagement_events` | id, engagement_id, seq (gapless per engagement), actor_user_id (NULL for the system), actor_role, command (`^[a-z][a-z0-9_]{0,39}$`), from_state (NULL only for the genesis), to_state, end_reason, stage_deadline_at, payload (jsonb), prev_hash, hash, created_at | Append-only, hash-chained (below). UNIQUE (engagement_id, seq), (engagement_id, prev_hash). CHECKs: a system event names nobody and a user event its actor; DECLINED/EXPIRED carry their reason codes (NULL-safe); 32-byte hashes; `app_event_payload_is_valid(payload)`. bridge_app: SELECT, INSERT |
| `engagement_endorsements` | id, engagement_id, stage, stage_round (the database's), milestone_id, party, user_id (NULL for auto), role, method, endorsed_at | Append-only. Unique index `uq_engagement_endorsements_once` (engagement, stage, stage_round, party, milestone_id) NULLS NOT DISTINCT. Only the stage the engagement is in (under its row lock); a milestone only at `IN_IMPLEMENTATION`; `auto` names no user and acts as the system; a `totp` endorsement needs TOTP enrolled. bridge_app: SELECT, INSERT |
| `agreements` | id, engagement_id, version (≥ 1), ip_terms, exclusivity (≤ 500 chars), deemed_acceptance_days (0–90; 0 = never deemed accepted), status, final_pdf_sha256, created_by, timestamps | UNIQUE (engagement_id, version), (id, engagement_id); one `signed` per engagement (partial unique index). Inserted as a draft; `final` needs the IP terms, the clause, the PDF hash (CHECK) and ≥ 1 milestone (trigger) and freezes them; `signed` needs both parties' `agreement` signatures of that hash; a signed one never changes; only drafts are deleted (owner; bridge_app has no DELETE). bridge_app: SELECT, INSERT, UPDATE (terms, status, hash, updated_at) |
| `milestones` | id, agreement_id, engagement_id, seq, deliverable (≤ 500), amount_kes_minor (> 0), due_date, review_window_bd (1–60), state, timestamps | FK (agreement_id, engagement_id) → agreements; UNIQUE (agreement_id, seq), (id, engagement_id). Planned (insert, edit, delete; PLANNED) while the agreement is a draft, frozen once final; once it is signed and the engagement is `IN_IMPLEMENTATION` the sub-tracker steps only. bridge_app: SELECT, INSERT, DELETE, UPDATE (plan, state, updated_at) |
| `signatures` | id, engagement_id, document_kind, document_ref, document_sha256, signer_user_id, party, step_up_method, ip (inet), user_agent, signed_at | Append-only; UNIQUE (engagement_id, document_kind, document_ref, party). An agreement only in its final version, at its PDF hash, and never with IP terms `assignment` or `exclusive_licence` (AC-TRACK-10); a milestone confirmation names a milestone of the engagement; a `totp` step-up needs TOTP enrolled. bridge_app: SELECT, INSERT |
| `payment_records` | id, engagement_id, milestone_id (NULL = final payment), amount_kes_minor (> 0), method, reference (≤ 64, not blank), paid_on, recorded_by, recorded_at, confirmed_by, confirmed_at, confirmed_amount_kes_minor (≥ 0) | FK (milestone_id, engagement_id) → milestones. Recorded unconfirmed and not dated in the future (Nairobi date); changes once, the engagement's developer confirming with the amount received; nothing else changes; never deleted (trigger) or truncated. Table comment in the model and revision: no code path moves money. bridge_app: SELECT, INSERT, UPDATE (confirmed_by, confirmed_amount_kes_minor) |
| `test_clock` | singleton (bool PK, CHECK true), enabled, clock_offset (0–366 days), updated_by, updated_at | Tenancy SYSTEM. One row, inserted disabled by the migration. bridge_app: SELECT only |
| `users` (new column) | `demo_account` bool NOT NULL default false | D-37. bridge_app: SELECT (column); INSERT is column-scoped to every other column; no UPDATE |

**The chain** (`engagement_events_chain()`, BEFORE INSERT, SECURITY DEFINER). Locks the engagement's row (`FOR UPDATE`,
so appends to one engagement serialise until commit at any isolation level), reads the head and sets `seq`,
`prev_hash`, `created_at` (`app_clock_now()` under the lock) and `hash = sha256(prev_hash ‖ convert_to(canonical,
'UTF8'))`, replacing any values sent. Canonical text (`engagement_event_canonical`, internal; recomputed by
`bridge.engagements.chain`): `{"v":1,"id":…,"engagement_id":…,"seq":n,"created_at":µs,"actor_user_id":…|null,
"actor_role":…,"command":…,"from_state":…|null,"to_state":…,"end_reason":…|null,"stage_deadline_at":µs|null,
"payload":<payload::text>}` (keys in this order, no whitespace outside the payload, µs = integer microseconds since the
epoch, payload read back as `payload::text` as for the audit chain). Rules: the first event records the engagement as
inserted; every later one names the current state as `from_state` ("the engagement is in state X, not Y" otherwise,
409 for P5); none follows a terminal state; entering `IN_IMPLEMENTATION` needs a signed agreement, `PAYMENT_FINAL` both
parties' signatures of one acceptance certificate (same ref and hash), `CLOSED` from `PAYMENT_FINAL` a confirmed final
payment at the recorded amount (AC-TRACK-10, AC-TRACK-7). UPDATE, DELETE and TRUNCATE: refused by `block_mutation()`
for every role, and no grant.

**The projection.** `engagements_genesis()` (AFTER INSERT on `engagements`, SECURITY DEFINER) writes the genesis event
(seq 1, command `create`, the inserting party in their strongest role, or the system; payload origin and version id).
`engagement_events_project()` (AFTER INSERT, SECURITY DEFINER) writes `state`, `end_reason`, `stage_entered_at` (the
event's time when the state changes), `stage_deadline_at` (the event's when the state changes; a same-state event may
set a new one) and `ended_at` in the same statement. `engagements_guard()` (BEFORE INSERT OR UPDATE, SECURITY DEFINER)
sets `stage_entered_at`, `ended_at` and `lock_version = 0` on insert; on update it bumps `lock_version` (the ORM's
server-side version counter), keeps the parties, proposal, version and origin, and refuses a `state` or `end_reason`
that is not the latest event's, for every role (the owner too). Engagements that predate 0003 (fixtures) get a
genesis event by the system (command `import`) during the upgrade.

**Who writes** (bridge_app policies; the owner bypasses RLS but not the triggers):

- `engagements` INSERT: the developer, `SUBMITTED`, origin `tagged`, with their open delivered tag; or an organisation
  signatory, `ORG_INTEREST`, origin `org_agent_match` or `org_browse`; both only for the current registered version of
  a published, clear proposal and an E2 organisation that is neither suspended nor delisted; no end reason. UPDATE: the
  organisation's owner, admin or signatory (WITH CHECK); USING admits the developer too, so both parties can
  `SELECT … FOR UPDATE` for optimistic concurrency.
- Events: the caller as `developer` (the engagement's developer), in an organisation role they hold, or as `system`
  (no user) from a job bound to a party. Staff read, never write.
- Endorsements: each party its own side; `auto` by a job bound to that party.
- Agreements: the developer or the organisation's owner, admin or signatory, from `NDA_SIGNED` to
  `AGREEMENT_SIGNING`, as themselves (`created_by`). Milestones: the same editors plan; the developer moves
  PLANNED → IN_PROGRESS → SUBMITTED_FOR_REVIEW and CHANGES_REQUESTED → IN_PROGRESS; the organisation's owner, admin,
  signatory or reviewer decides ACCEPTED or CHANGES_REQUESTED.
- Signatures: the signer as themselves; the developer (D2 or above for an agreement) or an organisation signatory.
- Payment records: the organisation's owner, admin, signatory or finance member, from `IN_IMPLEMENTATION` to
  `PAYMENT_FINAL`; the confirmation by the engagement's developer.

**Functions.** `app_event_payload_is_valid(jsonb)` (IMMUTABLE CHECK helper; EXECUTE bridge_app): an object of at most
4 KB, keys `[a-z][a-z0-9_]{0,62}`, strings `[A-Za-z0-9_.:+-]{0,128}` (ids, codes, dates, times, amounts, hex digests;
no free text, address or URL fits: docs/spec/06 6.4 item 4, AC-IP-7). `app_clock_now()` (EXECUTE bridge_app): the
database clock plus the test clock's offset when enabled. `app_set_test_clock(interval)` (SECURITY DEFINER, EXECUTE
bridge_app): only where enabled, only forward, at most 366 days; returns the new now. Trigger functions and
`engagement_event_canonical` have no EXECUTE for any role. Every function pins `search_path`.

## Tests

`backend/tests/integration/engagements/` (helpers in `tracker.py`; fixtures written as the owner in a rolled-back
transaction, then `bridge_app` acting for each party):

- `test_chain.py`: the genesis and who may create an engagement; appends numbered, linked and timed by the database
  with the projection following (values sent are replaced); the Python verifier agrees with the database and finds a
  changed, removed or reordered event; the state changes only by an event (grants, guard for the owner too, stale
  `from_state`, reason codes, nothing after a terminal state); events, endorsements and signatures refuse UPDATE,
  DELETE and TRUNCATE; payloads hold ids and codes only; the ORM mapping (server-generated chain columns, the
  `lock_version` counter, `StaleDataError`); concurrent appends serialised on the row lock (own database, commits);
  the upgrade backfill of pre-0003 engagements and a second round trip (own database).
- `test_parties.py`: parties only (another developer, another organisation, a forged org context and no user read
  and write nothing; staff admin reads and writes nothing); actors in roles they hold; the main path to `CLOSED`
  with each legal step refused until its evidence exists; the assignment refusal; endorsements per stage entry;
  the milestone sub-tracker; payments recorded by the organisation and confirmed once; DECLINED and EXPIRED
  refused at the table without their reason (the replaced 0002 CHECK); `demo_account`; the test clock.
- Catalogs (`test_migrations.py`): the grant matrix and column UPDATEs, the function catalog (EXECUTE and SECURITY
  DEFINER), the trigger catalog, bridge_app's column INSERT on `users`, and the round trip, which now also asserts
  that 0003 leaves every object of 0002 exactly as it found it. `world.py`: one row of each tracker table per tenant
  for the generated RLS tests. `test_seed.py`: the clock is enabled outside production only.

Mutation proofs (revert-to-prove): each breaks one guard of the revision, runs the named test (red), restores the file
and reruns it (green); no mutated state was committed. Command (in `backend/`, the fixtures build a fresh database
from the revision file per run): `TEST_DATABASE_ADMIN_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/postgres
.venv/bin/python -m pytest -q -p no:cacheprovider tests/integration/engagements/<file>::<test>`.

| Proof | Guard broken | Test (red: 1 failed; restored: 1 passed) |
|---|---|---|
| M1 | `engagements_guard`: the state is the latest event's (`IF … THEN` → `IF false THEN`) | `test_chain.py::test_the_state_changes_only_by_appending_an_event` (the owner's direct UPDATE went through) |
| M2 | `engagement_events_chain`: `from_state` is the current state | `test_chain.py::test_concurrent_appends_to_one_engagement_are_serialised` (the stale append was accepted) |
| M3 | `IN_IMPLEMENTATION` needs a signed agreement | `test_parties.py::test_the_main_path_runs_to_closed_only_with_its_evidence` |
| M4 | `payment_records_guard`: confirmed once | `test_parties.py::test_a_payment_is_recorded_by_the_org_and_confirmed_once_by_the_developer` |
| M5 | signatures INSERT policy: D2 for an agreement | `test_parties.py::test_the_main_path_runs_to_closed_only_with_its_evidence` |
| M6 | events INSERT policy: a system event from a party | `test_parties.py::test_only_the_parties_read_or_write_an_engagement` (staff admin's system event was accepted) |
| M7 | `users` INSERT column-scoped (table-wide again) | `test_parties.py::test_demo_account_is_the_owners_to_set` |
| M8 | `app_set_test_clock`: only where enabled | `test_parties.py::test_the_test_clock_moves_forward_only_where_the_owner_enabled_it` |
| M9 | `engagement_events_no_update_delete` left out | `test_chain.py::test_events_endorsements_and_signatures_are_insert_only` |
| M10 | payload strings: any text | `test_chain.py::test_event_payloads_hold_ids_codes_dates_amounts_and_digests_only` |
| M11 | the canonical text leaves the payload out | `test_chain.py::test_events_extend_the_chain_and_move_the_projection` (the Python verifier disagreed) |
| M12 | `engagement_endorsements_guard`: only the current stage | `test_parties.py::test_endorsements_are_of_the_current_stage_once_per_party_and_entry` |
| M13 | `ck_engagements_end_reason_matches_state` recreated without `coalesce(…, false)` (ruling 1) | `test_parties.py::test_a_declined_or_expired_engagement_needs_its_reason` |

Result on the branch: full backend suite 1022 passed (951 before, 71 new), `ruff check`, `ruff format --check`, `mypy`
(strict) and `python -m bridge.openapi --check` clean, `alembic check` clean in the round trip. After ruling 1 (M13)
and the merge of the integration branch (schema v2, T2.6a, D1, T2.4; `3a81d5b`, no conflict, `uv sync --frozen`):
1728 passed, the same static checks clean, `check_traceability.py` 0 errors.

## Deviations from the brief (reported, for the orchestrator)

1. Money is `bigint` KES minor units (`amount_kes_minor`, `confirmed_amount_kes_minor`), not `numeric amount_kes`:
   the house rule (CLAUDE.md, docs/spec/08) wins over the brief's wording.
2. `engagement_events` has two more columns than listed, `end_reason` and `stage_deadline_at`: the projection needs
   them (the `engagements` CHECK wants the reason with DECLINED/EXPIRED; the deadline set by the state machine from
   `policy.yaml` must reach `engagements.stage_deadline_at` without an app-writable column, and both parties see it in
   the History tab). "kind/command" is `command`.
3. The endorsement key adds `stage_round` (the number of times the engagement entered the stage, set by the
   database): a stage entered twice (a disputed first contact goes back to stage 3, 6.9 stage 4) needs fresh
   endorsements, which (engagement, stage, party, milestone) alone would refuse.
4. `test_clock` has an `enabled` flag only the owner sets (the seed: an explicit dev, test or staging) on top of the app-side
   APP_ENV gate, so a production database refuses to move the clock whatever calls the function. The offset column
   is `clock_offset` (OFFSET is a reserved word); the key is a boolean singleton, not a UUIDv7.
5. The database also enforces the main path's legal steps (the preconditions and predecessor sets), D2 for a developer's
   agreement signature, the internal e-signature's refusal of assignment and exclusive licence, the initial states and
   E2 for new engagements, and the payload shape. These restate AC-TRACK-10, AC-TRACK-7, 6.8 ("Express interest
   requires E2") and 6.4 item 4; the state machine remains the only transition table.
6. bridge_app's INSERT on `users` became column-scoped (every column but `demo_account`) so the app cannot insert a
   demo account either; it is otherwise unchanged.

## Findings on earlier revisions

- Revision 0002's `ck_engagements_end_reason_matches_state` let a DECLINED or EXPIRED engagement without a reason
  through (`NULL IN (...)` is NULL, which a CHECK accepts). Fixed in 0003 (ruling 1 below): the constraint is replaced
  by the NULL-safe `coalesce(<same expression>, false)` (validated, so an existing row without its reason stops the
  upgrade), and the downgrade restores 0002's exactly (the round trip compares the constraint definitions). The events'
  CHECK is NULL-safe too. Tested at the table, for every role:
  `test_parties.py::test_a_declined_or_expired_engagement_needs_its_reason` (proof M13).
- bridge_app may still insert `users.staff_role`, `status` and `subject_salt` (table-wide INSERT since 0001, kept
  column for column here). Follow-up below (ruling 2).

## Orchestrator rulings (2026-09-29, on the first report)

1. Tighten the 0002 end-reason CHECK inside 0003, the downgrade restoring the old one, with a table-level test: done
   (above).
2. Narrowing bridge_app's INSERT on `users.staff_role`, `status` and `subject_salt`: a follow-up, not changed now.
3. System events (and `auto` endorsements) written by a job bound to a party: accepted for the prototype; recorded
   as a residual in THREAT_MODEL §2 (the "party acts in a role they do not hold" row).
4. Deadline values stay the state machine's (P5).

## Review round 1 (reviewer and security-reviewer on `3191af5`; fixed in revision 0003 in place)

Each finding got a failing test first (`348f568`, red on `3191af5`: 10 tests), then the fix (`60c2a17`, `4bf3cc9`);
the mutation proofs below show each test catches its guard. After the fixes: full backend suite 1743 passed; `ruff
check`, `ruff format --check`, `mypy` (strict), `python -m bridge.openapi --check` and `check_traceability.py` clean.

| Finding | Fix | Tests |
|---|---|---|
| MAJOR 1: SECURITY DEFINER BEFORE INSERT triggers ran before RLS WITH CHECK and read, locked (`FOR UPDATE`) and reported another party's engagement (state, stage, agreement status, membership, TOTP) | `tracker_engagement_visible()` (SECURITY INVOKER) fires first on INSERT on all six tracker tables (`<table>_0_visible`; triggers fire in name order): one `insufficient_privilege` refusal, "no engagement of the caller's with that id", for a missing or invisible engagement. The checks that read other users moved to AFTER triggers (after RLS): `engagements_members()` (contact membership, and MINOR 7), `engagement_endorsements_totp()`, `signatures_totp()`. `milestones_guard` reads an agreement only as its own engagement's | `test_parties.py::test_an_outsider_learns_nothing_from_a_refused_write` (12 distinct refusals before, 1 after), `test_serialisation.py::test_an_outsider_takes_no_lock_on_another_partys_engagement` (lock timeout before), `test_migrations.py::test_the_visibility_trigger_fires_first_on_every_tracker_table` |
| MAJOR 2: milestone writes and finalisation were not serialised | `milestones_guard` reads the agreement `FOR SHARE` on INSERT, UPDATE and DELETE; the finalising UPDATE holds the row's update lock, so each waits for the other | `test_serialisation.py::test_a_milestone_planned_during_finalisation_waits_and_is_refused`, `::test_finalising_while_the_last_milestone_is_deleted_waits_and_fails` |
| MAJOR 3: the seed enabled the clock on the settings default (`dev`) | `test_clock_enabled(settings)`: `"app_env" in settings.model_fields_set` and dev, test or staging, else disabled (as the directory seed) | `test_seed.py::test_the_test_clock_stays_disabled_on_the_settings_default` |
| MAJOR 4: UNDER_REVIEW → DELIVERED → CLOSED skipped every evidence gate | `engagement_main_path_predecessors(state)` (internal): each main-path state only from its legal predecessors; ON_HOLD, DISPUTED and INFO_REQUESTED resume only to the state they were entered from; DELIVERED, SIGN_OFF and PAYMENT_FINAL need a signed agreement too; DISPUTED → CLOSED (the mediator's outcome) is refused to the parties by the events INSERT policy | `test_parties.py::test_the_main_path_cannot_be_skipped` |
| MINOR 5: viewers could write system events and `auto` endorsements | both need the developer or a member with owner, admin, signatory, reviewer or finance | `::test_viewers_write_no_system_events_or_automatic_endorsements` |
| MINOR 6: tracker writes after the end | `e.ended_at IS NULL` in the INSERT checks of endorsements, agreements, milestones and signatures and the UPDATE checks of agreements and milestones; the endorsement guard refuses a terminal stage | `::test_nothing_is_written_to_an_engagement_that_ended` |
| MINOR 7: one person on both sides | the tagged INSERT policy refuses an organisation the developer belongs to, and `engagements_members()` refuses any engagement whose developer is an active member (for every role); a signed agreement and PAYMENT_FINAL's certificate need two distinct signers | `::test_the_parties_are_two_people`, and the certificate case in `::test_the_main_path_runs_to_closed_only_with_its_evidence` |

The RLS world's engagement moved to a separate developer (`pitcher-<tenant>`, with a proposal of their own), because a
tenant's owner can no longer be the developer of an engagement with their own organisation; the tracker rows stay the
tenant's through its organisation, so the generated RLS tests now exercise the member path.

| Proof | Guard broken | Test (red → restored green) |
|---|---|---|
| M14 | no `<table>_0_visible` trigger | `test_an_outsider_learns_nothing_from_a_refused_write`, `test_an_outsider_takes_no_lock_on_another_partys_engagement` |
| M15 | `milestones_guard` without `FOR SHARE` | both `test_serialisation.py` race tests |
| M16 | predecessor check skipped | `test_the_main_path_cannot_be_skipped` |
| M17 | distinct signers not required | `test_the_parties_are_two_people`, `test_the_main_path_runs_to_closed_only_with_its_evidence` |
| M18 | the clock enables on the settings default | `test_seed.py::test_the_test_clock_stays_disabled_on_the_settings_default` |

Follow-ups recorded from the review (not built):

- A test that the endorsement guard's `FOR UPDATE` serialises an endorsement with a concurrent append.
- A test of the contact-member rule on UPDATE (a non-member named as contact) through the API path.
- A test of the payment state window (recording before `IN_IMPLEMENTATION` and after `PAYMENT_FINAL` refused).
- A test of `app.org_id` narrowing on every tracker table (a member of two organisations scoped to the other one).
- A test that the owner cannot DELETE a final agreement (the guard refuses it; bridge_app has no DELETE).
- Milestone endorsements are keyed with `stage_round` although milestones are endorsed only in IN_IMPLEMENTATION;
  a milestone re-endorsed after a resume would need a round of its own. Revisit with the milestone payment flow.
- Payments during DISPUTED or ON_HOLD: the INSERT policy's state window does not include them; P5 decides whether a
  payment can be recorded while paused.
- A passkey step-up cannot be verified by the database (no passkey table yet): P5 sets `step_up_method` only from
  the step-up it verified in the request.
- Commit sizes: the revision commits exceed the ~300-line guidance (one revision file); later rounds keep to it where
  a file allows.

## Notes for P5 and P9 (operating rules)

- Append an event instead of writing the state; send `from_state` as the state the command was checked against; map
  "the engagement is in state …" to 409. Refresh the `Engagement` after an append.
- Leave the database's columns out (`seq`, `prev_hash`, `hash`, all evidence times, `stage_round`,
  `stage_entered_at`, `ended_at`, `lock_version`, `confirmed_at`); read them back.
- Keep free text and personal data out of payloads: a decline's `OTHER` text and an internal start date's attestation
  text go to a mutable store with their salted digest in the payload.
- Close the tag when its engagement ends (`app_close_tag`); the projection does not.
- System events and `auto` endorsements come from a job bound (`bind_tenant`) to the party it acts for, never to a
  viewer.
- Map the tracker's one refusal for an engagement the caller cannot see ("no engagement of the caller's with that
  id", SQLSTATE 42501) to 404, like any cross-tenant reference.
- The test-clock router calls `app_set_test_clock`, stays out of the production image and, in staging, is staff-gated
  (review P1, MAJOR 3: staging has real-looking data and more than one user); read "now" from `app_clock_now()` in the
  API and the worker so deadlines, reminders and evidence times agree. The seed enables the clock only when `APP_ENV`
  is set explicitly (backend/.env or the environment) to dev, test or staging.
- The transition table in `state_machine.py` must stay within the database's backstop: each main-path state from the
  predecessors in `engagement_main_path_predecessors`, a side branch resuming to the state it left, and no
  DISPUTED -> CLOSED from a party (the mediator's outcome, after the prototype).
- The demo seed (P9) sets `users.demo_account` and D2 for the demo developers as the owner; demo engagements are best
  replayed through events so their History tabs are complete.

## Follow-ups (MINOR, not built)

- Endorsements are not in the hash chain themselves: P5 appends an event for each endorsement so the History tab and
  the chain carry it (AC-TRACK-3); the database does not require the pairing.
- A dual-endorsement stage is not blocked from being left without both endorsements (the state machine's rule); the
  legal steps above are.
- `signatures.ip` and `user_agent` are personal data kept with the evidence; their retention belongs to the Phase 8
  retention schedule.
- "Signed outside the platform" (assignment, exclusive licence) needs a new `step_up_method` value and path later.
- Narrow bridge_app's INSERT on `users` to leave out `staff_role`, `status` and `subject_salt` (ruling 2): an app bug
  could create a staff user or choose a user's salt (and so make their digests guessable). One grant change in a later
  revision once no branch's fixtures insert those columns as bridge_app (grep `INSERT INTO users` under
  `backend/tests` and `backend/src` first).
- System events and `auto` endorsements: the database cannot tell a job bound to a party from that party's request,
  so a party-bound job (or a bug in the party's request path) can write a system event on that party's engagements
  (ruling 3, accepted for the prototype). A separate login role for jobs (D-32) would let the policy tell them apart.
- The database trusts the state machine for deadline values (`stage_deadline_at` on an event, from `policy.yaml` on
  the business-day calendar): a same-state event can move a deadline. Every change is an event, so it is visible and
  verifiable in the History tab, but a policy check of the value belongs to P5.
