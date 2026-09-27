# REQ-PROV-02

- Task: T2.4 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (certificate, verify API), impl-frontend (`/verify`, F3); security-reviewer (Fable)
- Files owned: `bridge/provenance/{certificate,verify,router}.py`, `copy/banned_claims.txt`, `scripts/copy_lint.py`, `scripts/tests/test_copy_lint.py`, `frontend/app/(public)/verify/`
- Depends on: T2.1; the copy-lint can land first.

## Scope

Authorship certificate PDF on demand (never stored): cert id, owner (legal name only if D2), UTC and EAT time, hash, signature and key id, TSA serial, attachment hashes, QR to `/verify/{cert_id}`, and the fixed footer from `docs/spec/06` 6.4 item 2. Public `/verify/{cert_id}` (lookup) and `/verify` (upload a file, recompute its hash, match/no-match), showing only hash, timestamp, TSA serial and match unless the owner opted in to name and title; rate limited. `/.well-known/provenance-keys.json` from `provenance_keys`. Offline guide (`docs/runbooks/verify-offline.md`: `openssl ts -verify`). Banned-claims copy-lint (`copy/banned_claims.txt`: "theft-proof", "cannot be stolen", "protected idea", "patented"; the Approve/approved co-occurrence rule for `engagement.*`, `tracker.*`, `email.em2.*`) over locales, email and Jinja templates and frontend strings, as a `pr.yml` step and in `make check`.

## Acceptance criteria and tests

AC-IP-4 (`scripts/tests/test_copy_lint.py`), AC-IP-1 (`unit/provenance/test_certificate.py`).
