"""Demo subscriptions (P14; REQ-BIL-08; D-36): nothing paid by default. Part of ``python -m bridge.seed --demo``.

Every demo developer (``users.demo_account``) and every organisation with an active demo member gets its side's free
plan (``dev_free``, ``org_claimed``) when it has no live subscription. The walkthrough then upgrades live through the
simulated M-Pesa checkout (``POST /api/billing/checkouts``; P14 walkthrough step 2).

A used database (P9's re-seed rule: running the seed again after live demo steps never fails and never undoes them):
a live subscription is never touched, so a plan bought in the walkthrough (or given by another demo module) stays,
and no payment is ever written, changed or deleted here (payments are permanent records: ``payments_guard``). A fresh
walkthrough needs a fresh database (``make demo-reset``). Runs as the owner role, in the seed's transaction, and only
where ``APP_ENV`` is dev or test.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bridge.billing import plans
from bridge.config import Settings
from bridge.models.enums import PlanSide

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


class DemoSeedRefused(RuntimeError):
    """The demo seed runs only where ``APP_ENV`` is dev or test."""


async def seed_demo_subscriptions(conn: AsyncConnection, settings: Settings) -> dict[str, int]:
    """Give demo subjects without a live subscription their side's free plan; returns how many were added per side.
    Needs the reference seed's plans (``python -m bridge.seed`` runs first)."""
    if settings.app_env not in ("dev", "test"):
        raise DemoSeedRefused("the demo seed runs only in dev and test")
    catalog = plans.load(settings.plans_file)
    added: dict[str, int] = {}
    for side, statement in ((PlanSide.DEVELOPER, _DEVELOPERS), (PlanSide.ORG, _ORGANISATIONS)):
        code = catalog.default_for(side).code
        plan_id = (await conn.execute(_PLAN_ID, {"code": code})).scalar_one_or_none()
        if plan_id is None:
            raise LookupError(f"plan {code} is not seeded: run python -m bridge.seed first")
        result = await conn.execute(statement, {"plan": plan_id})
        added[side.value] = int(result.rowcount)
    return added
