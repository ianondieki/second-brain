## 5. Subscriptions & billing

Two sides, two plan families. Prices are **placeholders in `backend/config/plans.yaml`** (not code) until gate G3. KES, VAT 16% (inclusive for individuals, exclusive + VAT for orgs). Entitlements are enforced server-side on every gated action. **There is no per-submission or per-tag fee: within the plan's tag and active-proposal caps, tagging a claimed org is never gated behind any other paid feature.** Browse repo (Tier-1 keyword search + filters) is on every org plan. A **full unlock** is the first Tier-2 `disclosure_grant` on an untagged proposal to an org in a billing month, checked when the grant is created (402 over quota; tagged proposals never count). `FEATURE_DEALS_ENABLED` gates entry to stages ≥5, `SignatureProvider` and payment records. `plans.yaml` also holds `llm_monthly_cap_usd`, allowed scout frequencies and progress-digest cadence per plan. "Liked niches" (3–5, all plans) drive ranking; "followed niches" (capped per plan) drive trending alerts and the digest line.

| Side | Plan | Placeholder price | Entitlements |
|---|---|---|---|
| Developer | Free | KES 0 | 3 active proposals; 5 tags per proposal; 1 followed niche; weekly trending; disclosure certificate per version; tracker + daily email reminders |
| Developer | Pro | KES 499/mo or 4,990/yr | Unlimited proposals; 20 tags per proposal; 5 followed niches; personalised recommendations with explanations; viewer analytics (aggregates; the per-viewer log is free for every owner); WhatsApp reminders (opt-in, Release 2) |
| Developer | Student | KES 0, Pro features 12 mo | Verified Kenyan university/TVET email |
| Org | Claimed (Free) | KES 0 | Verified profile; receive & respond to tagged proposals; 1 scout agent (weekly, top 3 matches); 5 full unlocks/mo (proposals tagged to the org do not count); 2 seats; 1 Problem Brief; tracker; weekly progress digest |
| Org | Starter | KES 15,000/mo | 1 scout agent (weekly, full digest); 25 unlocks/mo; 5 seats; 5 Briefs; daily progress digest |
| Org | Growth | KES 45,000/mo | 5 scout agents (daily/weekly/on_new); unlimited unlocks; 20 seats; unlimited Briefs; CSV export; daily digest; pipeline analytics (Release 2, shown as "coming soon") |
| Org | Enterprise / Government | Custom, invoice/LPO, net-30 | SSO (Release 2), custom NDA template, procurement-friendly invoicing |
| Org | Social Impact | 50–100% off Starter/Growth | Verified NGOs/PBOs, public schools, public universities/TVETs, county governments; admin-approved |

Anchor orgs in wedge niches get Growth free for 90 days (coupon).

**Rails, behind a `PaymentProvider` interface:** M-Pesa Daraja STK Push per prepaid period (reminder 3 days before renewal; retries day 1/3/5; 7-day grace; then downgrade to the free tier, data kept, over-quota items hidden); M-Pesa Ratiba (Release 2); cards only via Paystack hosted Checkout (tokenised recurring; no PAN/CVV touches platform servers or logs, PCI SAQ-A; store only `authorization_code`, last4, brand); invoice/bank transfer for Enterprise/Government, marked paid by admin. Stripe excluded (no Kenyan merchant onboarding). **Callbacks never activate anything alone:** Daraja — look up the platform-created `CheckoutRequestID`, check amount/shortcode/account reference, confirm via the STK Push Query API before any state change, unguessable per-request callback path; Paystack — verify the HMAC-SHA512 signature, then `GET /transaction/verify/:reference`. Idempotent (`webhook_events(provider, event_id)` unique), amounts in `bigint` KES minor units, sequential invoice numbers, nightly Daraja Transaction Status reconciliation. **KRA eTIMS** invoicing (OSCU/VSCU or approved integrator) is required before any paid plan goes live, VAT-registered or not (Finance Act 2023; researcher confirms with citations); VAT charged only once registered. Subscription states: `trialing → active → past_due(grace) → downgraded | cancelled`. One-click cancellation; renewal reminder 7 days before auto-renew (Consumer Protection Act 2012).

| AC | Criterion |
|---|---|
| AC-SUB-1 | Given a Free developer with 3 active proposals, When they publish a 4th, Then the API returns 402 with the upgrade path and nothing is created. |
| AC-SUB-2 | Given a duplicate Daraja callback for the same `CheckoutRequestID`, Then the second is a no-op and the subscription is activated exactly once. |
| AC-SUB-3 | Given a forged Paystack webhook signature, Then it is rejected with 401 and logged. |
| AC-SUB-4 | Given an org in grace whose renewal fails for 7 days, Then it is downgraded to Claimed: scouts beyond the first pause, the remaining one switches to weekly top 3, over-quota items are hidden, no data is deleted. |
| AC-SUB-5 | A Free developer's 1st–5th tags to claimed orgs never return 402 and unlock no further paywall (NDA, tracker, messaging); AC-SUB-1 and AC-PROP-2 remain the cap tests. |
| AC-SUB-6 | A well-formed but forged Daraja success callback for a real `CheckoutRequestID`, where the STK Push Query fake returns failed or pending, activates nothing and is logged. |
| AC-SUB-7 | A Claimed org with 5 unlocks this month gets 402 on a 6th grant for an untagged proposal, while a grant on a proposal tagged to it succeeds. |
