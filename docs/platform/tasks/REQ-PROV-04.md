# REQ-PROV-04

- Task: T2.10 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend, impl-integrations (`SmsProvider`, `KycProvider`); impl-frontend (F4)
- Files owned: `bridge/profiles/verification.py`, `bridge/integrations/{sms,kyc}.py`, `bridge/jobs/kyc_purge.py`, `docs/runbooks/verification.md`
- Depends on: T2.1.

## Scope

D1 phone OTP through `SmsProvider` (Fake in dev, test and CI; an Africa's Talking adapter behind the interface, never called from tests; vendor account at G1): E.164 normalisation of Kenyan numbers, hashed OTP, 5 attempts, 10-minute expiry, throttled sends. D1 is required to publish and to tag (AC-IP-5, 403). D2 `KycProvider` `ManualReview` (D-19: the human reviews): ID images uploaded to the separate `kyc-review` bucket (in-memory fake in tests), visible only to staff admin, never logged, keys never in logs or `audit_events`; the staff decision stores reference, verified legal name, ID type, last 4 digits, `is_adult` and result; the `kyc.purge` job deletes the images 72 h after the decision. Users 18+.

## Acceptance criteria and tests

AC-IP-5 (`integration/profiles/test_verification.py::test_d1_required`), AC-IP-9 (`integration/profiles/test_verification.py::test_kyc_purge`).

## Notes (T2.10a: D1 only)

- Built: `bridge/integrations/sms.py` (`SmsProvider`, `FakeSmsProvider`, `AfricasTalkingSmsProvider`, `sms_provider_from_settings`), `bridge/profiles/verification.py` (normalisation, code issue and confirm, `require_d1` / `D1Developer`, `SmsDep`), routes `POST /api/me/verification/phone` and `POST /api/me/verification/phone/{verification_id}/confirm` in `bridge/profiles/router.py`, settings `SMS_PROVIDER`, `AFRICASTALKING_USERNAME`, `AFRICASTALKING_API_KEY`, `AFRICASTALKING_SENDER_ID` (`backend/.env.example`). The API builds its `SmsProvider` at start-up: `fake` is refused in production, `africastalking` in `APP_ENV=test`, and production refuses the `sandbox` account.
- Deferred: D2 (`KycProvider` `ManualReview`, the `kyc-review` bucket, `bridge/jobs/kyc_purge.py`, AC-IP-9 `test_kyc_purge`) needs the object store of T2.4 and follows as T2.10b. `docs/runbooks/verification.md` is written with D2.
- AC-IP-5: no registration route exists yet (T2.3). `REQ-PROP-01.md` (publish) and `REQ-PROP-03.md` (tag) carry the D1 requirement and their real-route test ids. `integration/profiles/test_verification.py::test_d1_required` mounts a test-only registration route guarded by `D1Developer`, exactly as the publish route will use it. T2.3 (publish) and T2.7 (tag) must take `profile: D1Developer` (or `dependencies=[Depends(require_d1)]`), and T2.3 repoints `test_d1_required` at the real route.
- Code digest (schema v2 security review): HMAC-SHA-256 under `SECRET_KEY`, purpose `phone_otp`, bound to the row id; the insert returns only `expires_at`; `bridge_app` holds no SELECT on `otp_hash` and the ORM maps it deferred with raiseload, so Python never reads it back; the comparison stays in `app_confirm_phone_otp`. The database sets `expires_at` (trigger: now() + 10 minutes) and decides expiry by its own clock; the application clock refuses nothing. Audit payloads take SHA-256(subject_salt || number) from `app_subject_digest` (`bridge_app` cannot read `users.subject_salt`).
- Choices not fixed by the spec: send limits (1 per user a minute; 3 per user or number and 30 per IP in 15 minutes; 5 per user or number and 100 per IP a day) on the `login_attempts` ledger, counted under the profile row lock (one user) and transaction-level advisory locks on the number's and the client IP's digests (every account), taken in one order (profile row, then the two keys ascending) and released at COMMIT; the code row, throttle records and audit event are committed before the SMS leaves (a failed send is 503 `sms_unavailable` and counts against the limits); a D1 or higher profile neither asks for nor confirms a code, including an open code for another number (409 `already_verified`, checked under the profile row lock; `app_confirm_phone_otp` also matches only a D0 profile).
- The SMS wording is `[[COPY-REVIEW]]` and names the working name "Bridge". Africa's Talking fields and status codes follow the vendor's SMS documentation; confirm against the account at G1 (no vendor was contacted).
- Open: should one number verify at most one account (needs a definer function, db-migrations)? The dev stack's fake keeps codes in API memory, so F4 and e2e need a local way to read them (for example a Mailpit SMS sink). `[tool.coverage.run]` lacks `concurrency = ["greenlet", "thread"]`, so pytest-cov under-reports async code (`verification.py` 73% without it, 99% with it).
