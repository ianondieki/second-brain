# ADR-006: Payments, invoicing and tax

- Status: PROPOSED (human may veto at G0)
- Date: 2026-09-24
- Spec: docs/spec/05-subscriptions-billing.md, docs/spec/04-principles.md (4.8), docs/spec/10-security-privacy-compliance.md (item 6)
- Related: ADR-008 (Release 2/3 rails), GATES.md (G3 prices, G4 live keys), THREAT_MODEL.md (Payments)

## Context

Subscriptions are the only money the platform touches; project funds move off-platform (National Payment System
Act 2011, no custody). Kenyan buyers pay by M-Pesa; cards must never touch platform servers. KRA eTIMS invoicing
is required before any paid plan goes live.

## Decision

1. **Rails behind `PaymentProvider`**: (a) M-Pesa Daraja STK Push per prepaid period (renewal reminder 3 days before, retries day 1/3/5, 7-day grace, then downgrade with data kept and over-quota items hidden); (b) cards only via Paystack hosted Checkout with tokenised recurring (store only `authorization_code`, last4, brand; PCI SAQ-A); (c) invoice/bank transfer for Enterprise/Government, marked paid by admin. M-Pesa Ratiba is Release 2. Stripe is excluded (no Kenyan merchant onboarding).
2. **Callbacks never activate anything alone**: Daraja — look up the platform-created `CheckoutRequestID`, check amount/shortcode/account reference, confirm via STK Push Query before any state change, unguessable per-request callback path; Paystack — verify HMAC-SHA512 signature, then `GET /transaction/verify/:reference`. Idempotency via `webhook_events(provider, event_id)` unique; amounts as `bigint` KES minor units; `billing.mpesa_reconcile` every 10 minutes for pending requests plus the nightly Daraja Transaction Status reconciliation.
3. **Entitlements** are enforced server-side on every gated action from `backend/config/plans.yaml` (placeholder prices until G3; VAT 16% inclusive for individuals, exclusive for orgs); 402 responses carry the upgrade path. Tagging claimed orgs within caps is never gated behind another paid feature (AC-SUB-5). A full unlock = first Tier-2 `disclosure_grant` on an untagged proposal per org per billing month.
4. **Invoicing**: `InvoiceIssuer` with sequential invoice numbers and KRA eTIMS (OSCU/VSCU or approved integrator; `researcher` confirms current requirements with citations before Phase 6); VAT charged only once registered. Subscription states `trialing → active → past_due(grace) → downgraded | cancelled`; one-click cancellation; renewal reminder 7 days before auto-renew (Consumer Protection Act 2012); published refund policy; admin refunds recorded against the original payment.
5. **Environments**: Daraja sandbox and Paystack test keys only, in `.env`, until G4; live keys go directly into SSM by the human. `FakePaymentProvider` in CI and staging; `respx` cassettes for Daraja/Paystack.

## Alternatives considered

- Stripe: rejected (no Kenyan merchant onboarding).
- Holding project funds / escrow / success fees: rejected in Release 1 and 2 (custody of funds needs a licensed PSP partner; Release 3 only via a CBK-licensed partner).
- Card data on platform (SAQ-D): rejected; hosted checkout keeps PCI scope at SAQ-A.
- Activating subscriptions on callback receipt: rejected; callbacks are forgeable (AC-SUB-3, AC-SUB-6).

## Consequences

- Phase 6 needs G3 values and eTIMS research before live; launch can run free + anchor plans with manual invoicing until G4 (Release 1 note in `docs/spec/11`).
- `billing/` is a security-reviewer path; coverage ≥95%.
- Daraja shortcode/passkey and Paystack secret are human-entered secrets; agents never see production values.
