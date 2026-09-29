"""REQ-BIL-08 and the REQ-BIL-04 interface (schema half; revision 0005): payments, their settlement and activation.

- A payment is inserted pending, by its subject (the user, or the organisation's owner, admin or finance member), for
  an active, non-default plan of the subject's side at exactly its price; provider ``fake`` only, a platform reference.
- Only the subject reads it; nobody updates or deletes it (no grant), and ``payments_guard`` keeps it for every role:
  never deleted or truncated, its subject, plan, amount and reference fixed, settled once at the database's clock,
  linked to one subscription once.
- ``app_settle_payment``: the subject only (one refusal, the same for a payment that does not exist); pending to a final
  status once; repeating the outcome changes nothing; another outcome is refused.
- ``app_activate_paid_subscription``: the subject only; a succeeded payment matching its plan's side and price;
  cancels the live subscription and starts the plan from ``app_clock_now()``; idempotent.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration.schema_v4 import Seats, act, add_user, as_app, as_owner, expect, rowcount, run, seats

PAY = (
    "INSERT INTO payments (id, user_id, org_id, plan_id, amount_kes_minor, provider, provider_ref, initiated_by,"
    " status) VALUES (:id, :user, :org, :plan, :amount, :provider, :ref, :by, CAST(:status AS payment_status))"
)
SETTLE = "SELECT app_settle_payment(:id, CAST(:status AS payment_status), :code)"
ACTIVATE = "SELECT app_activate_paid_subscription(:id)"
ADD_PLAN = (
    'INSERT INTO plans (id, code, side, name, price_kes_minor, "interval", limits, active, is_default)'
    " VALUES (:id, :code, CAST(:side AS plan_side), 'Test plan', :price, CAST(:interval AS billing_interval),"
    " '{}'::jsonb, :active, false)"
)
NEAR_CLOCK = "abs(extract(epoch FROM {column} - app_clock_now())) < 60"


class Plans:
    """Paid test plans (unique codes) and each side's default (free) plan."""

    def __init__(self, ids: dict[str, UUID], prices: dict[str, int]) -> None:
        self.ids, self.prices = ids, prices

    def __getitem__(self, name: str) -> UUID:
        return self.ids[name]


async def _plans(conn: AsyncConnection) -> Plans:
    """As the owner."""
    ids: dict[str, UUID] = {}
    prices = {"dev_month": 49_900, "dev_year": 499_000, "org_month": 1_500_000, "org_year": 15_000_000}
    specs = {
        "dev_month": ("developer", "month", True),
        "dev_year": ("developer", "year", True),
        "org_month": ("org", "month", True),
        "org_year": ("org", "year", True),
        "dev_inactive": ("developer", "month", False),
    }
    prices["dev_inactive"] = 49_900
    for name, (side, interval, active) in specs.items():
        ids[name] = uuid7()
        await run(
            conn,
            ADD_PLAN,
            id=ids[name],
            code=f"v4-{name}-{ids[name].hex[-8:]}",
            side=side,
            price=prices[name],
            interval=interval,
            active=active,
        )
    for side in ("developer", "org"):  # the seed may have made one already (config/plans.yaml `default: true`)
        default = await run(conn, "SELECT id FROM plans WHERE side = CAST(:s AS plan_side) AND is_default", s=side)
        if default is None:
            default = uuid7()
            await run(
                conn,
                'INSERT INTO plans (id, code, side, name, price_kes_minor, "interval", limits, is_default)'
                " VALUES (:id, :code, CAST(:s AS plan_side), 'Free', 0, 'none', '{}'::jsonb, true)",
                id=default,
                code=f"v4-free-{side}-{default.hex[-8:]}",
                s=side,
            )
        ids[f"{side}_default"] = default
        prices[f"{side}_default"] = 0
    return Plans(ids, prices)


def pay(plans: Plans, plan: str, *, user: UUID | None, org: UUID | None, by: UUID, **overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "id": uuid7(),
        "user": user,
        "org": org,
        "plan": plans[plan],
        "amount": plans.prices[plan],
        "provider": "fake",
        "ref": f"fake_{uuid7().hex}",
        "by": by,
        "status": "pending",
    }
    params.update(overrides)
    return params


async def _pending(conn: AsyncConnection, params: dict[str, Any]) -> UUID:
    """As the owner (no RLS; the guard still runs): a pending payment."""
    await run(conn, PAY, **params)
    return UUID(str(params["id"]))


async def _people(conn: AsyncConnection) -> tuple[UUID, UUID, Seats, Seats]:
    return await add_user(conn, "payer"), await add_user(conn, "other"), await seats(conn), await seats(conn)


