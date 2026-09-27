# REQ-PROV-04

- Task: T2.10 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend, impl-integrations (`SmsProvider`, `KycProvider`); impl-frontend (F4)
- Files owned: `bridge/profiles/verification.py`, `bridge/integrations/{sms,kyc}.py`, `bridge/jobs/kyc_purge.py`, `docs/runbooks/verification.md`
- Depends on: T2.1.

## Scope

D1 phone OTP through `SmsProvider` (Fake in dev, test and CI; an Africa's Talking adapter behind the interface, never called from tests; vendor account at G1): E.164 normalisation of Kenyan numbers, hashed OTP, 5 attempts, 10-minute expiry, throttled sends. D1 is required to publish and to tag (AC-IP-5, 403). D2 `KycProvider` `ManualReview` (D-19: the human reviews): ID images uploaded to the separate `kyc-review` bucket (in-memory fake in tests), visible only to staff admin, never logged, keys never in logs or `audit_events`; the staff decision stores reference, verified legal name, ID type, last 4 digits, `is_adult` and result; the `kyc.purge` job deletes the images 72 h after the decision. Users 18+.

## Acceptance criteria and tests

AC-IP-5 (`integration/profiles/test_verification.py::test_d1_required`), AC-IP-9 (`integration/profiles/test_verification.py::test_kyc_purge`).
