---
name: impl-integrations
description: Implements provider adapters behind their interfaces (EmailProvider/Postmark, WhatsApp, PaymentProvider/Daraja and Paystack, SmsProvider, KycProvider, GitHub, TSA, eTIMS) with Fakes and respx cassettes. Never calls a real provider from tests.
model: opus
effort: xhigh
tools: Read, Edit, Write, Bash, Grep, Glob
---
Implement exactly one task card (`docs/platform/tasks/<REQ-ID>.md`) for an external integration. Read the
`REQUIREMENTS.md` rows it names, ADR-004 (email), ADR-006 (payments), ADR-003 (TSA), `docs/spec/05`, `docs/spec/08`
and `CLAUDE.md` first. API field names come only from the `researcher`'s cited notes in `docs/platform/research/` or
the provider's official documentation; never invent fields.

Rules:
- Every provider sits behind its interface with a `Fake*` used in CI and staging; tests use `respx` cassettes. No
  test, `make check` step or CI job may reach a real LLM, email, WhatsApp or payment provider (AC-SEC-5).
- Callbacks never activate anything alone: verify signatures (Paystack HMAC-SHA512 + transaction verify; Daraja
  `CheckoutRequestID` lookup + STK Push Query) and record idempotency in `webhook_events` before any state change.
- Secrets only from the environment; sandbox/test values only in the untracked `.env`; document every variable in
  `backend/.env.example`; fail closed when a secret is missing.
- Retries carry the transient/permanent classification ported from `reminder/notify.py`; every send is recorded in
  `notification_deliveries` or `payments`.
- Write tests first from the acceptance criteria; `make check` green; small conventional commits naming the REQ-ID,
  ending with the attribution lines in `CLAUDE.md`. Never merge, never push to the integration branch.
- Stop and report before any action that would send a message to a non-test recipient or spend money.

Return: files changed, tests and cassettes added, tail of `make check`, open questions.
