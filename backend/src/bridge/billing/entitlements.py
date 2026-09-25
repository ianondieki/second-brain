"""Server-side entitlements (REQ-BIL-01; docs/spec/05 "enforced server-side on every gated action").

A gated action asks for the subject's ``Entitlements`` and calls ``check_count`` or ``require_feature``; over the
plan limit the API answers **402** with the next plan up (``upgrade``; null at the top of the ladder) and the action
creates nothing. Proposals, tags and unlocks (Phase 2) call these helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.billing import plans
from bridge.billing.models import Plan, Subscription
from bridge.config import Settings
from bridge.errors import ApiError
from bridge.models.enums import LIVE_SUBSCRIPTION_STATUSES, PlanSide


@dataclass(frozen=True, slots=True)
class Entitlements:
    plan_code: str
    side: PlanSide
    limits: dict[str, Any]

    def limit(self, key: str) -> int | None:
        """A numeric cap; ``None`` means unlimited. Unknown keys fail closed (limit 0)."""
        if key not in self.limits:
            return 0
        value = self.limits[key]
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{key} is not a numeric limit")
        return value

    def allows(self, key: str) -> bool:
        """A feature flag; only an explicit ``true`` allows (strings such as ``release-2`` do not)."""
        return self.limits.get(key) is True


def _upgrade_body(settings: Settings, ent: Entitlements) -> dict[str, str] | None:
    target = plans.load(settings.plans_file).upgrade_for(ent.plan_code)
    if target is None:
        return None
    return {"plan": target.code, "url": f"/billing/upgrade?plan={target.code}"}


class PlanLimitExceeded(ApiError):
    def __init__(self, settings: Settings, ent: Entitlements, key: str, *, limit: int | None, used: int | None) -> None:
        upgrade = _upgrade_body(settings, ent)
        super().__init__(
            402,
            "plan_limit",
            "This needs a higher plan." if upgrade else "This is beyond your plan. Contact us to raise the limit.",
            limit_key=key,
            limit=limit,
            used=used,
            plan=ent.plan_code,
            upgrade=upgrade,
        )


async def _live_plan_code(db: AsyncSession, *, user_id: UUID | None, org_id: UUID | None) -> str | None:
    stmt = (
        select(Plan.code)
        .join(Subscription, Subscription.plan_id == Plan.id)
        .where(Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES))
    )
    stmt = stmt.where(Subscription.user_id == user_id) if user_id else stmt.where(Subscription.org_id == org_id)
    return (await db.execute(stmt.limit(1))).scalar_one_or_none()


async def for_subject(
    db: AsyncSession, settings: Settings, *, user_id: UUID | None = None, org_id: UUID | None = None
) -> Entitlements:
    """The live plan of a user or an organisation; the side's free plan when there is none (fail safe, not open)."""
    if (user_id is None) == (org_id is None):
        raise ValueError("pass exactly one of user_id and org_id")
    side = PlanSide.DEVELOPER if user_id else PlanSide.ORG
    catalog = plans.load(settings.plans_file)
    code = await _live_plan_code(db, user_id=user_id, org_id=org_id)
    spec = catalog.plans.get(code) if code else None
    if spec is None or spec.side != side:
        spec = catalog.default_for(side)
    return Entitlements(spec.code, side, dict(spec.limits))


def check_count(settings: Settings, ent: Entitlements, key: str, *, used: int) -> None:
    """Raise 402 when one more item would exceed the cap ``key`` (``used`` = items that already count)."""
    cap = ent.limit(key)
    if cap is not None and used >= cap:
        raise PlanLimitExceeded(settings, ent, key, limit=cap, used=used)


def require_feature(settings: Settings, ent: Entitlements, key: str) -> None:
    if not ent.allows(key):
        raise PlanLimitExceeded(settings, ent, key, limit=None, used=None)
