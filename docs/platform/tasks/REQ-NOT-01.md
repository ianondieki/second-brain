# REQ-NOT-01

- Task: T1.7 (`docs/platform/PLAN.md` Phase 1)
- Agent: impl-integrations
- Files owned: `bridge/notifications/`
- Depends on: T1.4.

## Scope

`EmailProvider` protocol with `PostmarkEmailProvider` (httpx; respx-tested, never called in CI), `SmtpEmailProvider` (Mailpit sink in dev and CI), `FakeEmailProvider`; `notification_deliveries` ledger with a dedupe key; at most 3 attempts with the transient/permanent classification ported from `reminder/notify.py` `DeliveryError`; `email_suppressions` checked before every send.

## Acceptance criteria and tests

Unit: `backend/tests/unit/notifications/`. AC-MAIL-3 and AC-DIR-1 close in Phases 3 and 2.
