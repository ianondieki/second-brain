# REQ-PROV-01

- Task: T2.4 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (pipeline), impl-integrations (TSA client); security-reviewer (Fable)
- Files owned: `bridge/provenance/{manifest,signing,tsa,service}.py`, `bridge/jobs/provenance.py`, `backend/tests/unit/provenance/`, `backend/tests/fixtures/tsa/`
- Depends on: T2.1.

## Scope

Registration pipeline, each step an idempotent Procrastinate job: RFC 8785 canonical JSON manifest (all Tier-1 and Tier-2 fields, attachment SHA-256s, owner ref `SHA-256(subject_salt ‖ user_id)`, attestation ids, `prev_version_hash`, `manifest_version`) → `content_hash = SHA-256(manifest)` → Ed25519 signature (`Signer` interface: `LocalSigner` from `PROVENANCE_SIGNING_KEY` in dev/test; `KmsSigner` stub, never called from tests) → RFC 3161 request/response (`TSA_URL`; DigiCert primary, FreeTSA fallback in config only) → `proposal.version_registered` audit event. The encrypted manifest is kept in `proposal_confidential.manifest_ciphertext` and in the `evidence` object store (S3 API; SeaweedFS in dev per D-24; in-memory fake in tests). "Timestamp pending" until the token is stored. Tests use a local `openssl ts` test CA generated at test time; never DigiCert, FreeTSA or KMS.

## Acceptance criteria and tests

AC-IP-1 (`unit/provenance/test_manifest.py` golden fixtures, `test_tsa_openssl.py`: `openssl ts -verify` on the stored `.tsr`), AC-IP-2 (`unit/provenance/test_tamper.py`, `integration/test_audit_chain.py`).

## Notes (T2.4, implementation)

Built: `bridge/crypto/envelope.py` (per-proposal AES-256-GCM data keys; `LocalKeyWrapper` from `TIER2_LOCAL_KEK`,
`KmsKeyWrapper` stub that refuses until Phase 8), `bridge/storage/objects.py` (`ObjectStore`, in-memory and S3
adapters), `bridge/provenance/{manifest,signing,tsa,service,transparency}.py`, `bridge/jobs/{outbox,provenance,audit}.py`,
`python -m bridge.provenance register-key`. Deviations and contracts:

- **Contract for the publish flow (T2.3).** Mark the version `registered` with `cert_id = service.new_cert_id()`
  (16 Crockford base32 characters, 80 random bits); give every version a `proposal_confidential` row whose Tier-2
  document is a UTF-8 JSON object (`{}` when empty) sealed with `envelope.seal(..., purpose=Purpose.TIER2)` under the
  proposal's data key (`new_data_key` for a new proposal, `open_data_key` on an earlier row for later versions);
  attachments must be `clean` with a SHA-256 (pending ones are retried, infected ones refused); then call
  `service.enqueue_registration(session, version_id)` in the publish transaction (the job exists only if it commits).
- **Owner ref** = `SHA-256(subject_salt || 16 raw bytes of user_id)`, computed only in `service.subject_digest`
  through the definer function `app_subject_digest(p_user_id, p_data)` (the salt never leaves the database), with the
  session bound to the owner and `p_user_id` = the owner.
- **Version hash fill.** `service._fill_version_hashes` writes the fill-once columns (`content_hash`,
  `prev_version_hash`, `manifest_version`) as `provenance_worker` only. Every step binds the version owner, and Tier 2
  and records are touched only as `provenance_worker`, so the owner-scoped RLS on `provenance_records` needs no code
  change.
