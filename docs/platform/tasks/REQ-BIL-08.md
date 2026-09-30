# REQ-BIL-08 (with the REQ-BIL-04 interface)

- Task: P14 Subscriptions, backend half (`docs/platform/PLAN.md` §8 prototype track M2, 5th to cut;
  `docs/platform/prototype-m2-plan.md` §1, §3, §6). The screens (`/billing`, `/billing/upgrade?plan=`, avatar-menu
  entry) are the later P14-F task.
- Agent: impl-backend (xhigh; billing is security-sensitive, D-35); security-reviewer (P14-B is on its list,
  `prototype-m2-plan.md` §5), reviewer.
- Branch: `feat/REQ-BIL-08-payments`, from `feat/REQ-SCOUT-01-schema-0005` at `1da7349` (revision 0005). No Alembic
  revision: the schema is 0005's (`payments`, `app_settle_payment`, `app_activate_paid_subscription`, `payments_guard`).
- Files owned: `bridge/billing/providers/{__init__,base,fake}.py`, `bridge/billing/{checkout,router}.py`, the
  purchasable and sample-price helpers in `bridge/billing/plans.py`, the payment settings in `bridge/config.py`,
  `bridge/seed/demo/subscriptions.py`, two router lines in `bridge/main.py`, `backend/.env.example` (Payments),
  `backend/tests/unit/billing/{test_fake_provider,test_plans}.py`,
  `backend/tests/integration/billing/{conftest,checkout_helpers,test_checkouts,test_checkout_tenancy,test_upgrade_caps,test_demo_subscriptions}.py`.
- Depends on: revision 0005 (REQ-SCOUT-01 card: the payments sections, "Operating rules for P10, P11, P12 and P14",
  "Blocker before REQ-BIL-04"); REQ-BIL-01 (plans, entitlements, the 402 upgrade path); REQ-BIL-02 (the caps).
- Decisions applied: D-36 (zero spend: `FakePaymentProvider` only, no Daraja or Paystack code or accounts, no phone
  numbers); D-44 recommended default (a): `sample_prices` so the UI shows "Sample prices, not final" `[[COPY-REVIEW]]`,
  and `simulated_checkout` / `simulated` so it labels the checkout "Simulated M-Pesa".

## Scope

Plans page data, one checkout of a paid plan per subject at a time, the simulated M-Pesa rail behind the
`PaymentProvider` interface of docs/spec/05, activation of the paid plan with entitlements that follow at once, and
a demo seed that pays for nothing. Not in scope (REQ-BIL-04..07 after the prototype): Daraja, Paystack, callbacks
and `webhook_events`, renewals and grace, invoices and eTIMS, Student verification, Social Impact approval, the
anchor coupon.

## Design

**Interface (`providers/base.py`).** `PaymentProvider` with `name`, `simulated`, `initiate(CheckoutRequest, now)` →
`Initiated`, `query(provider_ref, now)` → `QueryResult(status, amount_kes_minor, failure_code)`,
`verify_callback(headers, body)` → `CallbackVerification(verified, provider_ref, event_id)`. `now` is the app clock
(`app_clock_now()`), passed by the caller; a real rail ignores it. `PaymentProviderError(code, transient)` carries the
transient/permanent split of `reminder/notify.py`. Only `query` settles; a verified callback only names the checkout
to query (docs/spec/05, ADR-006 point 2).

**Fake (`providers/fake.py`).** Keeps each checkout in memory (at most 10,000, oldest first out): the app-clock start,
the amount and the scripted outcome. `query` answers pending until `FAKE_PAYMENT_DELAY_SECONDS` (default 4, 0–300)
have passed on the app clock, then the outcome. The outcome is the checkout's `simulate` field: `succeed` (default),
`fail` (`insufficient_funds`), `cancel` (`cancelled_by_customer`). This replaces the brief's "magic plan code or phone
suffix" idea: the catalogue stays the real one and no phone number is ever asked for. An unknown reference (the API
restarted) answers failed `unknown_checkout`, never succeeded and never pending for ever. `verify_callback` refuses
everything (the fake is polled only).

**Settings.** `PAYMENT_PROVIDER` (`fake`; empty = the fake in dev and test, none in staging and production) and
`FAKE_PAYMENT_DELAY_SECONDS`, documented in `backend/.env.example`. `PAYMENT_PROVIDER=fake` in staging or production
stops the process at start-up; `payment_provider_from_settings` refuses the fake outside dev and test again (settings
built without validation); no provider answers 503 `not_configured` on checkout start (fail closed); a checkout is
still shown, without a provider query. Deviation from ADR-006 point 5 ("FakePaymentProvider in CI and staging"): the
brief and D-36 refuse the fake in staging; staging has no payment rail until REQ-BIL-04.

