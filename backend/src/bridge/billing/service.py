"""Subscription rows for free plans (REQ-BIL-01). Paid rails arrive in Phase 6."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import clock
from bridge.billing import plans
from bridge.billing.models import Plan, Subscription
from bridge.config import Settings
from bridge.models.enums import PlanSide, SubscriptionStatus


class PlansNotSeededError(RuntimeError):
    """The plans table is empty: run ``python -m bridge.seed``. Signup fails closed rather than skip billing."""


async def start_free_subscription(
    db: AsyncSession, settings: Settings, *, side: PlanSide, user_id: UUID | None = None, org_id: UUID | None = None
) -> Subscription:
    code = plans.load(settings.plans_file).default_for(side).code
    plan_id = (await db.execute(select(Plan.id).where(Plan.code == code))).scalar_one_or_none()
    if plan_id is None:
        raise PlansNotSeededError(code)
    subscription = Subscription(
        user_id=user_id,
        org_id=org_id,
        plan_id=plan_id,
        status=SubscriptionStatus.ACTIVE,
        current_period_start=clock.utcnow(),
    )
    db.add(subscription)
    await db.flush()
    return subscription