# --- INSERT and SELECT ----------------------------------------------------------------------------------------------


async def test_a_payment_starts_pending_for_a_paid_plan_of_the_subjects_side_at_its_price(
    owner_engine: AsyncEngine,
) -> None:
    async with as_app(owner_engine) as conn:
        plans = await _plans(conn)
        dev, other, a, b = await _people(conn)
        await act(conn, dev)
        await run(conn, PAY, **pay(plans, "dev_month", user=dev, org=None, by=dev))
        await run(conn, PAY, **pay(plans, "dev_year", user=dev, org=None, by=dev))
        for overrides in (
            {"amount": 49_899},  # not the plan's price
            {"amount": 49_901},
            {"plan": plans["org_month"], "amount": plans.prices["org_month"]},  # the other side's plan
            {"plan": plans["developer_default"], "amount": 1},  # the free plan: never paid for
            {"plan": plans["dev_inactive"]},  # a plan no longer sold
            {"by": other},  # initiated by oneself
            {"user": other, "by": dev},  # for oneself
            {"org": a.org},  # one subject only
        ):
            await expect(
                conn, PAY, "row-level security", **(pay(plans, "dev_month", user=dev, org=None, by=dev) | overrides)
            )
        # A payment starts pending: payments_guard (BEFORE, every role) refuses before the policy's own check does.
        await expect(
            conn, PAY, "starts pending", **pay(plans, "dev_month", user=dev, org=None, by=dev, status="failed")
        )
        await expect(
            conn,
            PAY,
            "ck_payments_provider_known",
            **pay(plans, "dev_month", user=dev, org=None, by=dev, provider="mpesa"),
        )
        await expect(
            conn,
            PAY,
            "ck_payments_provider_ref_format",
            **pay(plans, "dev_month", user=dev, org=None, by=dev, ref="short"),
        )
        taken = pay(plans, "dev_month", user=dev, org=None, by=dev)
        await run(conn, PAY, **taken)
        await expect(
            conn,
            PAY,
            "uq_payments_provider_ref",
            **pay(plans, "dev_month", user=dev, org=None, by=dev, ref=taken["ref"]),
        )
        for payer in (a.owner, a.admin, a.finance):  # the organisation's owner, admin or finance member
            await act(conn, payer, a.org)
            await run(conn, PAY, **pay(plans, "org_month", user=None, org=a.org, by=payer))
        for payer, context in (
            (a.reviewer, a.org),
            (a.signatory, a.org),
            (a.viewer, a.org),
            (b.owner, None),
            (a.finance, b.org),
        ):
            await act(conn, payer, context)
            await expect(conn, PAY, "row-level security", **pay(plans, "org_month", user=None, org=a.org, by=payer))
        await act(conn, a.finance, a.org)
        await expect(conn, PAY, "row-level security", **pay(plans, "dev_month", user=None, org=a.org, by=a.finance))


