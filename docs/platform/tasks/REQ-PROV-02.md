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

## Notes (P8 frontend, branch `feat/REQ-DIR-01-screens`)

Built (F3, public):

- `/verify`: a plain GET form for the certificate id (spaces, hyphens and lower case tidied; `/verify?id=…` redirects
  to `/verify/{id}`, a malformed id shows the field error with no request) and "Check a file" against every
  registered record (`POST /api/verify`, raw body through `withCsrf`, 10 MB checked first).
- `/verify/{cert_id}`: rendered on the server from `GET /api/verify/{cert_id}`: status (icon + words + colour),
  SHA-256 fingerprint (eight groups, monospace columns, copies as one string), timestamp in Nairobi time and UTC, TSA
  serial, key id, signature, the `.tsr` download and the published keys, the 6.4 footer verbatim, and never the owner
  or the title (D-33 default). "Check a file" against this certificate is the page's primary action. Unknown id,
  throttling (429) and API failure are one sentence and one action. `noindex`.
- Files: `frontend/app/(public)/verify/` (pages, `VerifyShell`, `VerifyRecord`, `Fingerprint`, `FileCheck`,
  `certificate.ts`, `lookup.ts`, `upload.ts`, tests), `frontend/e2e/verify.spec.ts`, `frontend/e2e/support/screen.ts`.
  Copy `verify.*`, `verifyFile.*` is `[[COPY-REVIEW]]` (`_meta.reviewP8`); Swahili drafts `[[SW-REVIEW]]`.

Shared files changed: `frontend/lib/api/server.ts` (exports `serverApi`; `forwardHeaders()` forwards the session
cookie and a pattern-checked X-Forwarded-For), `frontend/next.config.ts` (rewrite of
`/.well-known/provenance-keys.json` to the API, tested in `next.config.test.ts`), `frontend/components/ui/Button.tsx`
(`standaloneLinkClass`: own 44 px band for links on their own line).

Follow-ups, not built:

- `E2E_VERIFY_CERT_ID`: the registered-certificate Playwright test skips without it (no certificate exists on a stack
  until T2.3 publishing). Remove the skip once P9's demo seed exports a certificate id for E2E.
- The "matching file" Playwright test stubs `POST /api/verify` (the plaintext manifest is only reachable through the
  owner's download); a real match end to end comes with P2/P9 data.
- THREAT_MODEL note to add: the Phase 8 edge proxy must overwrite X-Forwarded-For (Next.js keeps a client-sent value),
  and only then may TRUSTED_PROXIES list the web hop; until then the public /verify limits are per web server in dev.
- JS budget: `/verify` and `/verify/{id}` measure about 145 KB gzipped of 150 KB; add the Lighthouse CI budget
  (AC-UX-3) before the next screen.
- Owner opt-in to show name and title (D-33) needs the schema column first.
