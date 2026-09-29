# REQ-PROP-01

- Task: T2.3 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (API), impl-frontend (wizard, F2)
- Files owned: `bridge/proposals/{editor,router,schemas,service}.py`, `bridge/problems/{service,router}.py`, `frontend/app/(app)/dev/ideas/`
- Depends on: T2.1, T2.2 (moderation pre-screen through `LLMClient`).

## Scope

3-step wizard (Problem & teaser → Full details → Review, attest & publish). Drafts are Tier 0 (owner only: a draft `proposal_versions` row plus its Tier-2 draft in `proposal_confidential` through `tier2_reader`). Linked Problem picker (published problems, filter by niche) or "Describe a new problem" (creates a Problem with `source=developer`, labelled "Developer-reported", published at once and queued for moderation without blocking). Niche label (`Parent › Child`), maturity, ask. Publishing validates (≥1 linked Problem, `niche_id`, Tier-1 sanitiser, summary ≤150 words), requires D1 (AC-IP-5: the publish route takes `profile: D1Developer` from `bridge.profiles.verification`, 403 `d1_required` below D1), checks the active-proposal cap (AC-SUB-1: 402, nothing created), records the three ownership attestations, registers the version (enqueues the T2.4 pipeline; `proposal.version_registered`), writes `signal_events` and the audit event. Publishing is the screen's one primary action.

## Acceptance criteria and tests

AC-REPO-4/a (`unit/proposals/test_publish_validation.py`, `frontend/e2e/proposal-wizard.spec.ts`), AC-PROP-5 (`integration/proposals/test_new_problem_flow.py`), AC-SUB-1 (`integration/billing/test_caps.py::test_fourth_proposal_402`), AC-IP-5 on the real publish route (`integration/profiles/test_verification.py::test_d1_required`: this task repoints it from the T2.10a probe route to the publish route and removes the probe).

## Prototype P2 (T2.3 minimal, 2026-09-29): built