**Routes (`billing/router.py`, registered in `main.py`).**

| Route | Who | Answer |
|---|---|---|
| `GET /api/plans?side=` | anyone (prices and limits are not personal) | `plans.yaml` in order, per plan `purchasable` and `upgrade_to`; `sample_prices` (true until `plans.yaml` `status: final`), `simulated_checkout` |
| `POST /api/billing/checkouts` `{plan_code, org_id?, simulate?}` | the developer (a developer profile), or an organisation's owner, admin or finance member | 201 new pending checkout; 200 the subject's checkout of that plan in progress |
| `GET /api/billing/checkouts/{id}` | the subject only | the checkout, after asking the provider and settling and activating on a final answer; `poll_after_seconds: 2` while pending |

Refusals (fixed messages, stable codes): 422 `plan_not_available` (unknown, default, free, custom-priced, approval or
eligibility plan: only `dev_pro_monthly`, `dev_pro_yearly`, `org_starter`, `org_growth` are sold); 422
`plan_wrong_side`; 403 `not_a_developer`; 404 to a non-member of `org_id`, 403 `forbidden` to a member without a paying
role; 409 `already_on_plan`; 409 `checkout_pending` with `checkout_id` (another plan's checkout in progress); 422
`simulation_not_available` (`simulate` with a non-simulating provider); 422 on any unknown body field (no id,
`provider_ref`, amount or subject from the client); 502 `payment_provider_error` (the provider could not start it: the
payment is settled failed `provider_unavailable` or `provider_refused`); 503 `not_configured`. The organisation's
second-factor rules apply (an owner or admin session without the second factor gets 401 `mfa_required`). No step-up:
M-Pesa confirms on the phone and the fake moves no money (ADR-002's "payment confirmations" are the tracker's).

**Service (`billing/checkout.py`).** Start: the plan from the catalogue (`PlanSpec.purchasable`) and from the `plans`
row (active, non-default, the side, price > 0); the subject's advisory lock (`checkout:<subject>`); each of the
subject's pending checkouts is refreshed first (a finished one no longer blocks); the current plan is refused; the
payment is inserted pending at the row's price with `provider_ref = chk_ + token_urlsafe(24)`, audited
`billing.checkout_started` and committed before `initiate` (a callback or query can find it). Refresh: only a pending
payment of this provider is queried; a final answer settles through `app_settle_payment` (in a savepoint: a concurrent
different outcome keeps the first); a success for any amount but the payment's settles as failed `amount_mismatch`; a
succeeded, unlinked payment is activated through `app_activate_paid_subscription`; the settlement is audited once
(`billing.checkout_settled`, when the definer returns true). Settlement and activation share one transaction.
Entitlements read the live subscription, so the new plan's limits apply on the next request.

**Demo seed (`bridge/seed/demo/subscriptions.py`).** `seed_demo_subscriptions(conn, settings)`: demo developers
(`users.demo_account` with a developer profile) and organisations with an active demo member get their side's free
plan when they have no live subscription; nothing paid. P9's re-seed rule: a live subscription is never touched (a
walkthrough upgrade, or P10's Growth for a fixture organisation, stays), no payment is written; dev and test only. A
fresh walkthrough needs `make demo-reset`.

## Acceptance criteria and tests

The brief's items, each with its tests (all on the fake; nothing reaches a network):

| Item | Tests |
|---|---|
| Interface, fake, delay on the caller's clock, outcomes, callbacks refused | `unit/billing/test_fake_provider.py` (19) |
| D-36: fake refused in staging and production, none when unset, the builder's second fence, bounded delay | the same |
| Catalogue: sold plans, sample prices, platform references | `unit/billing/test_plans.py` (11) |
| Every route and refusal, failed and cancelled outcomes, the delay on the test clock, unknown reference, provider errors, amount mismatch, no provider | `integration/billing/test_checkouts.py` (30) |
| Tenancy: another subject's checkout is 404 and never settled by their read; paying roles; other organisations; the second factor | `integration/billing/test_checkout_tenancy.py` (7) |
| Idempotent activation under parallel reads (one app; two payers) and parallel starts | the same |
| After activation the caps allow more: publish past 3 (AC-SUB-1 re-run), pitch past 5 tags, 5 scout agents on Growth | `integration/billing/test_upgrade_caps.py` (3) |
| Demo seed: free by default, re-seed keeps the upgrade, no payment, dev and test only | `integration/billing/test_demo_subscriptions.py` (3) |

AC-SUB-2's shape (a repeated answer activates once) holds for polls here; AC-SUB-2, AC-SUB-3 and AC-SUB-6 as written
(Daraja and Paystack callbacks) stay with REQ-BIL-04 and REQ-BIL-05. AC-SUB-4 (grace downgrade) stays with REQ-BIL-06.

### Mutation proofs

Each proof breaks one guard, runs the named test (red), and restores the file byte for byte (`git status` clean after
the batch). Runner: a scratch script replacing one exact string per proof; command in `backend/`:
`TEST_DATABASE_ADMIN_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/postgres .venv/bin/python -m pytest -q -p no:cacheprovider -x <test>`.

| Proof | Guard broken | Test (red) |
|---|---|---|
| P1 | `CheckoutIn` refuses unknown fields | `test_checkouts.py::test_the_client_never_supplies_an_id_reference_or_amount` |
| P2 | start: the organisation's paying roles (`payer_of_org`) | `test_checkout_tenancy.py::test_an_organisations_plan_is_paid_by_its_owner_admin_or_finance_members` |
| P3 | start: the subject's advisory lock | `test_checkout_tenancy.py::test_parallel_starts_of_one_plan_make_one_payment` (four 201s; red 3 of 3 runs) |
| P4 | the same plan's checkout in progress is answered again | `test_checkouts.py::test_a_checkout_in_progress_is_answered_again_and_blocks_another_plan` |
| P5 | a success for another amount never activates | `test_checkouts.py::test_a_success_for_another_amount_never_activates` |
| P6 | the fake's delay | `test_checkouts.py::test_the_delay_runs_on_the_app_clock` |
| P7 | settings: `PAYMENT_PROVIDER=fake` refused in staging and production | `test_fake_provider.py::test_staging_and_production_refuse_the_fake_at_start_up` |
| P8 | builder: the fake only in dev and test | `test_fake_provider.py::test_the_builder_refuses_the_fake_even_past_the_settings_check` |
| P9 | unset is no provider outside dev and test | `test_fake_provider.py::test_staging_and_production_have_no_provider_when_unset` |
| P10 | `simulate` needs a simulating provider | `test_checkouts.py::test_a_simulated_outcome_needs_a_simulating_provider` |
| P11 | the current plan is not sold again | `test_checkouts.py::test_the_current_plan_is_not_sold_again` |
| P12 | pending checkouts are refreshed before a new start | `test_checkouts.py::test_a_pending_checkout_that_has_ended_no_longer_blocks` |
| P13 | `purchasable`: price above zero | `unit/billing/test_plans.py` |
| P14 | the plan's side (the INSERT policy then answers 500) | `test_checkouts.py::test_a_plan_of_the_other_side_is_refused` |
| P15 | an unknown reference fails | `test_checkouts.py::test_a_checkout_the_provider_never_started_fails_instead_of_staying_pending` |
| P16 | demo seed: only subjects without a live subscription | `test_demo_subscriptions.py::test_demo_subjects_start_free_and_a_reseed_keeps_what_the_walkthrough_bought` |
| P17 | demo seed: dev and test only | `test_demo_subscriptions.py::test_the_demo_seed_refuses_outside_dev_and_test` |
| P18 | a succeeded checkout activates its plan | `test_checkouts.py::test_a_checkout_starts_pending_at_the_plans_price_and_settles_on_the_providers_answer` |
| P19 | read: the organisation's second-factor rules | `test_checkout_tenancy.py::test_an_organisations_owner_needs_the_second_factor_to_pay_or_poll` |
| P20 | another plan's checkout in progress refuses (409) | `test_checkouts.py::test_a_checkout_in_progress_is_answered_again_and_blocks_another_plan` |

The database guards (subject-only settlement and activation, once, idempotent, serialised, INSERT at the plan's
price) are 0005's, proved there (REQ-SCOUT-01 card M1-M12, M35, N19-N22).

## Open items and follow-ups

1. **Demo seed registration.** P9's `bridge/seed/demo/` package (`__init__`, `accounts`, …) is on the integration
   branch, not on this branch's base (0005 was cut before P9 merged). The module is written and tested on its own; after
   the merge, one line in P9's `__init__` calls `seed_demo_subscriptions(conn, settings)` after the accounts and
   organisations are seeded. Merging the integration branch into this one was refused by the permission check.
2. The fake lives in the API process: several API processes would fail some simulated checkouts (`unknown_checkout`;
   never a wrong activation). The demo runs one.
3. Paying for a lower plan (Growth to Starter) is allowed and replaces the live subscription; a downgrade rule belongs
   to REQ-BIL-06.
4. REQ-BIL-04 still needs the "Blocker before REQ-BIL-04" of the REQ-SCOUT-01 card (platform-path settlement,
   `webhook_events`, the amount and currency check in the database) before any real provider.
5. D-44 is open: the flags implement its recommended default (a); the labels are P14-F's `[[COPY-REVIEW]]` copy.
6. The org-side scout cap (402 on a 2nd scout) is P10's API, not on this branch; the entitlements test shows Growth's
   limit of 5 that P10 reads.
