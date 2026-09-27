# REQ-DIR-03

- Task: T2.6b (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend; impl-frontend (claim flow, admin queue, F1); security-reviewer (Fable) (tenancy)
- Files owned: `bridge/directory/{claims,verifier,domains,dns}.py`, `bridge/admin/claims.py`, `frontend/app/(app)/org/claim/`, `frontend/app/(admin)/`
- Depends on: T2.1, T2.6a.

## Scope

Claim flow. E1: domain-email OTP plus a DNS TXT record (`DnsResolver` interface, fake in tests); free-mail domains, punycode (`xn--`) and homoglyph/confusable lookalikes of listed domains are blocked; on a seeded org E1 is automatic only when the domain is in `official_domains[]`, otherwise manual review, as is any claim on an org with a pending or E1 claim. E1 badge, no Brief publishing, no proposal access. E2: `EntityVerifier` interface with `ManualReviewVerifier` only (never fake BRS/KRA calls): BRS registration + CR12 ≤3 months, KRA PIN, sector register, `.go.ke` + official letter sets `public_entity`, authorised-signatory letter, Master Enterprise Terms accepted by the Signatory against the `[[LEGAL-PLACEHOLDER]]` template with its hash (`legal_acceptances`); admin claim queue with the 2 BD SLA shown. Competing claims open a `moderation_cases` row (`claim_dispute`), never an automatic transfer. Annual re-verification date set on E2. On E2 approval held tags become `delivered` (Phase 3 derives the `SUBMITTED` engagements, AC-PROP-1/b).

## Acceptance criteria and tests

AC-DIR-2, AC-DIR-7, the AC-DIR-6 NGO clause (`integration/directory/test_claims.py`).
