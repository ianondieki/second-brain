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
- **Owner ref** = `SHA-256(subject_salt || 16 raw bytes of user_id)`, computed only in `service.subject_digest`, which
  reads `users.subject_salt` today; switch that one helper to `app_subject_digest(p_user_id, p_data)` when the
  revision 0002 fix lands (orchestrator note of 2026-09-28).
- **Version hash fill.** `service._fill_version_hashes` runs as `provenance_worker` when that role holds UPDATE on
  `proposal_versions.content_hash` (the pending 0002 fix) and as the owner-bound `bridge_app` otherwise; remove the
  fallback once the fix is merged. Every step binds the version owner, and Tier 2 and records are touched only as
  `provenance_worker`, so the planned owner-scoped RLS on `provenance_records` needs no code change.
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
- Coverage: `bridge/provenance` 99% (`uv run pytest --cov=bridge.provenance`); `[tool.coverage.run]` now traces
  SQLAlchemy's greenlets (`concurrency = ["greenlet", "thread"]`), which also lifts the measured coverage of every
  route handler.
- For db-migrations (not blocking): an index on `provenance_records.content_hash` (upload matching without a cert id
  scans the table today).
