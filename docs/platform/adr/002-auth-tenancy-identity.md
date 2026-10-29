# ADR-002: Authentication, tenancy and identity providers

- Status: PROPOSED (human may veto at G0)
- Date: 2026-09-24
- Spec: docs/spec/03-glossary-roles.md (roles), docs/spec/06-feature-modules.md (6.4 item 8, 6.1 predicate), docs/spec/08-architecture-stack-data-model.md (Auth, Tenancy)
- Related: ADR-003, ADR-007, THREAT_MODEL.md (Auth, Tenancy)

## Context

Two sides (developers, organisations) plus platform staff share one database. Tier-2 proposal content must be
unreadable across tenants even if application code has a bug. Organisation seats need MFA; developers need
graded verification (D0–D3) that gates publishing, tagging, deal rooms and signing.

## Decision

1. **Backend-owned auth** (no third-party identity SaaS in Release 1): argon2id passwords (m=64 MiB, t=3), magic links, GitHub OAuth (also used for opt-in repo import), Google OAuth. Server-side sessions in Postgres; cookie `httpOnly; Secure; SameSite=Lax`; CSRF double-submit token on state-changing requests.
2. **MFA**: TOTP mandatory for org `owner`, `admin`, `signatory`, `reviewer`, for D2 developers and for all staff. TOTP or passkey **step-up** (last MFA ≤12 h) for signing, endorsements, payment confirmations, disclosure-policy changes, manual grants and raw-download enablement. SMS OTP is only a fallback for signing with a 24 h delay and notice to the other party.
3. **Roles** exactly as the glossary: org members `owner | admin | reviewer | signatory | finance | viewer`; staff `admin | moderator | support` (support read-only, impersonation off by default and always audited). Developer verification levels D0 email, D1 phone OTP via `SmsProvider`, D2 KYC via `KycProvider` (`ManualReview` by staff `admin` in Release 1; vendor in Release 2), D3 self-reported registry numbers. Org verification E0 unclaimed, E1 domain-verified, E2 legal-entity-verified via `EntityVerifier` (`ManualReviewVerifier`; never faked BRS/KRA calls).
4. **Tenancy = Postgres Row-Level Security** on every org-scoped table, driven by `SET LOCAL app.user_id / app.org_id` per transaction (jobs set one tenant each), plus `require_role` FastAPI dependencies. No app or worker role has `BYPASSRLS` or table ownership; migrations run as a separate owner role. Tier-2 columns live in `proposal_confidential` behind the `tier2_reader` role and the single predicate `can_view_tier2(viewer, version)`. Cross-org aggregates read only `signal_events` under `aggregate_worker`. Error semantics: non-member/non-party 404; member lacking role or precondition 403.
5. **Identity providers**: GitHub and Google OAuth only in Release 1; SSO (SAML/OIDC for Enterprise/Government) in Release 2 (ADR-008).

## Alternatives considered

- Hosted auth (Auth0, Clerk, Supabase Auth): rejected; adds a sub-processor for all personal data, complicates Kenyan data-residency questions (ADR-007) and the RLS session context.
- Application-level tenant filtering only: rejected; a single missed `WHERE org_id` leaks Tier-2 data. RLS is the defence in depth AC-SEC-1 tests.
- JWT access tokens: rejected; server-side sessions allow immediate revocation on suspension and simpler CSRF.
- Automated KYC vendor from day one: rejected; vendor choice and DPA belong to Release 2 (D2 automated), manual review is enough for the anchor-org pilot.

## Consequences

- AC-SEC-1 is generated from table metadata: every new org-scoped table needs an RLS policy in its migration or the parametrised test fails.
- Staff impersonation writes an audit event and notifies the owner (AC-ADM-3).
- OAuth apps (GitHub, Google) need credentials in `.env` (sandbox/test apps only; production values in SSM at Phase 8).
- KYC images never touch logs or `audit_events` and are purged 72 h after decision (AC-IP-9).