- The hash step is serialised per version by a transaction-scoped advisory lock (a `FOR UPDATE` row lock would depend
  on the app role's UPDATE policy for registered versions).
- The sealed manifest goes to `proposal_confidential.manifest_ciphertext/manifest_nonce` and to the `evidence` bucket
  as `manifests/<proposal>/<version>/manifest-v1.sealed.json` (a JSON envelope with the wrapped key, nonce, AAD and
  ciphertext, so the object opens with the key wrapper alone). The `.tsr` lives in `provenance_records.tsa_token`.
- Retries: `RegistrationError` is permanent; other failures back off (30 s doubling to 1 h, 12 attempts); the
  timestamp step retries hourly for two weeks ("Timestamp pending" meanwhile). Exhausted jobs stay `failed` in
  `procrastinate_jobs`; every step is idempotent, so re-running them is safe.
- The `proposal.version_registered` audit event is a system event (global chain) written in the same transaction as
  the token; payload: cert id, content hash, key id, TSA serial and time (no Tier-2 text, no names).
- Test TSA: the root CA and TSA certificates are generated with `cryptography` at test time (portable across OpenSSL
  builds); tokens are issued with `openssl ts -reply` and checked with `openssl ts -verify` (`tests/openssl_tsa.py`).
- AC-IP-2 database half: `tests/integration/provenance/test_tamper_db.py` (the unit directory has no database); the
  manifest half is `tests/unit/provenance/test_tamper.py`.
- Coverage: `bridge/provenance` 99% after review round 1 (`uv run pytest --cov=bridge.provenance
  tests/unit/provenance tests/integration/provenance`); `[tool.coverage.run]` now traces SQLAlchemy's greenlets
  (`concurrency = ["greenlet", "thread"]`), which also lifts the measured coverage of every route handler.

## Notes (T2.4 review round 1 fixes)

- **TSA trust.** A token is stored only when it answers our nonce and imprint and its signer chains, through the
  token's certificates, to the CA bundle pinned for that URL (`TSA_CA_BUNDLE`, `TSA_FALLBACK_CA_BUNDLE`; PEM files,
  required outside `APP_ENV` dev and test), valid at `genTime`, with the timestamping usage as its only, critical
  purpose, named by the signed ESS `signingCertificate(V2)`, and a `genTime` within 15 minutes of the local clock.
  Issuers must be CAs allowed to sign certificates and, when they state an extended key usage, to timestamp
  (`tests/unit/provenance/test_tsa.py` refuses TLS-server, code-signing and non-keyCertSign intermediates). An ESS
  `issuerSerial`, when present, must name the signer (openssl omits it; the comparison used to fail on the explicit
  `[4]` tag and would have refused every token of a TSA that sends it). Ops supply the DigiCert and FreeTSA bundles
  before staging (`docs/runbooks/verify-offline.md`, "Operators").
- **One deadline per timestamp attempt**, primary and fallback together (`TSA_DEADLINE_SECONDS`, 30 s), on top of
  httpx's per-step `TSA_TIMEOUT_SECONDS` (whose read timeout restarts with every chunk). An hourly anchor run stops
  at its first failed timestamp and leaves the untried heads to the next run, oldest head first, then chain id.
- **No Tier-2 values in errors.** Canonicalisation errors name the field path and the kind of value only (keys that
  do not look like field names are numbered) and chain no library exception; a Tier-2 document that fails to decode
  raises without the decoder's exception (it holds the plaintext).
- **Audited owner downloads.** `manifest.json` and `certificate.pdf` append `provenance.manifest_downloaded` /
  `provenance.certificate_downloaded` on the owner's chain (payload: the cert id) and commit before sending.
- **Buckets** are created by `python -m bridge.storage ensure-buckets` in the dev compose `migrate` step (dev and test
  create; staging and production only check and fail closed), never at first use.
- **Nightly verification** retries transient failures (`bridge.jobs.audit.VERIFY_RETRY`, six retries over about 45
  minutes); a broken chain or a missing setting fails the job at once. Roots are signed only by a published,
  unretired key and keep naming it after it is retired (it stays listed with `retired_at`).
- **REQ-SEC-01 owner exemption (human decision, T2.4 review round 1).** An owner's reads of their own Tier 2 are not
  gated by `FEATURE_TIER2_ENABLED` (it still gates every `tier2` route of AC-SEC-2). So `GET
  /api/provenance/certificates/{cert_id}/manifest.json` (the registered manifest with its Tier-2 document, read as
  `tier2_reader` after the ownership check) is tagged `provenance`, not `tier2`, and AC-SEC-2's OpenAPI enumeration
  does not list it. It answers 404 to everyone but the owner, grantees included
  (`test_a_tier2_grantee_gets_neither_the_manifest_nor_the_certificate`), and audits every read. The same round
  decided that `/verify` may serve the Ed25519 signature, its key id and the `.tsr` (REQ-PROV-02 card).

