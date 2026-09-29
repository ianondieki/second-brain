# REQ-REPO-01

- Task: T2.1 (schema v2), T2.5 (Tier-2 access) (`docs/platform/PLAN.md` Phase 2)
- Agent: db-migrations (T2.1); impl-backend (T2.5 backend), impl-frontend (T2.5 screens); security-reviewer (Fable) on both
- Files owned: T2.1: `backend/alembic/versions/*_0002_*.py`, the new `models.py` files named below, `bridge/models/{base,enums,all}.py`, `infra/postgres/{roles,prepare_db}.sql`, `backend/tests/integration/{world,test_rls,test_migrations,test_privileges}.py`, `backend/seed/legal_templates.yaml` and its seed step. T2.5: `bridge/proposals/{access,grants,render,views}.py`, `bridge/legal/`, Tier-2 routes in `bridge/proposals/router.py`.
- Depends on: Phase 1. T2.5 after T2.3, T2.4 and the T2.6 claim/MET tables.

## Scope

Tier 0 draft (owner only), Tier 1 teaser (every signed-in user and scouts), Tier 2 in `proposal_confidential` (per-proposal envelope key) released only by `can_view_tier2(viewer, version)` in `bridge/proposals/access.py` over every condition in `docs/spec/06` 6.1. Owner attribution and per-viewer marks on every Tier-2 render; access log; "Who has seen this"; step-up and an email notice on policy changes, manual grants and raw-download enablement.

## T2.1 schema v2 design (binding for the revision; deviations need the orchestrator)

One revision `0002` (Revises `0001`), additive only. UUIDv7 PKs, `timestamptz`, `bigint` KES minor units, `embed_model`/`embed_version` beside every vector. ORM models live in the module that owns the feature (`bridge/proposals/models.py`, `bridge/problems/models.py`, `bridge/provenance/models.py`, `bridge/legal/models.py`, `bridge/engagements/models.py`, `bridge/llm/models.py`, `bridge/directory/models.py`, `bridge/profiles/models.py`, `bridge/admin/models.py`); `alembic check` must be clean.

**Tenancy classes.** Add to `bridge.models.base.Tenancy`: `PUBLISHED` (owner-scoped content: the owner reads and writes it; every signed-in user reads rows that are published, not hidden and clear of moderation holds; staff `admin|moderator` read everything) and `STAFF` (platform staff tables: `app_is_staff()` reads and updates; the app inserts). New SECURITY DEFINER helper `app_is_staff(p_roles staff_role[] DEFAULT NULL)` (reads `users.staff_role` for `app_user_id()`; pinned `search_path` like every 0001 function). Extend the metadata-driven RLS tests to both classes.

**New database roles** (`infra/postgres/roles.sql`, NOLOGIN, NOBYPASSRLS): `tier2_reader`, `provenance_worker`, `tier2_embed_worker`, `tier2_moderation`, `dsr_exporter`. `bridge_app` gets membership `WITH INHERIT FALSE, SET TRUE` in each (it can `SET LOCAL ROLE` after the application check but does not inherit their privileges, so `has_table_privilege('bridge_app', 'proposal_confidential', 'SELECT')` is false). `prepare_db.sql` grants them schema USAGE. Code switches with a helper (`bridge.db.as_role(session, role)`: `SET LOCAL ROLE`, then `RESET ROLE` before audit writes).

**Tables.**

| Table | Tenancy | Key columns / rules |
|---|---|---|
| `legal_templates` | GLOBAL | kind (`master_enterprise_terms`, `evaluation_nda`, `mutual_nda`, `tos`, `aup`, …), version, sha256, body, `is_placeholder`; unique(kind, version). Seeded with `DRAFT — NOT LEGAL ADVICE — MUST BE REVIEWED BY A KENYAN ADVOCATE BEFORE USE` + `[[LEGAL-PLACEHOLDER:<id>]]` bodies only |
| `nda_templates` | GLOBAL | kind (`evaluation`, `mutual`), version, `legal_template_id`, sha256 |
| `provenance_keys` | GLOBAL | key_id, algorithm `ed25519`, public_key, created_at, retired_at (served at `/.well-known/provenance-keys.json`) |
| `problems` | PUBLISHED | source (`research_agent`, `org_brief`, `developer`), niche_id, country, county_code, title ≤90, statement, affected_group, status (`candidate`, `pending_review`, `published`, `rejected`, `archived`), created_by (user), org_id (briefs), ai_generated, confidence, cluster_id, moderator_id, moderation_state, embedding + embed cols, published_at. `candidate` never readable by non-staff |
| `problem_sources` | PUBLISHED (via problem) | url, publisher, source_type, published_date, retrieved_at, quote |
| `problem_briefs` | ORG + public read | problem_id PK, org_id, visibility (`public`, `invited`), budget_band, deadline, status; public published briefs readable by every signed-in user, invited ones by org members and `brief_invitations` users |
| `brief_invitations` | ORG_OR_USER | brief_id, user_id |
| `proposals` | PUBLISHED | owner_id, status (`draft`, `published`, `hidden`, `archived`), moderation_state (`clear`, `held`, `rejected`), current_version_id, draft_version_id, denormalised current Tier-1 (title, niche_id, country, county_code, maturity `idea|prototype|mvp|live`, ask `sale|licence|co_build|pilot|hire`), `search_tsv` (generated, `simple` config, GIN), teaser_embedding vector(1024) (HNSW) + embed cols, tier2_policy (`auto_tagged` default, `manual`, `niche_e2`), raw_download_enabled, published_at, hidden_at. Moderation state is changed only by staff (definer function) |
| `proposal_versions` | PUBLISHED (via proposal) | proposal_id, version_no, status (`draft`, `registered`), Tier-1 snapshot (title, niche_id, county_code, maturity, ask, problem_statement, impact_claims, summary ≤150 words), owner_handle, prev_version_hash, content_hash, cert_id (unique, short random), manifest_version, registered_at. Trigger: UPDATE/DELETE refused once `status = 'registered'` (AC-IP-2) |
| `proposal_problems` | PUBLISHED (via proposal) | (proposal_version_id, problem_id); ≥1 enforced at publish |
| `proposal_confidential` | Tier 2 (RLS; **no bridge_app privilege at all**) | version_id PK, proposal_id, owner_id, ciphertext, nonce, wrapped_dek, kms_key_id, manifest_ciphertext, timestamps. Grants: `tier2_reader` SELECT/INSERT/UPDATE (policies: owner rows while the version is a draft for writes; SELECT for the owner or a live grant via definer `app_tier2_granted(proposal_id)`), `provenance_worker` SELECT + UPDATE(manifest_ciphertext), `tier2_embed_worker` SELECT, `tier2_moderation` SELECT (staff context), `dsr_exporter` SELECT (subject rows). Trigger refuses changes after registration |
| `proposal_confidential_embeddings` | Tier 2 | (version_id, embed_model, embed_version) PK, full_embedding vector(1024); SELECT **only** `tier2_moderation`; INSERT `tier2_embed_worker` |
| `proposal_attachments` | USER (owner_id) | proposal_id, version_id, sha256, size_bytes, content_type, av_status (`pending_upload`, `pending_scan`, `clean`, `infected`, `failed`), rerendered. Object keys and filenames live only inside the encrypted Tier-2 document |
| `proposal_lsh_bands` | SYSTEM | (proposal_id, band, bucket) over Tier-1 text only (originality, T2.9) |
| `originality_checks` | USER | user_id, created_at, band (daily cap ≤10) |
| `provenance_records` | SYSTEM (bridge_app SELECT; provenance_worker INSERT and fill-once UPDATE of TSA columns) | version_id unique, cert_id unique, content_hash, signature, key_id, status (`hashed`, `signed`, `timestamped`), tsa_token, tsa_time, tsa_serial, tsa_url, ots_proof (R2), evidence_s3_key. Trigger: no UPDATE except filling NULL TSA columns; no DELETE |
| `chain_anchors` | SYSTEM | chain_id, seq, event_hash, tsa_token, tsa_time, tsa_serial (hourly anchor; `audit_reader` SELECT, `provenance_worker` INSERT) |
| `transparency_roots` | SYSTEM | day PK, merkle_root, signature, key_id (nightly; public read) |
| `attestations` | USER, append-only | user_id, version_id, created_it, not_owned_by_employer_or_client, no_third_party_confidential, text_version, text_sha256 |
| `tags` | ORG_OR_USER | proposal_id, org_id, developer_id, status (`held_unclaimed`, `held_pending_verification`, `delivered`, `withdrawn`, `expired`, `released`), sla_due_at. Partial unique (developer_id, org_id) over open statuses. Visibility: the developer; the org's members only for `delivered`; E1 orgs see a count through definer `app_held_tag_count(org_id)` |
| `engagements` (skeleton) | ORG_OR_USER | proposal_id, org_id, developer_id, version_id, origin (`tagged`, `org_agent_match`, `org_browse`), state (every stage and side-branch state of `docs/spec/06` 6.9), end_reason (6.9 codes), unique(proposal_id, org_id). No transitions in Phase 2 (fixtures only) |
| `disclosure_grants` | ORG_OR_USER | proposal_id, org_id, owner_id, tier (2, 3), status (`requested`, `active`, `revoked`, `denied`), source (`auto_tagged`, `manual`, `niche_e2`, `org_interest`), counts_as_unlock, billing_month, requested_by, granted_by, granted_at, revoked_at, revoked_by. Visible to the owner and the grantee org's members |
| `nda_acceptances` | ORG_OR_USER, append-only | user_id, org_id, proposal_id, nda_template_id, template_sha256, logging_notice_version, accepted_at |
| `legal_acceptances` | ORG, append-only | org_id, user_id, legal_template_id, template_sha256, accepted_at (Master Enterprise Terms by the Signatory) |
| `document_views` | ORG_OR_USER | id = `view_id`, proposal_id, version_id, owner_id, viewer_user_id, org_id, nda_acceptance_id, nda_template_version, render_kind (`html`, `pdf`, `attachment`), started_at, duration_bucket, fingerprint_seed. Readable by the owner and the viewer |
| `signal_events` | SYSTEM | item_id, kind, actor_hash, org_hash, ts. bridge_app INSERT only; `aggregate_worker` SELECT only |
| `moderation_cases` | STAFF | subject_type, subject_id, reasons[], source (`prescreen`, `regex`, `report`, `claim_dispute`, `tier2_similarity`), status (`open`, `held`, `approved`, `rejected`, `escalated`), classifier (jsonb, Tier-1 only), assigned_to, decided_by, decided_at |
| `org_claims` | ORG_OR_USER + staff | org_id, claimant_user_id, domain, email_address, level (`e1`, `e2`), status (`otp_sent`, `dns_pending`, `pending_review`, `approved`, `rejected`, `disputed`, `withdrawn`), otp_hash, otp_expires_at, otp_attempts, dns_token, dns_verified_at, E2 facts (registration_no, cr12_date, kra_pin, sector_register, public_entity_requested, document keys), reviewed_by, decided_at, decision_reason. Approval runs through staff/definer functions that set `organizations.verification` and create the membership |
| `directory_invitations` | STAFF | org_id, to_address, status (`proposed`, `approved`, `sent`, `refused`), reason, proposed_by, approved_by, sent_at |
| `phone_verifications` | USER | user_id, phone_e164, otp_hash, attempts, expires_at, verified_at |
| `kyc_reviews` | USER + staff | user_id, status (`submitted`, `approved`, `rejected`), reference, verified_legal_name, id_type, id_last4, is_adult, decided_by, decided_at, purge_due_at, images_purged_at. Never images or image keys in a column that logs or audit events read |
| `llm_calls` | ORG_OR_USER + system rows + staff read | org_id, user_id, task, purpose, model, input/output/cache tokens, cost_usd numeric(12,6), latency_ms, status, stop_reason, trace_id, inputs (jsonb, sanitised; retained 30 days) |