async def test_only_the_subject_reads_a_payment(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        plans = await _plans(conn)
        dev, other, a, b = await _people(conn)
        mine = await _pending(conn, pay(plans, "dev_month", user=dev, org=None, by=dev))
        theirs = await _pending(conn, pay(plans, "org_month", user=None, org=a.org, by=a.finance))
        seen = "SELECT count(*) FROM payments WHERE id = ANY (:ids)"
        for reader, context, expected in (
            (dev, None, 1),
            (other, None, 0),
            (a.owner, None, 1),
            (a.admin, a.org, 1),
            (a.finance, a.org, 1),
            (a.reviewer, a.org, 0),
            (a.signatory, None, 0),
            (a.viewer, None, 0),
            (b.owner, None, 0),
            (a.finance, b.org, 0),  # narrowed to another organisation
            (None, None, 0),
        ):
            await act(conn, reader, context)
            assert await run(conn, seen, ids=[mine, theirs]) == expected, (reader, context)


# --- payments_guard -----------------------------------------------------------------------------------------------


async def test_the_guard_keeps_every_payment_for_every_role(owner_engine: AsyncEngine) -> None:
    """The owner too: a payment starts pending, is never deleted or truncated, keeps its subject, plan, amount and
    reference, settles once at the database's clock (a time sent is replaced), and links one subscription once."""
    async with as_app(owner_engine) as conn:
        plans = await _plans(conn)
        dev, other, a, _b = await _people(conn)
        await as_owner(conn)
        for overrides in ({"status": "succeeded"}, {"status": "failed"}):
            await expect(
                conn, PAY, "starts pending", **pay(plans, "dev_month", user=dev, org=None, by=dev, **overrides)
            )
        payment = await _pending(conn, pay(plans, "dev_month", user=dev, org=None, by=dev))
        await expect(conn, "DELETE FROM payments WHERE id = :id", "never deleted", id=payment)
        await expect(conn, "TRUNCATE payments", "TRUNCATE on payments is not allowed")
        for assignment in (
            "amount_kes_minor = 1",
            "plan_id = :other_plan",
            "user_id = :other",
            "org_id = :org, user_id = NULL",
            "provider_ref = 'fake_0123456789abcdef'",
            "initiated_by = :other",
            "created_at = now() - interval '1 day'",
        ):
            await expect(
                conn,
                f"UPDATE payments SET {assignment} WHERE id = :id",
                "never change",
                id=payment,
                other=other,
                other_plan=plans["dev_year"],
                org=a.org,
            )
        subscription = uuid7()
        await run(
            conn,
            "INSERT INTO subscriptions (id, user_id, plan_id, status, current_period_start) VALUES (:id, :u, :p,"
            " 'cancelled', now())",
            id=subscription,
            u=dev,
            p=plans["dev_month"],
        )
        link = "UPDATE payments SET subscription_id = :s WHERE id = :id"
        await expect(conn, link, "linked to its subscription once", s=subscription, id=payment)  # not succeeded
        settle = "UPDATE payments SET status = 'succeeded', settled_at = now() - interval '9 days' WHERE id = :id"
        assert await rowcount(conn, settle, id=payment) == 1
        assert await run(
            conn, f"SELECT {NEAR_CLOCK.format(column='settled_at')} FROM payments WHERE id = :id", id=payment
        )
        for change in ("status = 'failed'", "status = 'pending'", "settled_at = now()", "failure_code = 'declined'"):
            await expect(
                conn,
                f"UPDATE payments SET {change} WHERE id = :id",
                "settled once|settlement never changes",
                id=payment,
            )
        assert await rowcount(conn, link, s=subscription, id=payment) == 1
        for relink in (uuid7(), None):
            await expect(conn, link, "linked to its subscription once", s=relink, id=payment)


# --- app_settle_payment -------------------------------------------------------------------------------------------


async def test_a_payment_is_settled_once_by_its_subject(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        plans = await _plans(conn)
        dev, other, a, b = await _people(conn)
        mine = await _pending(conn, pay(plans, "dev_month", user=dev, org=None, by=dev))
        theirs = await _pending(conn, pay(plans, "org_month", user=None, org=a.org, by=a.finance))
        for caller, context, payment in (
            (other, None, mine),  # wrong user
            (a.owner, None, mine),
            (None, None, mine),
            (dev, None, uuid7()),  # none: the same refusal
            (a.reviewer, a.org, theirs),  # a member who does not pay
            (a.viewer, None, theirs),
            (b.owner, None, theirs),  # wrong organisation
            (a.finance, b.org, theirs),  # narrowed to another organisation
        ):
            await act(conn, caller, context)
            await expect(
                conn, SETTLE, "no payment of the caller's with that id", id=payment, status="succeeded", code=None
            )
        await act(conn, dev)
        await expect(conn, SETTLE, "settles as succeeded, failed or cancelled", id=mine, status="pending", code=None)
        await expect(conn, SETTLE, "settles as succeeded, failed or cancelled", id=mine, status=None, code=None)
        await expect(conn, SETTLE, "failure code", id=mine, status="succeeded", code="declined")
        await expect(conn, SETTLE, "failure code", id=mine, status="failed", code="Card declined!")
        assert await run(conn, SETTLE, id=mine, status="succeeded", code=None) is True
        settled = "SELECT status::text, settled_at, failure_code FROM payments WHERE id = :id"
        first = (await conn.execute(sa.text(settled), {"id": mine})).one()
        assert first.status == "succeeded"
        assert await run(conn, SETTLE, id=mine, status="succeeded", code=None) is False  # the same outcome: a no-op
        assert (await conn.execute(sa.text(settled), {"id": mine})).one() == first
        for outcome, code in (("failed", "declined"), ("cancelled", None)):  # a second settle
            await expect(conn, SETTLE, "already settled as succeeded", id=mine, status=outcome, code=code)
        await act(conn, a.admin, a.org)
        assert await run(conn, SETTLE, id=theirs, status="failed", code="insufficient_funds") is True
        assert await run(conn, SETTLE, id=theirs, status="failed", code="insufficient_funds") is False
        await expect(conn, SETTLE, "already settled as failed", id=theirs, status="failed", code="timeout")
        await expect(conn, SETTLE, "already settled as failed", id=theirs, status="succeeded", code=None)


# --- app_activate_paid_subscription ---------------------------------------------------------------------------------


async def _subscriptions(conn: AsyncConnection, *, user: UUID | None = None, org: UUID | None = None) -> list[Any]:
    await as_owner(conn)
    found = await conn.execute(
        sa.text(
            "SELECT id, plan_id, status::text AS status, current_period_end IS NULL AS open_ended,"
            " current_period_end = current_period_start + interval '1 month' AS a_month,"
            " current_period_end = current_period_start + interval '1 year' AS a_year,"
            f" {NEAR_CLOCK.format(column='current_period_start')} AS now_started"
            " FROM subscriptions WHERE user_id IS NOT DISTINCT FROM :u AND org_id IS NOT DISTINCT FROM :o"
            " ORDER BY created_at, id"
        ),
        {"u": user, "o": org},
    )
    return list(found.all())


async def test_activation_is_idempotent_and_replaces_the_live_subscription(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        plans = await _plans(conn)
        dev, other, a, _b = await _people(conn)
        free = uuid7()
        await run(
            conn,
            "INSERT INTO subscriptions (id, user_id, plan_id, status, current_period_start) VALUES (:id, :u, :p,"
            " 'active', now())",
            id=free,
            u=dev,
            p=plans["developer_default"],
        )
        monthly = await _pending(conn, pay(plans, "dev_month", user=dev, org=None, by=dev))
        await act(conn, dev)
        await expect(conn, ACTIVATE, "has not succeeded", id=monthly)
        await run(conn, SETTLE, id=monthly, status="succeeded", code=None)
        for caller in (other, a.owner, None):
            await act(conn, caller)
            await expect(conn, ACTIVATE, "no payment of the caller's with that id", id=monthly)
        await act(conn, dev)
        first = await run(conn, ACTIVATE, id=monthly)
        assert await run(conn, ACTIVATE, id=monthly) == first  # idempotent: a repeated query activates nothing twice
        subscriptions = await _subscriptions(conn, user=dev)
        assert [(s.id, s.status) for s in subscriptions] == [(free, "cancelled"), (first, "active")]
        new = subscriptions[1]
        assert (new.plan_id, new.now_started, new.a_month) == (plans["dev_month"], True, True)
        assert await run(conn, "SELECT subscription_id FROM payments WHERE id = :id", id=monthly) == first
        yearly = await _pending(conn, pay(plans, "dev_year", user=dev, org=None, by=dev))
        await act(conn, dev)
        await run(conn, SETTLE, id=yearly, status="succeeded", code=None)
        second = await run(conn, ACTIVATE, id=yearly)
        subscriptions = await _subscriptions(conn, user=dev)
        assert [s.status for s in subscriptions] == ["cancelled", "cancelled", "active"]
        assert subscriptions[2].id == second
        assert (subscriptions[2].plan_id, subscriptions[2].a_year) == (plans["dev_year"], True)
        # An organisation's payment, activated by another of its paying members.
        previous = uuid7()
        await run(
            conn,
            "INSERT INTO subscriptions (id, org_id, plan_id, status, current_period_start) VALUES (:id, :o, :p,"
            " 'trialing', now())",
            id=previous,
            o=a.org,
            p=plans["org_default"],
        )
        org_payment = await _pending(conn, pay(plans, "org_month", user=None, org=a.org, by=a.finance))
        await act(conn, a.finance, a.org)
        await run(conn, SETTLE, id=org_payment, status="succeeded", code=None)
        await act(conn, a.owner, a.org)
        activated = await run(conn, ACTIVATE, id=org_payment)
        assert [(s.id, s.status) for s in await _subscriptions(conn, org=a.org)] == [
            (previous, "cancelled"),
            (activated, "active"),
        ]


@pytest.mark.parametrize(
    ("plan", "overrides", "outcome"),
    [
        ("dev_month", {}, "failed"),  # not succeeded
        ("dev_month", {}, "cancelled"),
        ("org_month", {}, "succeeded"),  # a user paid for an organisation plan (inserted past the policy)
    ],
)
async def test_activation_needs_a_succeeded_payment_matching_its_plan(
    owner_engine: AsyncEngine, plan: str, overrides: dict[str, Any], outcome: str
) -> None:
    async with as_app(owner_engine) as conn:
        plans = await _plans(conn)
        dev = await add_user(conn, "payer")
        payment = await _pending(conn, pay(plans, plan, user=dev, org=None, by=dev, **overrides))
        await act(conn, dev)
        code = None if outcome == "succeeded" else "declined"
        await run(conn, SETTLE, id=payment, status=outcome, code=code)
        message = "has not succeeded" if outcome != "succeeded" else "plan is not of its subject's side"
        await expect(conn, ACTIVATE, message, id=payment)
        assert await _subscriptions(conn, user=dev) == []


async def test_a_price_change_after_payment_never_strands_a_succeeded_payment(owner_engine: AsyncEngine) -> None:
    """The plan and the amount were matched when the payment was inserted and never change, so activation does not
    re-check the price: a plans.yaml price change between the checkout and its activation still activates."""
    async with as_app(owner_engine) as conn:
        plans = await _plans(conn)
        dev = await add_user(conn, "payer")
        await act(conn, dev)
        payment = pay(plans, "dev_month", user=dev, org=None, by=dev)
        await run(conn, PAY, **payment)
        await as_owner(conn)
        await run(conn, "UPDATE plans SET price_kes_minor = 59900 WHERE id = :id", id=plans["dev_month"])
        await act(conn, dev)
        await run(conn, SETTLE, id=payment["id"], status="succeeded", code=None)
        activated = await run(conn, ACTIVATE, id=payment["id"])
        assert [(s.id, s.status) for s in await _subscriptions(conn, user=dev)] == [(activated, "active")]


async def test_a_paid_default_plan_is_still_never_bought(owner_engine: AsyncEngine) -> None:
    """N2: the side's default plan priced above zero (a mistake in plans.yaml) at exactly its price is still refused:
    the default plan is self-serve only (revision 0001's subscriptions policy), never paid for."""
    async with as_app(owner_engine) as conn:
        plans = await _plans(conn)
        dev = await add_user(conn, "payer")
        await run(conn, "UPDATE plans SET price_kes_minor = 5000 WHERE id = :id", id=plans["developer_default"])
        await act(conn, dev)
        await expect(
            conn,
            PAY,
            "row-level security",
            **(
                pay(plans, "dev_month", user=dev, org=None, by=dev)
                | {"plan": plans["developer_default"], "amount": 5000}
            ),
        )


async def test_settlement_fails_closed_for_a_real_provider(owner_engine: AsyncEngine) -> None:
    """Only the fake provider exists (CHECK). If a later revision widens the CHECK, app_settle_payment still never
    settles that provider's payment as succeeded for its subject: the platform path (REQ-BIL-04) must be added on
    purpose. Failing or cancelling it stays possible. (The CHECK is dropped inside this rolled-back transaction.)"""
    async with as_app(owner_engine) as conn:
        plans = await _plans(conn)
        dev = await add_user(conn, "payer")
        await run(conn, "ALTER TABLE payments DROP CONSTRAINT ck_payments_provider_known")
        real, other = (pay(plans, "dev_month", user=dev, org=None, by=dev, provider="daraja") for _ in range(2))
        for payment in (real, other):
            await _pending(conn, payment)
        await act(conn, dev)
        await expect(
            conn,
            SETTLE,
            "only the platform settles a real provider's payment",
            id=real["id"],
            status="succeeded",
            code=None,
        )
        assert await run(conn, "SELECT status::text FROM payments WHERE id = :id", id=real["id"]) == "pending"
        assert await run(conn, SETTLE, id=other["id"], status="failed", code="declined") is True


async def test_settlement_and_activation_follow_the_test_clock(owner_engine: AsyncEngine) -> None:
    """Both times are app_clock_now(): where the owner enabled the dev/test clock, a moved clock moves them."""
    async with as_app(owner_engine) as conn:
        plans = await _plans(conn)
        dev = await add_user(conn, "payer")
        await run(conn, "UPDATE test_clock SET enabled = true, clock_offset = interval '3 days'")
        payment = await _pending(conn, pay(plans, "dev_month", user=dev, org=None, by=dev))
        await act(conn, dev)
        await run(conn, SETTLE, id=payment, status="succeeded", code=None)
        await run(conn, ACTIVATE, id=payment)
        await as_owner(conn)
        ahead = (
            await conn.execute(
                sa.text(
                    "SELECT p.settled_at - now() > interval '71 hours', s.current_period_start - now() > interval"
                    " '71 hours' FROM payments p JOIN subscriptions s ON s.id = p.subscription_id WHERE p.id = :id"
                ),
                {"id": payment},
            )
        ).one()
        assert tuple(ahead) == (True, True)