## Notes (T2.4 review round 2, pre-merge MINORs)

- **Anchor runs** (REQ-AUD-01 card): each anchor in its own savepoint, one skew bound with `chain_anchors_guard`
  (the anchor path takes no token more than 60 s ahead of the worker clock; registration keeps ±15 minutes), lock
  `provenance:anchors`, batches of 25, a 15-minute budget per run.
- **`python -m bridge.provenance probe-tsa`** timestamps a random digest at each configured TSA on its own with the
  worker's client (pinned bundles, the one-minute bound); `docs/runbooks/verify-offline.md` step 4 runs it from the
  worker host before a release, `openssl ts -verify` stays as a second check. Real TSA calls: never in tests or CI
  (`tests/unit/provenance/test_probe_tsa.py` uses the local openssl TSA transport).
- **Tier-2 key paths.** Below `manifest.tier2` a refusal gives positions only (`manifest.tier2.<key 0>[1]`): the
  owner's keys are content too, even when they look like field names. Only the manifest's own fields are named.
- **Drafts carry no `owner_handle`** (`builders.registered_version`): schema v2 round 4 refuses one on insert and sets
  it at registration from `developer_profiles.handle`; the builder sends that same handle at registration, which the
  current schema's `registered_is_complete` check needs.
- **`POST /api/verify` from the command line** needs the CSRF pair (`GET /api/auth/csrf`, cookie plus
  `X-CSRF-Token`); the runbook shows it, the route stays protected.
- **Compatibility with schema v2 round 4** (`feat/REQ-REPO-01-schema-v2` at `abc4263`): `tests/integration/provenance`,
  `tests/unit/provenance` and `tests/unit/jobs` (196 tests) pass on a scratch copy of this branch carrying round 4's
  migrations, models, `world.py` and schema tests (`chain_anchors_guard`, `transparency_roots_guard`, the pinned
  `owner_handle`, the `(version_id, cert_id)` foreign key, database-set evidence times). After the merge,
  `app_unanchored_chain_heads()` can replace the anchor's trial-insert probe, and `transparency_roots.snapshot_at` can
  be written (`RootReport.snapshot_at`) and served.

## Schema follow-ups for db-migrations (schema v2; none blocks T2.4)

1. `app_audit_chain_heads()` also returns each head's `occurred_at`, so capped anchor runs take the oldest heads
   first (the query selects `h.*` and `anchor_order` uses the column when present; until then the order is chain id).
   Better still, `app_unanchored_chain_heads()` returning only heads without an anchor at their `seq`, with
   `occurred_at`, replacing the trial-insert probe (REQ-AUD-01 card).
2. `transparency_roots.snapshot_at timestamptz NOT NULL`: the moment of the REPEATABLE READ snapshot whose heads the
   root covers (`RootReport.snapshot_at` is computed and logged today). `/api/transparency` then serves it (a route
   contract change: regenerate `backend/openapi.json` and the frontend types).
3. An index on `provenance_records.content_hash` (upload matching without a cert id scans the table).
4. The owner's opt-in to show name and title on `/verify` (REQ-PROV-02 card), e.g. `proposals.verify_shows_owner`.

Compatibility with schema v2 round 3, checked against `backend/src/bridge/provenance/service.py`: the only
`app_subject_digest` call (line 320, `hash_manifest`) runs as `bridge_app` bound to the owner (line 270) for the
owner's own id, which the caller-bound function allows; the only `provenance_records` INSERT (line 348) follows the
`registered` check (line 276) in the same transaction, under the version's advisory lock (line 272).
`tests/integration/provenance/builders.tier2_grantee` sets `email_verified_at`, which round 3's `app_tier2_granted`
requires.
