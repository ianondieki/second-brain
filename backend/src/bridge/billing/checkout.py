"""Checkouts of a paid plan (REQ-BIL-08, the REQ-BIL-04 interface; P14; docs/spec/05). The routes are in
``bridge.billing.router``.

A checkout is one ``payments`` row (revision 0005). ``start`` inserts it pending, for the subject (the user, or an
organisation whose owner, admin or finance member asks), at the plan's price, with a ``provider_ref`` generated here
(never taken from the client: a client-chosen key would let a unique-key refusal reveal another tenant's row), then
asks the provider to ``initiate``. ``refresh`` asks the provider how it ended (``query``) and only that answer settles
it, through ``app_settle_payment``, and a success activates the plan through ``app_activate_paid_subscription``; both
functions are idempotent and serialised in the database, so repeated or parallel refreshes activate once. Nothing else
writes a payment.

One checkout at a time per subject: the subject's advisory lock is held while its pending checkouts are refreshed and a
new one inserted. A still-pending checkout for the same plan is answered again; one for another plan refuses (409).
Every refusal is a fixed message.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, and_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.billing import entitlements, plans
from bridge.billing.models import Payment, Plan
from bridge.billing.plans import PlanSpec
from bridge.billing.providers.base import (
    FAILURE_CODE_PATTERN,
    CheckoutRequest,
    PaymentProvider,
    PaymentProviderError,
    ProviderStatus,
    SimulatedOutcome,
)
from bridge.config import Settings
from bridge.errors import ApiError
from bridge.ids import uuid7
from bridge.models.enums import PaymentStatus, PlanSide

REF_PREFIX: Final = "chk_"
POLL_AFTER_SECONDS: Final = 2
AMOUNT_MISMATCH: Final = "amount_mismatch"
_SETTLE = text("SELECT app_settle_payment(:id, CAST(:status AS payment_status), :code)")
_ACTIVATE = text("SELECT app_activate_paid_subscription(:id)")
_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
_CHECK_VIOLATION = "23514"
_NOW = text("SELECT app_clock_now()")


def plan_not_available() -> ApiError:
    return ApiError(422, "plan_not_available", "Choose a paid plan to upgrade to.")


def plan_wrong_side() -> ApiError:
    return ApiError(422, "plan_wrong_side", "This plan is for the other kind of account.")


def not_a_developer() -> ApiError:
    return ApiError(403, "not_a_developer", "Developer plans are for developer accounts.")


def already_on_plan() -> ApiError:
    return ApiError(409, "already_on_plan", "You are already on this plan.")


def checkout_pending(checkout_id: UUID) -> ApiError:
    return ApiError(
        409,
        "checkout_pending",
        "Another checkout is still in progress. Wait for it to finish, then try again.",
        checkout_id=str(checkout_id),
    )


def simulation_not_available() -> ApiError:
    return ApiError(422, "simulation_not_available", "This checkout cannot be simulated.")


def provider_error() -> ApiError:
    return ApiError(502, "payment_provider_error", "The payment could not be started. Try again in a few minutes.")


async def app_now(db: AsyncSession) -> datetime:
    """The shared app clock (``app_clock_now()``): the database clock plus the dev/test clock's offset where enabled,
    so the dev/test clock drives the fake provider's delay."""
    now: datetime = (await db.execute(_NOW)).scalar_one()
    return now


def new_provider_ref() -> str:
    """A platform reference: 36 characters of ``[A-Za-z0-9_-]`` (payments.provider_ref CHECK), 192 random bits."""
    return REF_PREFIX + secrets.token_urlsafe(24)


@dataclass(frozen=True, slots=True)
class Subject:
    """Who a checkout is for: a developer (``user_id``) or an organisation (``org_id``), exactly one."""

    user_id: UUID | None = None
    org_id: UUID | None = None

    def __post_init__(self) -> None:
        if (self.user_id is None) == (self.org_id is None):
            raise ValueError("a checkout is for exactly one of a user and an organisation")

    @property
    def side(self) -> PlanSide:
        return PlanSide.DEVELOPER if self.user_id is not None else PlanSide.ORG

    @property
    def key(self) -> str:
        return f"checkout:{self.org_id or self.user_id}"


def purchasable_spec(settings: Settings, plan_code: str) -> PlanSpec:
    """The catalogue entry of a plan a checkout may buy; 422 otherwise (unknown, default, free, custom, approval)."""
    spec = plans.load(settings.plans_file).plans.get(plan_code)
    if spec is None or not spec.purchasable:
        raise plan_not_available()
    return spec


async def _plan_row(db: AsyncSession, spec: PlanSpec) -> Plan:
    plan = (await db.execute(select(Plan).where(Plan.code == spec.code, Plan.active))).scalar_one_or_none()
    if plan is None or plan.is_default or plan.side != spec.side or plan.price_kes_minor <= 0:
        raise plan_not_available()  # not seeded, retired or changed in the database: never sold
    return plan


def _of_subject(subject: Subject) -> ColumnElement[bool]:
    if subject.org_id is not None:
        return Payment.org_id == subject.org_id
    return and_(Payment.user_id == subject.user_id, Payment.org_id.is_(None))


