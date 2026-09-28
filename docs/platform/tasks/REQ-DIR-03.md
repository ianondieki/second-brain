# REQ-DIR-03

- Task: T2.6b (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend; impl-frontend (claim flow, admin queue, F1); security-reviewer (Fable) (tenancy)
- Files owned: `bridge/directory/{claims,verifier,domains,dns}.py`, `bridge/admin/claims.py`, `frontend/app/(app)/org/claim/`, `frontend/app/(admin)/`
- Depends on: T2.1, T2.6a.

## Scope

Claim flow. E1: domain-email OTP plus a DNS TXT record (`DnsResolver` interface, fake in tests); free-mail domains, punycode (`xn--`) and homoglyph/confusable lookalikes of listed domains are blocked; on a seeded org E1 is automatic only when the domain is in `official_domains[]`, otherwise manual review, as is any claim on an org with a pending or E1 claim. E1 badge, no Brief publishing, no proposal access. E2: `EntityVerifier` interface with `ManualReviewVerifier` only (never fake BRS/KRA calls): BRS registration + CR12 ≤3 months, KRA PIN, sector register, `.go.ke` + official letter sets `public_entity`, authorised-signatory letter, Master Enterprise Terms accepted by the Signatory against the `[[LEGAL-PLACEHOLDER]]` template with its hash (`legal_acceptances`); admin claim queue with the 2 BD SLA shown. Competing claims open a `moderation_cases` row (`claim_dispute`), never an automatic transfer. Annual re-verification date set on E2. On E2 approval held tags become `delivered` (Phase 3 derives the `SUBMITTED` engagements, AC-PROP-1/b).

## Obligations from the schema v2 reviews (T2.1 rounds 2–3; `REQ-REPO-01.md` refinements, `THREAT_MODEL.md`)

- DNS half of E1: resolve only the claim's own domain, compare the TXT token exactly (`dns_token`, written with the claim and write-once), use a validating resolver, then call `app_mark_claim_dns_verified(claim)`; bridge_app cannot write `dns_verified_at` itself. The database trusts this lookup (Medium residual).
- Refuse free-mail, punycode and homoglyph domains before inserting a claim (the self-signup branch of `app_approve_claim_e1` consults no list).
- OTP digests are HMAC-SHA-256 under the server pepper; compare only in SQL (`app_confirm_claim_otp`, `app_reissue_claim_otp`); bridge_app never reads `otp_hash`.
- Competing claims: move them to `disputed` and file the case with `app_open_moderation_case(..., 'claim_dispute', ...)` (bridge_app inserts only user reports). Upholding a dispute (`app_decide_claim` on a disputed claim) removes the earlier approved claimants' memberships; other owners and their open invitations are the uphold action's job (see the T2.1 round-3 review); upholding against an E2 organisation is closed pending D-30.
- E2 approval needs the current Master Enterprise Terms accepted by the claimant (`app_current_legal_template`); the E2 badge copy is pending D-31.

## Acceptance criteria and tests

AC-DIR-2, AC-DIR-7, the AC-DIR-6 NGO clause (`integration/directory/test_claims.py`).