**Column additions to Phase 1 tables.** `organizations`: official_domains citext[], source_url, source_retrieved_on, county_code, delisted_at, invitations_opted_out_at, e2_verified_at, reverify_due_on. New SELECT policy: every signed-in user reads listed organisations (`verification IN ('unclaimed','e1','e2') AND delisted_at IS NULL`); same for `org_niches` of listed organisations. `users`: subject_salt bytea (per-subject salt for owner refs and audit digests).

**Privileged changes through definer functions** (checked in SQL, pinned `search_path`, EXECUTE granted explicitly): staff moderation decisions, claim approval (E1/E2: set verification, verified_domain, create the claimant's membership), D1 confirmation (`app_confirm_phone_otp`, compares the stored hash), D2 decisions (`app_is_staff('{admin}')`). The app role keeps no UPDATE on `verification_level`, `verification`, `moderation_state`.

**Tests the revision ships** (AC-SEC-1/b, AC-REPO-3 privileges half, AC-IP-2 manifest half): the RLS test covers every new tenant table (org, user, org_or_user, published drafts, staff) with fixtures in `world.py`, developer A reads 0 of B's drafts, versions or Tier-2 rows, an org without a grant reads 0 `proposal_confidential` rows even as `tier2_reader`, `aggregate_worker` reads 0 rows of every tenant table and only `signal_events`; `test_privileges.py` asserts with `has_table_privilege` that exactly `tier2_reader`, `provenance_worker`, `tier2_embed_worker`, `tier2_moderation`, `dsr_exporter` have SELECT on `proposal_confidential` and only `tier2_moderation` on `proposal_confidential_embeddings`; the grant matrix test lists every new table; registered versions and provenance records refuse UPDATE/DELETE; migration up/down/up without drift.

### Refinements (approved by the orchestrator 2026-09-28)

Deviations from the design above, all additive and inside revision 0002; the migration docstring states the same rules.

First review round:

- `tags.closed_at`: a tag is open while it is NULL; the partial unique index is (developer_id, org_id) WHERE `closed_at IS NULL`. Withdrawn, expired and released tags are closed by trigger (`tags_guard`), `app_close_tag(tag)` closes one otherwise (the developer, or a member of the organisation for a delivered tag), nothing reopens a tag; `closed_at` is not in bridge_app's UPDATE grant.
- `org_claims.otp_reissues` and `app_reissue_claim_otp(claim, otp_hash, expires_at)`: a new code for an open claim (32-byte digest, expiry within the hour), at most 5 reissues, then manual review; `otp_attempts` is cumulative (5 per code issued); one open claim and one new claim per 24 hours per claimant and organisation (`org_claims_guard`).
- `app_audit_chain_heads()`: the head of every audit chain for the hourly anchor; EXECUTE for `provenance_worker` only.
- `organizations.suspended_at`: the "not suspended" condition of `can_view_tier2`.
- `proposal_confidential.manifest_nonce`: the manifest is encrypted under the proposal key with its own nonce.
- `org_claims.otp_verified_at`: set only by `app_confirm_claim_otp`.
- `moderation_cases.reporter_id`: who reported (a user may report, never read the queue).
- `brief_invitations.org_id`: the brief's organisation, so the two brief policies never read each other recursively.
- `app_tier2_granted(proposal_id, version_id)`: the second argument keeps drafts out (only a registered version is ever granted).
- `proposals` also denormalises the current `problem_statement`, `impact_claims` and `summary` (the generated `search_tsv` reads its own row only).

Second review round (reviewer and security-reviewer findings, D1 review):

- Master Enterprise Terms: besides the organisation's owner, admin or signatory, only the claimant of their own open E2 claim with a verified email code, on an unclaimed or E1 organisation, may record an acceptance, and only of the Master Enterprise Terms. `app_current_legal_template(kind)` (the most recently created version; EXECUTE bridge_app). `app_decide_claim` approves E2 only with the current version accepted by that claimant; `app_tier2_granted` counts only the current version accepted by the approved E2 claimant or an active signatory. Publishing a new version therefore requires re-acceptance.
- `app_tier2_granted` requires membership on the verified domain: the organisation has a `verified_domain` and the viewer's email address is at exactly that domain (the T2.5 predicate must mirror it).
- `app_decide_claim` approves any claim (E1 or E2) only with the domain proven: `otp_verified_at` and `dns_verified_at`, or, for E2, a claimant who is an active owner, admin or signatory of an organisation already E1 on the same verified domain.
- Registration: `proposal_versions_guard` sets `registered_at := now()` when a draft is registered (any value sent is replaced) and refuses registration columns on insert and on drafts. bridge_app loses UPDATE on `registered_at`, `content_hash`, `prev_version_hash`, `manifest_version` (keeps `cert_id`). `provenance_worker` gets SELECT and UPDATE (`content_hash`, `prev_version_hash`, `manifest_version`, `updated_at`) on `proposal_versions`, RLS: registered versions of the bound owner. `app_owns_version(version)` (definer, EXECUTE `provenance_worker`). `ProposalVersion` maps `registered_at` with `server_onupdate=FetchedValue()` and `eager_defaults`.
- `provenance_records` gets RLS under a new tenancy class `EVIDENCE`: bridge_app reads every record (`/verify` is anonymous); `provenance_worker` reads, inserts and updates only the records of its bound owner's versions.
- `proposal_attachments_guard`: an attachment of a registered version is never deleted and changes only `av_status`, `rerendered`, `updated_at`.
- Column-level SELECT for bridge_app: every column except `org_claims.otp_hash`, `phone_verifications.otp_hash`, `users.subject_salt` and `llm_calls.inputs`. The ORM maps the OTP digests and `inputs` deferred with raiseload and leaves `subject_salt` unmapped (`exclude_properties`). `app_subject_digest(user_id, data)` = SHA-256(subject_salt ‖ data) (definer; EXECUTE bridge_app, provenance_worker); owner refs are `app_subject_digest(user_id, uuid_send(user_id))`. `app_llm_call_inputs(call)` (definer, staff admin only; EXECUTE bridge_app).
- `app_add_niche(slug, name_en, parent_slug, isic_code)` for the admin route of T2.6a (definer, staff admin only, EXECUTE bridge_app; the parent must be an active top-level niche; slugs are new, lower-case and hyphenated).
- D1: `app_confirm_phone_otp` matches only while the caller's developer profile is D0 (the attempt is still counted); `phone_verifications_guard` sets `expires_at := now() + 10 minutes` on insert (column default the same), so leave `expires_at` out and read it back.

Third review round (reviewer and security-reviewer findings on the second round):

- An upheld dispute transfers the organisation: staff approval of a disputed claim (`app_decide_claim`) rejects every earlier approved claim of another claimant (`decision_reason` names the superseding claim) and removes those claimants' memberships in the same transaction (completed in the fourth round: the new claimant becomes the only owner and admin). `app_staff_remove_membership(membership, reason)` (definer, staff admin, reason required for the caller's audit event; EXECUTE bridge_app) corrects a roster.
- DNS proof: `dns_verified_at` is set only by `app_mark_claim_dns_verified(claim)` (definer; the claimant's own open claim that carries a token; EXECUTE bridge_app), which the app's DNS-check code calls once it has resolved the claim's TXT record. `dns_token` (written with the claim) and `dns_verified_at` are write-once for every role (`org_claims_dns_guard`) and not in bridge_app's UPDATE grant. The lookup is app-side and the database trusts the app's resolution: T2.6b resolves only the claim's own domain, compares the token exactly and uses a validating resolver.
- `app_subject_digest(user_id, data)` is bound to the caller: bridge_app computes only `app_user_id()`'s digest; staff (admin or moderator since the fourth round) and the registration job compute any user's. The job is recognised by `current_setting('role') = 'provenance_worker'` (inside a SECURITY DEFINER function `current_user` is the owner and `session_user` the login role; the `role` setting keeps the caller's membership-checked `SET ROLE`), so compute other users' digests only inside `as_role(session, "provenance_worker")` or in a staff context.
- `app_tier2_granted` also requires the viewer's `users.email_verified_at IS NOT NULL`; the T2.5 predicate `can_view_tier2` must mirror it.
- `moderation_cases`: bridge_app inserts only a user's report (`source = 'report'`, `reporter_id = app_user_id()`, `status = 'open'`, no `classifier`). The system sources file through `app_open_moderation_case(subject_type, subject_id, reasons, source, classifier)` (definer; returns the case id): `prescreen` and `regex` on a `proposal` or `problem` by whoever may write it or staff admin|moderator; `claim_dispute` on a disputed `org_claim` by its claimant or staff admin; `tier2_similarity` on a `proposal` in a staff admin|moderator context only. `classifier` is Tier-1 output only, a JSON object of at most 8 KB; 1 to 20 non-blank reasons of at most 200 characters. One unresolved case (`open`, `held`, `escalated`) per subject and source: a new call adds its new reasons (at most 50) and returns that case. EXECUTE bridge_app and `tier2_moderation` (the similarity job reads embeddings as `tier2_moderation`, which reads only in a staff context, and files without switching back). A subject without an owner (a research-agent candidate problem) needs a staff context.
- `provenance_records`: `provenance_worker` inserts a record only for a registered version it owns (`app_owns_version`).
- Tested (no schema change): the E1 shortcut of `app_decide_claim` holds only when the claimed domain equals the organisation's verified domain (`test_staff_approval_needs_the_claimed_domain_proven`, revert-to-prove).

Fourth review round (reviewer and security-reviewer findings on the third round; the transfer rule is the orchestrator's decision):

- Transfer on an upheld dispute: the new claimant becomes the organisation's only owner and admin, in the same transaction. The superseded claimants' memberships are removed with roles `{viewer}` (nobody reactivates them with power); every other active membership loses `owner` and `admin` and keeps its other roles (`{viewer}` when none is left); every pending invitation (`accepted_at` and `revoked_at` NULL) issued by anyone but the new claimant, or carrying `owner` or `admin`, gets `revoked_at`. The new claimant re-promotes people afterwards. Only approving a `disputed` claim transfers (negative test: the E2 upgrade of an E1 organisation by its signatory changes no other claim or membership).
- `proposal_versions.owner_handle`: set by `proposal_versions_guard` when a version is registered, to the `developer_profiles.handle` of the proposal's owner (any value sent is replaced; registration is refused when the owner has no developer profile); refused on insert and on drafts; not in bridge_app's UPDATE grant. The ORM maps it with `server_onupdate=FetchedValue()`, so the registering flush reads it back.
- Evidence times are the database's: `evidence_time_guard` (BEFORE INSERT) sets `attestations.created_at`, `legal_acceptances.accepted_at`, `nda_acceptances.accepted_at` and `document_views.started_at` to `now()` whatever is sent (leave them out and read them back).
- `document_views` INSERT: `app_tier2_granted(proposal_id, version_id, org_id)`, so a view is logged only by a viewer the grant held by that organisation lets read that registered version; the named NDA acceptance must be the viewer's for that proposal and organisation. `app_tier2_granted` takes the organisation as an optional third argument (`p_org uuid DEFAULT NULL`). The owner's own renders are not logged (`org_id` is the viewer's organisation). T2.5 writes the view as the viewer in the render request.
- `app_subject_digest`: staff means `app_is_staff('{admin,moderator}')`; support is refused. The caller binding stops a query bug or an ORM load, not SQL the app role itself runs: bridge_app may `SET ROLE provenance_worker` (membership WITH SET), so an injected expression can switch first. A separate LOGIN role for the worker is D-32 (with the digest formula).
- `proposal_lsh_bands`: RLS, tenancy PUBLISHED. A bucket is readable exactly when its proposal is (the owner; every signed-in user for a published, clear proposal; staff), which is the spec's "other owners' Tier-1 teasers only" (6.1, AC-PROP-4); only the proposal's owner inserts or deletes buckets. (The finding proposed SELECT `true`; following the proposal's visibility is narrower and keeps drafts, held and hidden teasers out of the comparison.) T2.9 compares against the buckets it can read.
- `llm_calls`: CHECK `cost_usd BETWEEN 0 AND 100` and no negative token count or latency (the global daily cap sums every row).
- `moderation_cases`: CHECK `app_reasons_are_valid(reasons, 50)` (1 to 50 non-blank reasons of at most 200 characters; an IMMUTABLE helper created before the tables, EXECUTE bridge_app), for a report and a staff edit alike. `directory_invitations`: `to_address` at most 254 characters with one `@` and no spaces; `reason` NULL or non-blank and at most 500 characters. Rate limits stay app-side (PLAN T8.4, the T2.6b card).
- Anchors and roots: `chain_anchors_guard` (SECURITY DEFINER) requires an anchor's `(chain_id, seq, event_hash)` to match an `audit_events` row and `tsa_time <= clock_timestamp() + 1 minute` (the TSA's clock is not ours); `transparency_roots_guard` requires `day` before today's Africa/Nairobi date (the nightly job closes the Nairobi day that just ended, `bridge.jobs.audit.closing_day`).
- `provenance_records`: composite foreign key `(version_id, cert_id)` to `proposal_versions (id, cert_id)` (new UNIQUE `(id, cert_id)`), so a record carries its version's certificate id; its `content_hash` equals the version's once both are set, whichever is written first (`provenance_records_hash_guard` on insert, `proposal_versions_guard` on filling the version's hash).
- `app_mark_kyc_images_purged`: only the `kyc.purge` job (no user bound) or staff admin; a signed-in request is refused. bridge_app can clear `app.user_id`, so this stops a request-path bug, not a compromised app role.
- `org_claims_guard` sets `created_at := now()` on insert, so the 24-hour cooldown cannot be escaped by a backdated claim.
- `app_tier2_granted` counts only the current Evaluation NDA: `app_current_nda_template('evaluation')`, the most recently created `nda_templates` row of that kind (as `app_current_legal_template`; EXECUTE bridge_app). A new NDA version therefore requires re-acceptance; the T2.5 predicate must mirror it.
- Tested (no schema change): a user's report naming an assignee, a decider or a decision time is refused (`test_users_only_report_and_system_sources_file_through_the_function`, revert-to-prove).

Schema follow-ups requested by T2.4 (`docs/platform/tasks/REQ-PROV-01.md`, "Schema follow-ups"):

- `app_audit_chain_heads()` also returns each head's `occurred_at`; `app_unanchored_chain_heads()` (definer, EXECUTE `provenance_worker`) returns the heads with no anchor at their `seq`, oldest first, with `occurred_at`, so the hourly job can drop its trial-insert probe.
- `transparency_roots.snapshot_at timestamptz` (nullable until T2.4's insert sends it): the moment of the snapshot whose chain heads the root covers; `transparency_roots_guard` refuses a future time or one before the root's Nairobi day ended.
- `ix_provenance_records_content_hash` for `/verify` upload matching without a cert id.
- Not built: the owner's opt-in to show name and title on `/verify`. The spec says only "unless the owner opts to show name and title" (06 6.4 item 2); which name (handle, display name or D2 legal name), per proposal or per version, and whether withdrawing the opt-in hides the name again are not written down, so the column waits for that decision.

Batch reservations (T2.2 review, M2 and m3 on `feat/REQ-LLM-01-llm-layer`):

- `llm_calls.batch_id` and `custom_id` (`varchar(64)`, both or neither); status `batch_reserved` only with a batch id. Partial unique indexes on `(batch_id, custom_id)`: one reservation per item (`status = 'batch_reserved'`) and one settlement per item (`batch_id IS NOT NULL AND status <> 'batch_reserved'`), so the ledger settles with an untargeted `INSERT ... ON CONFLICT DO NOTHING`.
- The spend rule is defined once, in the view `llm_spend` (`security_invoker`; `org_id`, `user_id`, `cost_usd`, `created_at`; SELECT bridge_app only): a row counts unless it is a reservation whose item has settled. `app_llm_spend_usd()` sums it as the owner; the tenant monthly sum must read it (under the caller's RLS) instead of `llm_calls`. bridge_app's column SELECT on `llm_calls` adds `batch_id` and `custom_id`.

Fifth review round (reviewer CHANGES_REQUIRED, security-reviewer PASS with minors, on the fourth round; "a dispute is decided in SQL, not by the label" is the orchestrator's decision):

- Disputes: `app_claim_competes(org, claimant)` (no EXECUTE for any role; called by the claim functions as the owner) is true when another user holds an approved claim on the organisation or is an active owner or admin of it, and the claimant is not an active owner, admin or signatory of it. `app_decide_claim` approving such a claim runs the transfer whatever its status label; approving any other claim transfers nothing (the E1 to E2 upgrade by the organisation's own member). `org_claims_guard` files a competing open claim as `disputed` whatever status is sent and refuses an open claim sent as `disputed` that competes with nobody (closed statuses written by the owner, fixtures and the seed, are left as sent); `app_approve_claim_e1` returns `disputed` for a disputed claim, a claim on an E2 organisation or a claim that competes (no longer `pending_review`). New trigger `org_claims_status_guard` (BEFORE UPDATE, invoker): only the table's owner, that is the claim functions, turns a claim into `disputed` or out of it; the claimant may still withdraw a disputed claim, and the UPDATE policy keeps admitting an unchanged `disputed` so the claimant can add evidence to it. `app_confirm_claim_otp` and `app_reissue_claim_otp` also serve a disputed claim (a claim filed as a dispute still proves its domain); a disputed claim whose reissues run out stays `disputed`.
- The transfer strips `owner` and `admin` from every other membership whatever its status, so a membership removed before the dispute regains no power on reactivation.
- Batch items belong to their tenant: `uq_llm_calls_batch_reservation` and `uq_llm_calls_batch_settlement` are on `(batch_id, custom_id, org_id, user_id)` NULLS NOT DISTINCT (same partial predicates); the `llm_spend` rule cancels a reservation only by a settlement with the same `org_id` and `user_id` (IS NOT DISTINCT FROM); new trigger `llm_calls_batch_guard` (BEFORE INSERT, SECURITY DEFINER) refuses a settlement for an item that has reservations, none of its own tenant (another tenant's request, or a ledger bound to another organisation or user than the reservation). Reservations of different tenants for one pair coexist and each settles only as its own, so squatting a pair blocks nobody. The `llm_calls` INSERT policy adds: a batch row with no user and no organisation only from a request that binds no user (the platform job). Deviation from the brief, reported: the brief's trigger compared a new row with every existing row of the pair; comparing a settlement with the pair's reservations gives the same refusals for settlements (T2.2's `test_another_tenant_cannot_settle_or_cancel_an_items_reservation`) without letting a first squatting row block the real tenant's reservation (probe L2b), and without the system-row rule another tenant could still settle a platform job's item.
- `document_views` INSERT: the NDA-acceptance clause (the viewer's own, for that proposal, under that organisation) is now tested as the viewer (`test_only_a_granted_viewer_logs_a_view_under_the_granting_org`, revert-to-prove); no schema change.
- `chain_anchors_guard`: the TSA time is also no earlier than the anchored event's `occurred_at` less one minute.
- Item H (T2.2 M2, for `batch_poll`): `app_llm_batch_owned(p_batch_id varchar)` (SECURITY DEFINER, EXECUTE bridge_app only) is true only when every `llm_calls` row of the batch belongs to the caller's bound tenant, that is the rows it could have written: a row naming a user names `app.user_id`, a row naming an organisation names one that user is an active member of (the bound one when `app.org_id` is set), and a platform job's row (no user, no organisation) belongs only to a caller with nothing bound; false for a batch with no row. `batch_poll` calls it before fetching a batch's results, because one provider account serves every tenant and bridge_app cannot read other tenants' rows or system rows. (Round 6 judges the batch by its earliest reservation instead; see below.)

Sixth review round (reviewer CHANGES_REQUIRED and security-reviewer PASS with findings on the fifth round; the orchestrator's answers to the implementer's questions Q1 to Q5, 2026-09-29, are final):

What changed (`2ca0347`, `c933f0f`, `64c834e`, `108a0f3`; full backend suite 951 passed on Linux):

- Item 1, the transfer: an upheld dispute strips `signatory` as well as `owner` and `admin` from every other membership, whatever its status (`{viewer}` when nothing is left), and revokes pending invitations carrying any of the three, so a signatory appointed under the ousted control has no E2 shortcut and their later claim is a dispute.
- Item 2, labels: `app_relabel_open_claims(org)` (no EXECUTE) labels the organisation's open claims `disputed` exactly when `app_claim_competes`; a `disputed` claim that no longer competes becomes `pending_review`. It runs from the new trigger `memberships_claims_relabel` (AFTER INSERT OR UPDATE on `memberships`, row level, SECURITY DEFINER; the downgrade drops it, `memberships` stays) and after every approval in `app_decide_claim` and `app_approve_claim_e1`. `app_decide_claim` approves only when the stored label agrees with the predicate (Q1).
- Item 3, seats and domains: routine approvals (a claim that competes with nobody) seat the claimant through `app_seat_claimant` (no EXECUTE): an active member keeps their roles unless the organisation has no active owner (then `owner` and `admin` are added; Q2); anyone else becomes owner and admin. An E1 approval of an organisation already E1, and an E2 approval of one already E1 or E2 (Q3), keep its `verified_domain` unless the claimant is an active owner; a first verification and an upheld dispute set the claim's domain.
- Item 4, batch ownership: `app_llm_batch_owned(batch_id)` judges the batch by the tenant of its earliest reservation (`status = 'batch_reserved'`, by `created_at`, then `id`) instead of requiring every row of the batch to be the caller's; false for a batch with no reservation (a batch with settlements only is no longer anybody's). Q5: `llm_calls_batch_guard` sets a reservation's `created_at := clock_timestamp()` whatever is sent.
- Item 5, settlements: `app_llm_settle_batch_item(p_batch_id, p_custom_id, p_id, p_task, p_purpose, p_model, p_input_tokens, p_output_tokens, p_cache_read_tokens, p_cache_write_tokens, p_cost_usd, p_latency_ms, p_status, p_stop_reason, p_trace_id, p_inputs)` (SECURITY DEFINER, EXECUTE bridge_app) inserts the item's settlement with the `org_id` and `user_id` of the batch's earliest reservation, for the batch's tenant (`app_llm_batch_owned`) or the platform job (nothing bound), at the database's `now()`, with a final status (never `batch_reserved`), under every CHECK and trigger of `llm_calls`; `ON CONFLICT DO NOTHING` on the settlement index, so it returns false once the item has settled. Anybody else and an unknown batch get the same `insufficient_privilege` refusal ("no batch of the caller's with that id"). A reservation whose user has left the organisation therefore still settles (by the job).
- Items 6 and 7 (tests of behaviour that already held, proven by mutation below): a disputed claim's email code is reissued like any other and the claim stays `disputed` when the reissues run out; `app_claim_competes` counts another user's approved claim alone (after staff removed that user's membership) and not a removed ex-owner alone.
- Item 8: `app_approve_claim_e1` returns `disputed` for a claim that competes, and `pending_review` (never approval) for a claim on an E2 organisation that competes with nobody or one still labelled `disputed` that no longer competes.

Tests (`backend/tests/integration/test_privileges.py` unless named): new `test_signatories_appointed_under_the_ousted_control_lose_the_role` (E1 and E2; item 1), `test_a_claims_label_follows_the_organisations_control` (item 2, the review's N4, N5 and PROBE3), `test_a_routine_e2_approval_never_makes_a_member_an_owner` (items 3 and 8, N3, N6, N7b), `test_a_routine_e1_approval_keeps_the_owners_domain_and_roles` (item 3), `test_a_routine_e2_approval_keeps_the_owners_domain` (Q2, Q3), `test_a_batch_item_settles_once_through_the_function_even_after_its_user_left` (item 5, N9, N9a); changed `test_an_upheld_dispute_transfers_the_organisation` (signatories and their invitations, item 1), `test_approving_a_claim_that_is_not_disputed_transfers_nothing` (the signatory keeps `{signatory}`), `test_a_competing_claim_is_decided_as_a_dispute_whatever_its_label` (M16, M17), `test_claim_otp_attempts_never_reset_and_reissues_are_capped` (M13, M14b), `test_a_batch_is_owned_only_by_its_tenant` (item 4, N10a, Q5: squats sent an hour back), `test_e1_claims_approve_automatically_only_on_an_official_domain` (its AC-DIR-2 claim is now on an E2 organisation that has an owner, item 8); `test_migrations.py`: the function catalog (EXECUTE and SECURITY DEFINER of the four new functions) and the trigger catalog (`memberships_claims_relabel`).

Follow-ups (MINOR, not built in this round):

- `memberships_claims_relabel` fires on INSERT and UPDATE only: a membership or an approved claim deleted by a cascade (a user's erasure) relabels nothing, so another claim can keep a stale `disputed` label. It fails closed (`app_decide_claim` refuses the approval; rejecting still works) until the next roster change. Relabel on DELETE too, or from the erasure job.
- A `disputed` claim relabelled `pending_review` before its email code was confirmed is outside the code path (`app_confirm_claim_otp` and `app_reissue_claim_otp` serve `otp_sent`, `dns_pending` and `disputed`); the claimant's own UPDATE may move it back to `otp_sent`, which T2.6b must do (or a later round relabels by proof state).
- `memberships_claims_relabel` runs `app_claim_competes` for every open claim of the organisation on every membership write, the transfer's multi-row updates included; cheap at pilot scale, worth a statement-level trigger if rosters grow.

Deviations and answers:

- Q1, accepted deviation (item 2, stale labels). The brief had `app_decide_claim` write the label `app_claim_competes` gives and then raise. A RAISE aborts the caller's statement and rolls back everything the function wrote in it, the corrected label included, so staff would keep seeing the stale label and every retry would fail the same way. Instead labels are kept in step where the predicate's inputs change: the new trigger `memberships_claims_relabel` (AFTER INSERT OR UPDATE on `memberships`, row level, SECURITY DEFINER) and every approval (`app_decide_claim`, `app_approve_claim_e1`) call `app_relabel_open_claims(org)` (no EXECUTE for any role), which labels the organisation's open claims `disputed` when they compete and a `disputed` one that no longer competes `pending_review`. `app_decide_claim` still refuses to approve a claim whose stored label disagrees with `app_claim_competes` (`check_violation`, "the claim is labelled … although it …"): such a label was written past the claim functions (the claimant can neither set nor clear the mark, `org_claims_status_guard`), so it is refused rather than decided on; rejecting the claim stays possible.
- Q2, accepted as built (item 3, seating the claimant). Approving a claim that competes with nobody seats the claimant through `app_seat_claimant` (no EXECUTE for any role): a claimant with an active membership keeps their roles unless the organisation has no active owner, when `owner` and `admin` are added; a claimant with no active membership becomes owner and admin. This holds for the E2 shortcut too (an owner, admin or signatory of an organisation already E1 on the claimed domain, with no email code or DNS record): on an organisation whose only owner has left, staff approving that member's E2 claim make them owner and admin. Reason: an organisation with no active owner has nobody else to appoint one, the claimant is an active member on the verified domain, and staff approve E2 only after the document review and the claimant's acceptance of the current Master Enterprise Terms. Covered by `test_a_routine_e2_approval_keeps_the_owners_domain` (the signatory of `orphan`).
- Q3, yes (`64c834e`): the item-3 domain rule applies to E2 as well: `app_decide_claim` approving an E2 claim on an organisation already E1 or E2 keeps its `verified_domain` unless the claimant is an active owner or the approval upholds a dispute.
- Q4, accepted: the stranded-reservation threat (item 5) is a denial of the spend caps, so its THREAT_MODEL row is under §6 D (cost controls), not §4 (payments and billing).
- Q5, yes (`108a0f3`): `llm_calls_batch_guard` sets a reservation's `created_at` to `clock_timestamp()` whatever is sent, so a backdated reservation cannot become a batch's earliest (item 4).

Mutation proofs of the round-6 tests for behaviour that already held (items 6 and 7; the other items' tests were shown red on the unfixed revision, 14 failures, before `2ca0347`). The brief named them M13, M14b, M16 and M17 without writing them down, so they are defined here: each breaks one guard of the revision on `0fcabad`, runs `tests/integration/test_privileges.py`, restores the file (`git checkout -- backend/alembic/versions/20260927_0002_schema_v2.py`) and reruns the named test green. Command (in `backend/`): `TEST_DATABASE_ADMIN_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/postgres .venv/bin/python -m pytest -q -p no:cacheprovider tests/integration/test_privileges.py` (the fixtures build a fresh database from the revision file for each run). No mutated state was committed.

| Proof | Guard broken (revision 0002) | Mutated line | Red (1 failed, 69 passed) | Restored |
|---|---|---|---|---|
| M13 | `app_reissue_claim_otp` serves a disputed claim (item 6) | `IF v_claim.status NOT IN ('otp_sent', 'dns_pending', 'disputed') OR …` → `NOT IN ('otp_sent', 'dns_pending')` | `test_claim_otp_attempts_never_reset_and_reissues_are_capped`: `CheckViolation: app_reissue_claim_otp: the claim is not waiting for an email code` at the first reissue of the disputed claim (line 925) | 1 passed |
| M14b | a disputed claim whose reissues run out stays disputed (item 6) | `SET status = CASE WHEN status = 'disputed' THEN status ELSE 'pending_review' END` → `SET status = 'pending_review'` | `test_claim_otp_attempts_never_reset_and_reissues_are_capped`: `assert (0, 5, 'pending_review') == (0, 5, 'disputed')` (line 927) | 1 passed |
| M16 | `app_claim_competes`: another user's approved claim alone competes (item 7) | the `EXISTS (… org_claims c … c.status = 'approved')` branch → `false` | `test_a_competing_claim_is_decided_as_a_dispute_whatever_its_label`: `assert 'otp_sent' == 'disputed'` for the newcomer's claim once the approved claimant's membership was removed (line 1703) | 1 passed |
| M17 | `app_claim_competes`: only an active owner or admin membership competes (item 7) | `WHERE m.org_id = p_org AND m.user_id <> p_claimant AND m.status = 'active'` → without `AND m.status = 'active'` | `test_a_competing_claim_is_decided_as_a_dispute_whatever_its_label`: `assert 'disputed' == 'otp_sent'` for a claim on an organisation held only by a removed ex-owner (line 1714) | 1 passed |

Compatibility for the merging branches (grepped 2026-09-29 at the commits named; each branch has already merged the round-6 SQL, `108a0f3`, and T2.4 and T2.2 also `4dd313a`). Everything schema v2 added after `108a0f3` is documentation (`0fcabad`, `4dd313a`, `ce0c234`, `b0c8e70`: this card, THREAT_MODEL, the revision docstring and the `OrgClaim`/`LlmCall` docstrings), so re-merging changes no behaviour. The shared T2.1 files on every branch (revision, `test_privileges.py`, `test_migrations.py`, `test_rls.py`, `world.py`, the models) equal the schema branch's apart from those docstrings: take the schema branch's versions.

| Branch (at) | File:line | What must change |
|---|---|---|
| T2.2 `feat/REQ-LLM-01-llm-layer` (`73e4cce`) | `backend/src/bridge/llm/sql_ledger.py:162-169` (`SqlLedger.settle`; the insert at :164) | Settle through `app_llm_settle_batch_item(...)` (named arguments, the 16-parameter signature above) instead of `pg_insert(LlmCall)….on_conflict_do_nothing()`. Pass the clamped `row_values(entry)`: the function does not clamp (a cost above 100 USD raises the CHECK). It ignores the entry's `org_id`, `user_id` and `created_at` (it writes the batch's earliest reservation's tenant and `now()`), returns false once the item has settled, and raises `insufficient_privilege` ("no batch of the caller's with that id") for a caller that is not the batch's tenant and for an unknown batch: map that to `LLMBatchNotOwned`. Update the module docstring (:24-28). |
| T2.2 | `backend/src/bridge/llm/client.py:634-645` (`batch_poll`) | Before `batch_state` (:642) and `batch_results` (:645), check `app_llm_batch_owned(handle.batch_id)` in the ledger's bound session and raise `LLMBatchNotOwned` when it is false. Round 6 changed its meaning: the tenant of the batch's earliest reservation, no longer every row of the batch; false for a batch with no reservation, so a batch whose `reserve` failed (:627-632, `llm.batch_unreserved`) belongs to nobody and its poll is refused (an operator path). |
| T2.2 | `client.py:641` (`check_subject` with the handle's tenant) | The stranded-reservation path: once the batch's user has left the organisation, their own poll is refused (RLS, `app_llm_batch_owned`) and only the platform job (nothing bound) may settle, which `app_llm_settle_batch_item` accepts; but `check_subject(org_id=handle.org_id, user_id=handle.user_id)` refuses an unbound session. The job's poll must skip that check (settlements take the reservation's tenant anyway), and fetching results with nothing bound must stay the job's alone. |
| T2.2 | `sql_ledger.py:73` (`row_values`: `"created_at": entry.created_at`), used by `reserve` (:152-160) | Nothing breaks: `llm_calls_batch_guard` replaces a reservation's `created_at` with `clock_timestamp()`. Leave it out for reservations or say in the docstring that the stored time is the database's; the in-memory spend window (`ledger.py:170`) keeps the entry's time. |
| T2.2 | `backend/src/bridge/llm/ledger.py:111` (`LedgerStore.settle`), `:136-160` (`InMemoryLedger.reserve`, `settle`, `_check_tenant`) | Mirror the SQL rules: `batch_owned` (the earliest reservation's tenant; false with no reservation), settlements written as that tenant and refused otherwise (`LLMBatchNotOwned`), and reservations of different tenants for one item coexisting (round 5; `reserve` still refuses a second tenant's). At `73e4cce` the tests for all of this are written (`tests/unit/llm/test_ledger_and_sinks.py:85`, `:111`; `tests/unit/llm/test_batch.py:351`, `:372`; `tests/integration/llm/test_sql_batches.py:264`, `:297`, `:336`) and the source is not switched yet. |
| T2.4 `feat/REQ-PROV-01-provenance` (`87ae05c`) | `backend/src/bridge/provenance/transparency.py:126-146` (`_unanchored`), `:204` | Open since round 5, not round 6: the trial insert timed at `_EPOCH` (:139) is refused by `chain_anchors_guard` (the TSA time is no earlier than the event's `occurred_at` less one minute), so the hourly run raises. Read `SELECT * FROM app_unanchored_chain_heads()` (heads with no anchor, oldest first, with `occurred_at`) as `provenance_worker` and drop the probe; update the module docstring (:3-9) and the `_HEADS` comment (:108-111: `app_audit_chain_heads()` returns `occurred_at`). |
| T2.4 | `transparency.py:265-268` (`_INSERT_ROOT`), `:290` | Send `snapshot_at` (the `statement_timestamp()` already read at :290): `transparency_roots_guard` refuses a snapshot in the future or before the root's Nairobi day ended (NULL is accepted until it is sent). Update the comments at :26-29 and :258. |
| T2.4 | `backend/tests/integration/provenance/test_transparency.py:122-123` | The `database_clock_guard` docstring says the probe's epoch trial inserts pass the guard; they no longer do. |
| T2.4 | `backend/tests/integration/provenance/builders.py:192-200` | No change: its `memberships` inserts fire `memberships_claims_relabel`, a no-op without open claims. |
| T2.6a `feat/REQ-DIR-02-provisional-seed` (`b70f9f9`) | none | No change: the seed loader writes `organizations` only, and the membership that `tests/integration/directory/test_seed_and_browse.py:123` inserts fires the relabel trigger as a no-op. |
| D1 `feat/REQ-PROV-04-verification` (`b5bcfb7`) | none | No change: D1 uses `phone_verifications` and `app_confirm_phone_otp`, which round 6 did not touch. |

Not on these branches: `app_decide_claim`, `app_approve_claim_e1`, the claim labels and `app_seat_claimant` have no caller outside schema v2 yet; T2.6b is their first user (follow-ups above).

Notes for the code on this schema:

- OTP digests are HMAC-SHA-256 under a server pepper (T2.10a already does), never bare hashes; bridge_app can write them but never read them back, and the comparison stays in SQL (`app_confirm_phone_otp`, `app_confirm_claim_otp`).
- `app_approve_claim_e1`'s self-signup branch approves the organisation's own owner on whatever domain they verified (email code and DNS TXT record; no list is consulted), so the free-mail, punycode and homoglyph block of docs/spec/06 6.2 is application-side: T2.6b must refuse those domains before inserting a claim.
- `llm_calls.inputs` never holds Tier-2 plaintext: the LLM layer stores Tier-2 fields only as name, tier and length (`feat/REQ-LLM-01-llm-layer`, `bridge/llm/ledger.py`, AC-SEC-6); staff admin reads the inputs through `app_llm_call_inputs`.
- `organizations`: the public directory set is `id`, `kind`, `legal_name`, `slug`, `country`, `regions`, `county_code`, `sector_id`, `website`, `verified_domain`, `official_domains`, `verification`, `public_entity`, `source`, `source_url`, `source_retrieved_on`, `e2_verified_at`, `delisted_at`, `created_at`, `updated_at`; directory serialisers expose only those. The listed-organisations policy still exposes the whole row (also `registration_no`, `created_by`, `invitations_opted_out_at`, `reverify_due_on`, `suspended_at`) because column privileges apply per role, not per row: a column-limited SELECT would also hide those columns from members reading their own organisation and break the Phase 1 organisation routes, which load the whole row. None of them is secret (registration numbers come from public registers).

## T2.5 scope

`can_view_tier2(viewer, version)` as one function returning the first failing condition: `FEATURE_TIER2_ENABLED`; org E2 and not suspended; viewer membership on the verified domain with role reviewer, signatory or admin and TOTP enrolled (step-up if last MFA >12 h); Master Enterprise Terms accepted (hash recorded); Evaluation NDA accepted by this person for this proposal (template hash); active `disclosure_grant` from the owner's policy; no WITHDRAWN/DECLINED/TERMINATED engagement for that org; no revocation. Each refusal is 403 plus an audit event naming the condition. Grants: auto-grant to tagged orgs (default policy), manual approval, optional "any E2 org in my niche"; a grant on an untagged proposal consumes an org unlock (REQ-BIL-03). Renders (HTML document and PDF) are server-side with the owner attribution mark (handle before `INTEREST_CONFIRMED`, display name after; cert id, `registered_at` EAT, `/verify/{cert_id}`) and the per-viewer tiled overlay (name, org, `view_id`, EAT date) plus `view_id` in document metadata; each render writes `document_views` in the same request. Owner panel "Who has seen this" (org, person, date, coarse duration, NDA template version); revocation stops future views and says so. Policy changes, manual grants, raw-download enablement need step-up and send an email notice.

## Acceptance criteria and tests

AC-REPO-1 (`integration/proposals/test_access.py::test_predicate_negatives`), AC-REPO-2 (`integration/proposals/test_render_marks.py`), AC-REPO-3 (`integration/test_privileges.py`, `contract/test_search_schemathesis.py`), AC-SEC-1/b (`integration/test_rls.py`), AC-SEC-2 (`integration/test_feature_flags.py::test_tier2_flag`).

## Round 6 reviews (2026-09-29, prototype track): reviewer PASS, security-reviewer PASS; MINOR follow-ups (not built, PLAN §8)

Reviewer (22 mutations red, 4 survivors explained or listed below; 951 passed) and security-reviewer (probes P1–P4) found no BLOCKER or MAJOR.

1. Seat-aware domain rule (both reviewers): `v_owner` is computed before `app_seat_claimant` (`:1653-1657`, used at `:1675`, `:1698`), so a claimant who becomes owner through this approval (an organisation nobody holds, e.g. after the sole owner's erasure) keeps the old control's `verified_domain`. Fix: set the domain when `v_dispute`, a first verification, an active owner, or the claimant had no active membership / no active owner existed.
2. A first verification of an E0 organisation with an active owner takes a non-owner member's domain (`:1675`, `:1698`). Fix: refuse it in `app_decide_claim` or route it to the owner in T2.6b.
3. A non-owner's routine E2 approval still rewrites `public_entity`, `registration_no`, `e2_verified_at`, `reverify_due_on` (`:1700-1703`). Fix: the same CASE as the domain, or refuse non-owner E2 claims that change them.
4. Deadlocks (40P01, fail closed): `app_decide_claim` locks claim → organisation while roster writes lock membership → claim (relabel trigger), and `app_approve_claim_e1` locks its claim then the organisation. Fix: lock the organisation before the claim everywhere, or T2.6b retries on 40P01.
5. `app_llm_settle_batch_item` (`:2020`): no test pins the tenant a settlement is written under (mutation J2 survives). Add a squatted item to `test_a_batch_item_settles_once_through_the_function_even_after_its_user_left` and assert T's ids.
6. `memberships_claims_relabel` `OLD.org_id` branch (`:2480`) untested (mutation O survives). Cover a membership move, or refuse `org_id` changes on `memberships`.
7. A batch tenant settling an item only another tenant reserved gets `check_violation`, not `insufficient_privilege` (`:2504-2516`); optionally map both to `LLMBatchNotOwned`.
8. Commit `2ca0347` is a 725-line "wip (unverified)" commit; it stays in history (no rewrite; recorded with the earlier wip commits as a deviation). Its content was verified in session 2 (951 passed) and reviewed in round 6.

## T2.5 prototype P3 (2026-09-29): built

Files: `bridge/proposals/{access,grants,render,views}.py`, `bridge/legal/nda.py`, the Tier-2 routes in
`bridge/proposals/router.py` (`tier2_router`), `backend/openapi.json`, `frontend/lib/api/schema.d.ts`.

- **Predicate** `access.can_view_tier2(db, settings, live, proposal_id=, org_id=, check_nda=)` returns an `Access` or
  the first failed `Condition` (its value is the error code). Order: `tier2_disabled`; the proposal is published, clear
  and has a registered current version (404; its owner passes every organisation condition and reads unlogged); an
  active membership of the path's organisation (404); `org_not_e2`, `org_suspended`; `role_not_permitted`
  (reviewer, signatory or admin, as the database); `email_unverified`; `domain_mismatch` (the address at exactly the
  verified domain, compared like citext); `mfa_enrolment_required`; `step_up_required` (the session's second factor
  at most `STEP_UP_MAX_AGE_HOURS` = 12 h old); `master_terms_required` (the current version accepted for the
  organisation); `grant_revoked`, `grant_required` (an active, unrevoked Tier >= 2 grant); `engagement_ended`
  (WITHDRAWN, DECLINED, TERMINATED); `nda_required` (the current Evaluation NDA, this person, this proposal, this
  organisation). The NDA is last so the NDA step is offered only when nothing else is missing, and accepting it needs
  the others (`check_nda=False`); the card's list put it before the grant. The facts are read under the viewer's RLS;
  then `app_tier2_granted(proposal, version, org)` must agree. RLS hides `org_claims` from a reviewer, so the
  application checks only that the current Master Enterprise Terms were accepted, and a database refusal after every
  application condition passed is reported as `master_terms_required` (the acceptor was neither the approved E2
  claimant nor an active signatory). Each refusal writes `tier2.access_denied` (condition, purpose `render|nda`,
  organisation id) on the organisation's chain once the viewer is its member, else on the viewer's, committed before
  the 403/404.
- **Grants** `grants.grant_on_tag(db, *, owner_id, proposal_id, org_id) -> UUID | None`: what P4 calls in the owner's
  transaction right after inserting a `delivered` tag (tenant bound to the owner; it does not commit). Policy
  `auto_tagged` (the default): an active Tier-2 grant (`source auto_tagged`, `granted_by` the owner,
  `counts_as_unlock` false), idempotent under an advisory lock on (proposal, organisation); an organisation's pending
  `requested` grant is activated instead (it keeps its source: bridge_app has no UPDATE on `source`). Any other policy
  returns None. `GrantError` when the caller does not own the proposal or has no open `delivered` tag on it for that
  organisation. Audited `tier2.grant_created` or `tier2.grant_activated` on the owner's chain. A grant made while the
  flag is off releases nothing until it is on.
- **Evaluation NDA** (`bridge/legal/nda.py`; `GET|POST /api/orgs/{org_id}/proposals/{id}/nda`): the current
  `nda_templates` row of kind `evaluation` with its legal body (the seeded placeholder) and the viewer-logging notice
  v1 (`[[COPY-REVIEW]]`); 503 `not_configured` without a seeded NDA. Accepting echoes `template_id`, `sha256` and
  `logging_notice_version` (409 `nda_outdated` otherwise; 422 for a malformed hash) and records one row per person,
  organisation, proposal and template version (201; 200 with the same row when repeated), with the template hash and
  notice version, under an advisory lock; audited `tier2.nda_accepted` on the organisation's chain. The owner gets
  409 `nda_not_needed`.
- **Render and access log**: see `REQ-PROV-03.md`. `GET /api/orgs/{org_id}/proposals/{id}/tier2` (organisations; one
  logged view per page) and `GET /api/me/proposals/{id}/tier2` (the owner's preview). No JSON form of Tier 2 exists
  for organisations (`test_render_marks.py::test_organisations_get_tier2_only_as_a_marked_page`).
- **Flag**: `REQ-SEC-01.md`.
- Tests: `integration/proposals/test_access.py::test_predicate_negatives` (AC-REPO-1, 25 cases: every condition
  above, the Master Enterprise Terms by a non-signatory, by the approved E2 claimant (readable) and superseded, the
  grant requested and revoked, each ended engagement, the NDA superseded, another organisation of the viewer's without
  a grant, hidden and held proposals, the membership removed; each refusal audited, no view logged, no Tier-2 text in
  the response, logs or audit), `::test_the_owner_reads_their_own_tier2_without_a_logged_view`,
  `::test_a_stranger_and_an_anonymous_caller_get_nothing`; `test_nda.py`; `test_grants.py`; `test_render_marks.py`
  (AC-REPO-2); `integration/test_feature_flags.py::test_tier2_flag` (AC-SEC-2); `unit/proposals/test_access_rules.py`,
  `unit/proposals/test_render.py`. The shared scene is `integration/proposals/tier2_scene.py` (registered in
  `integration/conftest.py`). No schema change was needed.

## T2.5 after prototype (rescheduled, not removed)

- Manual approval, the "any E2 organisation in my niche" policy, organisations' grant requests and the owner's
  decisions on them, revocation by the owner ("stops future views only", and the UI says so), with the step-up and
  the email notice on policy changes, manual grants and raw-download enablement (`REQUIREMENTS.md` §7).
- Grants for held tags delivered on E2 approval (`app_decide_claim` delivers the tags; nothing grants yet).
- The unlock quota (REQ-BIL-03), the PDF render, attachment renders and raw download, coarse durations, the KIPI and
  KECOBO nudge before the first Tier-2 release, the P8 screens (the NDA step, the Tier-2 view, the "Who has seen this"
  panel).
- Follow-up for `db-migrations` (ruling 6): a unique index on `nda_acceptances (user_id, org_id, proposal_id,
  nda_template_id)` makes "once per version" a database rule (today the advisory lock and the lookup in
  `bridge/legal/nda.py`).

## T2.5 orchestrator rulings (2026-09-29, on the P3 report)

1. Tenancy before the flag on organisation paths (404 to non-members, 403 `tier2_disabled` otherwise): accepted;
   recorded in `REQ-SEC-01.md`.
2. The terms condition checked by the application as "the current version was accepted", the database deciding who
   accepted it (a refusal only it can see reported as `master_terms_required`): accepted.
3. The NDA checked last, after the grant: accepted.
4. Manual grants, revocation, policy changes, held-tag grants, the unlock quota, the PDF render, attachments, raw
   download and durations: after the prototype (above).
5. `frame-ancestors 'self'` and `X-Frame-Options: SAMEORIGIN` on the render only: accepted.
6. The unique index on `nda_acceptances`: a follow-up for `db-migrations` (above).
7. The viewer-logging notice and the render text stay `[[COPY-REVIEW]]`.

## T2.5 on schema v3 (revision 0003, merged 2026-09-29)

- `engagements.state` is now the projection of `engagement_events`. The predicate still reads `state` for the
  ended-engagement condition and denies exactly `WITHDRAWN`, `DECLINED` and `TERMINATED`, as `app_tier2_granted`
  (unchanged by 0003) does: an `EXPIRED` or `CLOSED` engagement also has `ended_at` but keeps the access, as in
  docs/spec/06 6.1.
- The owner attribution now reads the chain: the owner is named once the engagement's events have entered
  `INTEREST_CONFIRMED` or a later main-path state (`access.REVEALED_STATES`), whatever the current state, so a pause,
  dispute or expiry after the approval keeps the name. `PROCUREMENT_ROUTE` is no longer in the set: a public entity
  determines its route before it approves to proceed.
- The T2.5 fixtures move engagements as the parties do, as `bridge_app`: the developer creates the `SUBMITTED`
  engagement of their delivered tag; the reviewer starts the review or declines (a reason code); a public entity's
  admin sets the procurement route; the signatory names the contact and approves to proceed, or terminates; the
  developer withdraws or pauses (`tier2_scene.engage`, `step`, `approve_to_proceed`, `end_engagement`, which also
  checks the projection's `state` and `ended_at`). `test_render_marks.py::test_the_owner_is_named_once_the_organisation_approved_to_proceed`
  walks SUBMITTED → UNDER_REVIEW → PROCUREMENT_ROUTE → INTEREST_CONFIRMED → ON_HOLD (mutation: the reveal read from
  the current state instead of the history, or `PROCUREMENT_ROUTE` back in the set, turns it red).
- Not T2.5's files, left as they are (they pass on 0003): `integration/test_rls.py::_grant_scenario` still inserts its
  ended engagements directly as the owner (0003 records the inserted state as the genesis event), as do
  `integration/world.py` and `integration/test_migrations.py`'s fixtures.

