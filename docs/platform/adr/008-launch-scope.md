# ADR-008: Launch scope and release scheduling

- Status: PROPOSED (human may veto at G0)
- Date: 2026-09-24
- Spec: docs/spec/01-mission.md (Launch scope), docs/spec/11-delivery-phases.md (Releases), docs/spec/05-subscriptions-billing.md (anchor coupon)
- Related: every DEFERRED row in REQUIREMENTS.md cites this ADR unless a more specific ADR applies

## Context

The original request spans Kenya and East Africa, many niches, WhatsApp, GitHub investigation, advanced e-signature
and learning-to-rank. Building all of it before the first pilot would delay evidence that the core loop works.
Nothing is dropped, only scheduled.

## Decision

1. **Release 1 (this build, before G8)**: Kenya only (47 counties); two wedge niches actively seeded (Microfinance & SACCOs; Higher Education) plus telecom licensees and counties in the directory; all other niches browsable; 10–20 concierge-onboarded anchor orgs on the Growth-free-for-90-days coupon; free and anchor plans with manual invoicing at launch, live Daraja/Paystack/eTIMS once G4 is signed (may follow launch). English UI with complete Swahili keys (live after G5 review). Single-owner proposals. Visible watermarks. Internal simple e-signature for NDAs/EOIs/milestones/acceptance; agreements with IP assignment or exclusive licence signed outside the platform. Milestone-based health (no GitHub App). Hybrid ranker with LTR in shadow mode. Research at national level.
2. **Release 2**: remaining niches seeded, county-level research, invisible watermark marks, OpenTimestamps, KYC vendor (D2 automated), E-CSP advanced e-signature, GitHub App investigator and repo-cold health, WhatsApp reminders and adviser, co-owned proposals, SSO, M-Pesa Ratiba, pipeline analytics, offline tracker, post-disclosure similarity monitor, Swahili live, local companion `--platform`.
3. **Release 3**: LTR activation if thresholds are not reached earlier, East Africa (Uganda, Tanzania, Rwanda: MTN MoMo, Airtel Money, local registries), success fees/escrow only via a CBK-licensed PSP partner, public API, procurement-friendly government flows.
4. **Explicit non-goals**: holding project funds, auto-emailing unclaimed orgs, "theft-proof" claims, black-box ranking, native mobile apps (responsive PWA instead), regions outside Kenya in Release 1.
5. **Scheduling rule**: every `REQUIREMENTS.md` row carries a release; Release 2/3 rows are `DEFERRED` with this ADR (or a more specific one) and keep their schema hooks (e.g., `co_owners`, `ots_proof`, `wa_contacts`) so later releases are additive.

## Alternatives considered

- Launch with WhatsApp and GitHub signals: rejected; both need external approvals (Meta templates, GitHub App review) and consent flows that do not affect the pilot's core hypothesis.
- Launch in Kenya and Uganda: rejected; payments, registries and legal templates differ per country.
- Skip Swahili keys in Release 1: rejected; retrofitting i18n is costlier than shipping keys now.

## Consequences

- The Definition of Done (`docs/spec/14`) applies to Release 1 MUST rows; SHOULD/COULD and R2/R3 rows must be DONE or DEFERRED with an ADR number.
- The directory seeds only public organisational data and starts at E0; G6 approves the production list.
- Anchor-org onboarding is concierge work by the human, not an agent task.
