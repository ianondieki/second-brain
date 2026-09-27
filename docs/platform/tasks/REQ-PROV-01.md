# REQ-PROV-01

- Task: T2.4 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (pipeline), impl-integrations (TSA client); security-reviewer (Fable)
- Files owned: `bridge/provenance/{manifest,signing,tsa,service}.py`, `bridge/jobs/provenance.py`, `backend/tests/unit/provenance/`, `backend/tests/fixtures/tsa/`
- Depends on: T2.1.

## Scope

Registration pipeline, each step an idempotent Procrastinate job: RFC 8785 canonical JSON manifest (all Tier-1 and Tier-2 fields, attachment SHA-256s, owner ref `SHA-256(subject_salt ‖ user_id)`, attestation ids, `prev_version_hash`, `manifest_version`) → `content_hash = SHA-256(manifest)` → Ed25519 signature (`Signer` interface: `LocalSigner` from `PROVENANCE_SIGNING_KEY` in dev/test; `KmsSigner` stub, never called from tests) → RFC 3161 request/response (`TSA_URL`; DigiCert primary, FreeTSA fallback in config only) → `proposal.version_registered` audit event. The encrypted manifest is kept in `proposal_confidential.manifest_ciphertext` and in the `evidence` object store (S3 API; SeaweedFS in dev per D-24; in-memory fake in tests). "Timestamp pending" until the token is stored. Tests use a local `openssl ts` test CA generated at test time; never DigiCert, FreeTSA or KMS.

## Acceptance criteria and tests

AC-IP-1 (`unit/provenance/test_manifest.py` golden fixtures, `test_tsa_openssl.py`: `openssl ts -verify` on the stored `.tsr`), AC-IP-2 (`unit/provenance/test_tamper.py`, `integration/test_audit_chain.py`).