async def start(
    db: AsyncSession,
    settings: Settings,
    provider: PaymentProvider,
    *,
    actor_id: UUID,
    subject: Subject,
    plan_code: str,
    simulate: SimulatedOutcome | None = None,
) -> tuple[Payment, bool]:
    """Start a checkout of ``plan_code`` for ``subject`` (the caller is checked by the route and again by RLS).
    Returns the payment and whether it is new (False: the subject's pending checkout of that plan)."""
    spec = purchasable_spec(settings, plan_code)
    if spec.side != subject.side:
        raise plan_wrong_side()
    if simulate is not None and not provider.simulated:
        raise simulation_not_available()
    plan = await _plan_row(db, spec)

    await db.execute(_LOCK, {"key": subject.key})  # one checkout decision per subject at a time
    pending = (
        (
            await db.execute(
                select(Payment)
                .where(_of_subject(subject), Payment.status == PaymentStatus.PENDING)
                .order_by(Payment.created_at)
            )
        )
        .scalars()
        .all()
    )
    for payment in pending:
        await refresh(db, provider, payment)
        if payment.status is PaymentStatus.PENDING:
            await db.commit()  # keep whatever the refreshes settled meanwhile
            if payment.plan_id == plan.id:
                return payment, False
            raise checkout_pending(payment.id)

    current = await entitlements.for_subject(db, settings, user_id=subject.user_id, org_id=subject.org_id)
    if current.plan_code == spec.code:
        await db.commit()  # keep whatever the refreshes settled meanwhile
        raise already_on_plan()

    payment = Payment(
        id=uuid7(),
        user_id=subject.user_id,
        org_id=subject.org_id,
        plan_id=plan.id,
        amount_kes_minor=plan.price_kes_minor,
        provider=provider.name,
        provider_ref=new_provider_ref(),
        status=PaymentStatus.PENDING,
        initiated_by=actor_id,
    )
    db.add(payment)
    await db.flush()
    await audit(
        db,
        "billing.checkout_started",
        actor_user_id=actor_id,
        org_id=subject.org_id,
        subject_type="payment",
        subject_id=payment.id,
        payload={"plan": spec.code, "amount_kes_minor": plan.price_kes_minor, "provider": provider.name},
    )
    now = await app_now(db)
    await db.commit()  # the pending row exists before the provider hears of it (a callback or query can find it)

    request = CheckoutRequest(payment.provider_ref, payment.amount_kes_minor, spec.code, simulate)
    try:
        await provider.initiate(request, now=now)
    except PaymentProviderError as exc:
        code = "provider_unavailable" if exc.transient else "provider_refused"
        await _settle(db, payment, ProviderStatus.FAILED, code, actor_id=actor_id)
        await db.commit()
        raise provider_error() from exc
    return payment, True


async def refresh(
    db: AsyncSession, provider: PaymentProvider, payment: Payment, *, actor_id: UUID | None = None
) -> None:
    """Ask the provider about a pending checkout and settle it on a final answer; activate a succeeded one. Does not
    commit. Leaves ``payment`` reloaded. A provider error, or a payment of another provider, changes nothing."""
    if payment.status is PaymentStatus.PENDING and payment.provider == provider.name:
        try:
            result = await provider.query(payment.provider_ref, now=await app_now(db))
        except PaymentProviderError:
            return  # transient or not, the checkout stays pending; the next poll asks again
        if result.status is not ProviderStatus.PENDING:
            status, code = result.status, result.failure_code
            if status is ProviderStatus.SUCCEEDED and result.amount_kes_minor != payment.amount_kes_minor:
                status, code = ProviderStatus.FAILED, AMOUNT_MISMATCH  # never activate on a different amount
            await _settle(db, payment, status, code, actor_id=actor_id or payment.initiated_by)
    if payment.status is PaymentStatus.SUCCEEDED and payment.subscription_id is None:
        await db.execute(_ACTIVATE, {"id": payment.id})
        await db.refresh(payment)


async def _settle(
    db: AsyncSession, payment: Payment, status: ProviderStatus, code: str | None, *, actor_id: UUID
) -> None:
    """``app_settle_payment`` once; a refusal because another request settled it differently first keeps that
    outcome (the row is reloaded either way)."""
    if status is ProviderStatus.SUCCEEDED:
        code = None
    elif code is None or not re.fullmatch(FAILURE_CODE_PATTERN, code):
        code = f"provider_{status.value}"
    try:
        async with db.begin_nested():
            params = {"id": payment.id, "status": status.value, "code": code}
            settled = bool((await db.execute(_SETTLE, params)).scalar())
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) != _CHECK_VIOLATION:
            raise
        settled = False  # already settled with another outcome by a concurrent request: that one stands
    await db.refresh(payment)
    if settled:
        await audit(
            db,
            "billing.checkout_settled",
            actor_user_id=actor_id,
            org_id=payment.org_id,
            subject_type="payment",
            subject_id=payment.id,
            payload={"status": status.value, "failure_code": code},
        )
