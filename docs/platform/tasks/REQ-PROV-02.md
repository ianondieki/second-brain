# REQ-PROV-02

- Task: T2.4 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (certificate, verify API), impl-frontend (`/verify`, F3); security-reviewer (Fable)
- Files owned: `bridge/provenance/{certificate,verify,router}.py`, `copy/banned_claims.txt`, `scripts/copy_lint.py`, `scripts/test_copy_lint.py`, `frontend/app/(public)/verify/`
- Depends on: T2.1; the copy-lint can land first.

## Scope

Authorship certificate PDF on demand (never stored): cert id, owner (legal name only if D2), UTC and EAT time, hash, signature and key id, TSA serial, attachment hashes, QR to `/verify/{cert_id}`, and the fixed footer from `docs/spec/06` 6.4 item 2. Public `/verify/{cert_id}` (lookup) and `/verify` (upload a file, recompute its hash, match/no-match), showing only hash, timestamp, TSA serial and match unless the owner opted in to name and title; rate limited. `/.well-known/provenance-keys.json` from `provenance_keys`. Offline guide (`docs/runbooks/verify-offline.md`: `openssl ts -verify`). Banned-claims copy-lint (`copy/banned_claims.txt`: "theft-proof", "cannot be stolen", "protected idea", "patented"; the Approve/approved co-occurrence rule for `engagement.*`, `tracker.*`, `email.em2.*`) over locales, email and Jinja templates and frontend strings, as a `pr.yml` step and in `make check`.

## Acceptance criteria and tests

AC-IP-4 (`scripts/test_copy_lint.py`), AC-IP-1 (`unit/provenance/test_certificate.py`).

## Notes (T2.4, backend implementation)

Built: `bridge/provenance/{certificate,verify,router}.py`, `docs/runbooks/verify-offline.md`. The `/verify` page (F3)
follows in the frontend batch. Deviations:

- `/verify` shows the hash, the timestamp, the TSA serial and the status, plus the Ed25519 signature, its key id and a
  `.tsr` download (`GET /api/verify/{cert_id}/timestamp.tsr`): none is personal data, and offline verification needs
  them (approved by the human in T2.4 review round 1). The owner opt-in to show name and title is **not built**: it needs a schema column (e.g.
  `proposals.verify_shows_owner boolean` or per version) from db-migrations; until then `/verify` never shows them.
- Upload matching (`POST /api/verify`) takes the raw file as the request body (no multipart dependency), up to 10 MB,
  optionally against one `cert_id`. Lookups (30/min) and uploads (10/min) are limited per client IP on the
  login-attempt ledger (`bridge.auth.throttle`).
- `/.well-known/provenance-keys.json` is a JWK set (RFC 8037 `OKP`/`Ed25519`, plus a PEM copy per key) served by the
  API outside `/api`: the web server (Next.js rewrites now, Caddy in Phase 8) must route that path to the API.
- Added an owner-only `GET /api/provenance/certificates/{cert_id}/manifest.json` (the registered manifest, decrypted
  as `tier2_reader` after the ownership check) so owners can hand the exact bytes to anyone checking offline; the
  certificate is `GET /api/provenance/certificates/{cert_id}/certificate.pdf`. Both answer 404 to anyone else.
- The certificate uses the PDF base font Helvetica (Latin-1): names outside Latin-1 need an embedded font later.
  Labels are `[[COPY-REVIEW]]`; the footer is the spec text verbatim.
