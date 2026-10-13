"""Demo subscriptions (P14; REQ-BIL-08; D-36): nothing paid. Part of ``python -m bridge.seed --demo``.

Every demo developer (``users.demo_account``) and every organisation with an active demo member gets its side's free
plan (``dev_free``, ``org_claimed``) when it has no live subscription. The walkthrough then upgrades live through the
simulated M-Pesa checkout (``POST /api/billing/checkouts``; P14 walkthrough step 2).

One showcase (P28, REQ-TEN-02 and REQ-ENG-17): State Department D starts on Growth (``SHOWCASE_PLANS``: 20 seats and
``csv_export``), so its Team page invites within its seats and its Engagements list exports CSV, while Telco A and
SACCO B stay on the free plan and show the paywall line and the 402 seats refusal: a deliberate contrast. It is a
seeded subscription row, like the free ones: no checkout, no provider call and no payment (a subscription needs none;
payments are permanent records the seed never writes), given only to the fixture (by its name, with a demo member):
its free plan (which its owner's sign-up started) is moved to Growth, or Growth is added when it has no live
subscription, before the free plans; a plan bought in the walkthrough is kept, and a re-run changes nothing.

A used database (P9's re-seed rule: running the seed again after live demo steps never fails and never undoes them):
a live subscription is never touched, so a plan bought in the walkthrough (or given by another demo module) stays,
and no payment is ever written, changed or deleted here (payments are permanent records: ``payments_guard``). A fresh
walkthrough needs a fresh database (``make demo-reset``). Runs as the owner role, in the seed's transaction, and only
where ``APP_ENV`` is dev or test.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bridge.billing import plans
from bridge.config import Settings
from bridge.models.enums import PlanSide
from bridge.seed.demo.data import STATE_D

# (fixture legal name, plan code): the fixtures that start on a paid plan, seeded (P28's Team and CSV showcase). By
# name, as the seed finds a signed-up fixture (the sign-up gives it a slug with a random suffix), with a demo member.
SHOWCASE_PLANS: Final = ((STATE_D.legal_name, "org_growth"),)

# Demo developers without a live subscription of their own.
_DEVELOPERS = text(
    "INSERT INTO subscriptions (id, user_id, plan_id, status, current_period_start)"
    " SELECT uuid7(), u.id, :plan, 'active', app_clock_now() FROM users u"
    " JOIN developer_profiles d ON d.user_id = u.id"
    " WHERE u.demo_account AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.user_id = u.id"
    "                                      AND s.status IN ('trialing', 'active', 'past_due'))"
)
# Organisations with an active demo member and no live subscription.
_ORGANISATIONS = text(
    "INSERT INTO subscriptions (id, org_id, plan_id, status, current_period_start)"
    " SELECT uuid7(), o.id, :plan, 'active', app_clock_now() FROM organizations o"
    " WHERE EXISTS (SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id"
    "               WHERE m.org_id = o.id AND m.status = 'active' AND u.demo_account)"
    " AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.org_id = o.id"
    "                 AND s.status IN ('trialing', 'active', 'past_due'))"
)
_PLAN_ID = text("SELECT id FROM plans WHERE code = :code AND is_default")
# A showcase fixture (by name) with an active demo member and no live subscription.
_SHOWCASE = text(
    "INSERT INTO subscriptions (id, org_id, plan_id, status, current_period_start)"
    " SELECT uuid7(), o.id, :plan, 'active', app_clock_now() FROM organizations o"
    " WHERE o.legal_name = :name"
    " AND EXISTS (SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id"
    "             WHERE m.org_id = o.id AND m.status = 'active' AND u.demo_account)"
    " AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.org_id = o.id"
    "                 AND s.status IN ('trialing', 'active', 'past_due'))"
)
# The same fixture already on the free plan (its owner's sign-up starts one, as every organisation's does): moved to
# the showcase plan. Only the free plan is moved: a plan bought in the walkthrough is kept.
_SHOWCASE_UPGRADE = text(
    "UPDATE subscriptions s SET plan_id = :plan, updated_at = now() FROM organizations o"
    " WHERE o.id = s.org_id AND o.legal_name = :name AND s.plan_id = :free"
    " AND s.status IN ('trialing', 'active', 'past_due')"
    " AND EXISTS (SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id"
    "             WHERE m.org_id = o.id AND m.status = 'active' AND u.demo_account)"
)
_PLAN_BY_CODE = text("SELECT id FROM plans WHERE code = :code AND active")


class DemoSeedRefused(RuntimeError):
    """The demo seed runs only where ``APP_ENV`` is dev or test."""


async def seed_demo_subscriptions(conn: AsyncConnection, settings: Settings) -> dict[str, int]:
    """Give the showcase fixtures their plan, then demo subjects without a live subscription their side's free plan;
    returns how many were added (``showcase`` and per side). Needs the reference seed's plans (``python -m bridge.seed``
    runs first)."""
    if settings.app_env not in ("dev", "test"):
        raise DemoSeedRefused("the demo seed runs only in dev and test")
    catalog = plans.load(settings.plans_file)
    added: dict[str, int] = {"showcase": 0}
    free_org = (await conn.execute(_PLAN_ID, {"code": catalog.default_for(PlanSide.ORG).code})).scalar_one_or_none()
    for name, code in SHOWCASE_PLANS:  # first, so the free plans pass the fixture by
        plan_id = (await conn.execute(_PLAN_BY_CODE, {"code": code})).scalar_one_or_none()
        if plan_id is None or free_org is None:
            raise LookupError(f"plan {code} is not seeded: run python -m bridge.seed first")
        moved = await conn.execute(_SHOWCASE_UPGRADE, {"plan": plan_id, "name": name, "free": free_org})
        inserted = await conn.execute(_SHOWCASE, {"plan": plan_id, "name": name})
        added["showcase"] += int(moved.rowcount) + int(inserted.rowcount)
    for side, statement in ((PlanSide.DEVELOPER, _DEVELOPERS), (PlanSide.ORG, _ORGANISATIONS)):
        code = catalog.default_for(side).code
        plan_id = (await conn.execute(_PLAN_ID, {"code": code})).scalar_one_or_none()
        if plan_id is None:
            raise LookupError(f"plan {code} is not seeded: run python -m bridge.seed first")
        result = await conn.execute(statement, {"plan": plan_id})
        added[side.value] = int(result.rowcount)
    return added