- Routes (signed in; owner routes answer 404 for anyone else's proposal): `GET /api/me/proposals` (My ideas, Tier 1,
  newest change first, at most 200), `POST /api/me/proposals` (new draft, 201), `GET|PATCH /api/me/proposals/{id}`
  (current and draft versions with the owner's own Tier 2; the Tier-2 read is audited `proposal.tier2_read`),
  `POST /api/me/proposals/{id}/publish` (`profile: D1Developer`), `DELETE /api/me/proposals/{id}` (REQ-PROV-05),
  `POST /api/me/proposals/{id}/attachments` and `DELETE .../attachments/{attachment_id}`, `GET /api/proposals/attestations`,
  `GET /api/proposals/{id}` (the Tier-1 teaser of a published, clear proposal; everything else 404, the owner included)
  and `GET /api/problems` (the picker). Files: `bridge/proposals/{editor,service,router,schemas,tier2,attestations,deps,lifecycle}.py`,
  `bridge/problems/{service,router}.py`, `bridge/storage/scanner.py`, `ATTACHMENT_SCANNER` (`backend/.env.example`).
- Drafts are Tier 0: the draft `proposal_versions` row (Tier 1, sanitised on every save: 422 `invalid_teaser` with the
  fields), its `proposal_problems` links and one sealed Tier-2 JSON document per version (`bridge-tier2-v1`: approach,
  architecture, pricing, notes, links, attachments' ids, names and object keys) under the proposal's envelope key, read
  and written only as `tier2_reader`. Editing a published proposal starts the next version as a copy of the current
  one (Tier 1, still-visible links, Tier 2, attachment rows). Partial bodies: a field sent is applied, `null` clears.
- "Describe a new problem" is kept inside the sealed draft document (`draft.new_problem`) and becomes the Problem when
  the proposal is published (drafts are Tier 0, so nothing is public before): `source=developer`, `published`, clear
  (held when the pre-screen holds it), linked, labelled "Developer-reported", and filed with
  `app_open_moderation_case` (`regex`, reason `new_developer_problem`) without blocking (AC-PROP-5). Publishing removes
  the `draft` key before the version is registered, so it never reaches a manifest.
- Publishing, in one transaction or not at all: current attestation text version (409 `attestation_text_outdated`) and
  all three statements (422 `attestations_required`); `publish_errors` (AC-REPO-4/a: Tier-1 fields, niche, a linked or
  new Problem, the sanitiser again; 422 `cannot_publish`); the `active_proposals` cap for a first publication under a
  per-owner advisory lock (AC-SUB-1: 402 `plan_limit`, nothing created); the rules pre-screen (REQ-PROP-02/REQ-MOD-01);
  the version registered with `new_cert_id()` (the database sets `registered_at` and the handle); the proposal's Tier-1
  copy; the attestation row (text version + SHA-256); `enqueue_registration` (T2.4: certificate and `/verify` work once
  the worker runs); a `signal_events` row when the teaser is visible; `proposal.published` on the owner's chain.
- Attachments: raw body, type in `Content-Type` (PDF, PNG, JPG, Markdown, text; magic bytes checked, text UTF-8), name
  percent-encoded in `X-File-Name` (never in the URL), 1 byte to 20 MB (413), at most 10 per version; scanned by the
  demo-only `FakeScanner` (D-36: EICAR is infected and refused, 422 `attachment_infected`, only the refusal audited);
  stored in `uploads` under `attachments/{proposal_id}/{attachment_id}`.
- AC-IP-5 now runs on the publish route: `integration/profiles/test_verification.py::test_d1_required` was repointed
  and the test-only probe route removed.
- Tests: `unit/proposals/test_publish_validation.py`, `unit/proposals/test_deps.py`,
  `integration/proposals/test_drafts.py`, `test_publish.py` (registration end to end: pipeline, `/verify`, certificate,
  manifest with the attestation; version 2 chained), `test_new_problem_flow.py` (AC-PROP-5), `test_holds.py`
  (AC-PROP-6), `test_attachments.py`, `test_delete_retains.py` (AC-IP-6), `test_tier2_never_leaks.py`,
  `test_problem_picker.py`, `integration/billing/test_caps.py::test_fourth_proposal_402` (AC-SUB-1).

Choices the spec leaves open (prototype defaults): field limits (title 120, problem statement 2,000, impact claims
1,000, summary 1,500 characters and 150 words; approach and architecture 20,000, pricing and notes 5,000; 10 links,
http or https only; 5 linked problems; 10 attachments per version); "active proposal" = `status = published`;
the Tier-1 teaser needs a session (docs/spec/06 6.1 "all signed-in users"; RLS admits no anonymous reader); signal
kinds `proposal_published` (first visible publication, or a moderator's approval of a held one) and
`proposal_version_published`, with `actor_hash = app_subject_digest(owner, "signal_events.actor")`.

## After prototype (rescheduled, not removed)

- The wizard (F2, P8) and `frontend/e2e/proposal-wizard.spec.ts`; the niche label on the directory picker (P4).
- The Haiku pre-screen and the over-disclosure check through `LLMClient` (T2.2/P7) behind `PreScreen`.
- ClamAV behind `Scanner`, PDF re-rendering (`rerendered`), and attachment reads (the Tier-2 render, P3).
- Pagination of My ideas; Browse repo search (P4); the originality check (REQ-PROP-04); the assistant (REQ-PROP-05).
- Application-level encryption of attachment bytes (today: plaintext in `uploads`, bucket encryption by
  infrastructure; object keys and file names only inside Tier 2) and cleanup of an object orphaned when the database
  write after its upload fails.
- Open for the orchestrator: the attestation wording in `bridge/proposals/attestations.py` is `[[COPY-REVIEW]]` draft
  text for G2; REQUIREMENTS.md's AC-IP-5 row still describes the probe route.

## P2 review round 1 (2026-09-29): fixed, and follow-ups

Fixed (red test first each): an "@" before a domain is an email (MAJOR 1); the detectors and the pre-screen read a
Unicode skeleton (lookalikes, fillers, foreign full stops and digits, defanged forms; MAJOR 2); a moderation decision
carries the reviewed `subject_version_id` and answers 409 `case_changed` when the author published another version
meanwhile (MAJOR 3); wider phone separators, a payment keyword after the number, token word counts, lengths checked
after cleaning (422 `too_long`), only published and clear linked problems count at publishing; tests for the
concurrent cap, a chunked upload over 20 MB, the audited owner read, the picker and the attestation digest pin.

Follow-ups (not in P2):
1. db-migrations: the `proposal_versions` SELECT policy lets any signed-in `bridge_app` reader see every registered
   version of a published, clear proposal, including an older version that was held (a teaser approved at version 2
   exposes a held version 1 to direct SQL; no endpoint returns older versions today). Add a per-version moderation
   flag or limit non-owners to `proposals.current_version_id`.
2. When the LLM pre-screen lands (T2.2/P7), its `security_vulnerability` label must join the approve check in
   `bridge/admin/moderation.py` (today the rules re-screen the current text).
3. Commit sizes: several P2 commits exceed the ~300-line guideline (whole modules with their tests); later work
   splits by concern.
