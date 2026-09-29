"""Plans and checkouts (REQ-BIL-08, the REQ-BIL-04 interface; P14; docs/spec/05). The service is
``bridge.billing.checkout``.

- ``GET /api/plans?side=``: the catalogue from ``config/plans.yaml``, flagged ``sample_prices`` until G3 (D-44: the UI
  labels them "Sample prices, not final") and ``simulated_checkout`` while the provider is the fake (D-36: "Simulated
  M-Pesa"). Public: prices and limits are not personal.
- ``POST /api/billing/checkouts``: ``{plan_code, org_id?, simulate?}``; for the caller as a developer, or for an
  organisation whose owner, admin or finance member the caller is (404 to a non-member, 403 to another role). 201 with
  a new checkout; 200 with the subject's checkout of that plan still in progress. The body takes no id or reference
  (unknown fields are refused): the payment id and ``provider_ref`` are generated on the server.
- ``GET /api/billing/checkouts/{id}``: the subject only (404 otherwise, whether or not the id exists). Asks the
  provider, settles a final answer and activates a success; repeated or parallel reads activate once. Poll it every
  ``poll_after_seconds`` while pending.

Errors are fixed messages with stable codes (``bridge.billing.checkout``). No step-up: M-Pesa confirms on the phone,
and the fake moves no money; a real rail's checkout is reviewed again at REQ-BIL-04.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from bridge.auth.deps import CurrentSession, Db, SettingsDep
from bridge.billing import checkout, plans
from bridge.billing.models import Payment, Plan
from bridge.billing.providers import payment_provider_from_settings
from bridge.billing.providers.base import PaymentProvider, SimulatedOutcome
from bridge.billing.providers.fake import FAKE_PROVIDER_NAME
from bridge.config import ConfigurationError, Settings
from bridge.errors import ERROR_RESPONSES, ApiError, ApiErrorBody, not_found
from bridge.models.enums import BillingInterval, OrgRole, PaymentStatus, PlanSide
from bridge.profiles.models import DeveloperProfile
from bridge.tenancy.deps import org_member

CURRENCY = "KES"
NOT_CONFIGURED = "not_configured"

plans_router = APIRouter(prefix="/api/plans", tags=["billing"], responses=ERROR_RESPONSES)
router = APIRouter(prefix="/api/billing", tags=["billing"], responses=ERROR_RESPONSES)
# Who pays for an organisation's plan (docs/spec/03 roles; the payments policies of revision 0005).
payer_of_org = org_member(OrgRole.OWNER, OrgRole.ADMIN, OrgRole.FINANCE)


def _built_provider(request: Request) -> PaymentProvider:
    """The provider on ``app.state`` (built from settings on first use and kept: the fake remembers its checkouts;
    tests install their own there). ``ConfigurationError`` when this server has none."""
    provider: PaymentProvider | None = getattr(request.app.state, "payment_provider", None)
    if provider is None:
        settings: Settings = request.app.state.settings
        provider = payment_provider_from_settings(settings)
        request.app.state.payment_provider = provider
    return provider


def get_payment_provider(request: Request) -> PaymentProvider:
    try:
        return _built_provider(request)
    except ConfigurationError as exc:
        raise ApiError(503, NOT_CONFIGURED, "Payments are not available on this server.") from exc


def get_optional_payment_provider(request: Request) -> PaymentProvider | None:
    try:
        return _built_provider(request)
    except ConfigurationError:
        return None


ProviderDep = Annotated[PaymentProvider, Depends(get_payment_provider)]
OptionalProviderDep = Annotated[PaymentProvider | None, Depends(get_optional_payment_provider)]


class PlanOut(BaseModel):
    code: str
    side: PlanSide
    name: str
    price_kes_minor: int
    interval: BillingInterval
    limits: dict[str, Any]
    is_default: bool
    purchasable: bool  # a checkout sells it (paid and self-serve)
    upgrade_to: str | None


class PlansOut(BaseModel):
    currency: str
    sample_prices: bool  # D-44: placeholders until G3, labelled "Sample prices, not final"
    simulated_checkout: bool  # D-36: the checkout is the fake one, labelled "Simulated M-Pesa"
    plans: list[PlanOut]


class CheckoutIn(BaseModel):
    """Only these fields: a checkout never takes an id or a reference from the client."""

    model_config = ConfigDict(extra="forbid")

    plan_code: str = Field(min_length=1, max_length=40)
    org_id: UUID | None = None  # pay for this organisation (owner, admin or finance); none: for oneself
    # Simulated checkouts only (the fake): what the simulated customer does. Refused by a real provider.
    simulate: SimulatedOutcome | None = None


class CheckoutOut(BaseModel):
    id: UUID
    plan_code: str
    plan_name: str
    side: PlanSide
    org_id: UUID | None
    amount_kes_minor: int
    currency: str
    status: PaymentStatus
    failure_code: str | None
    simulated: bool
    plan_active: bool  # the plan this checkout paid for was activated
    created_at: datetime
    settled_at: datetime | None
    poll_after_seconds: int | None  # while pending: ask again after this long


@plans_router.get("")
async def list_plans(settings: SettingsDep, side: PlanSide | None = None) -> PlansOut:
    """The plan catalogue (one side, or both), in ``plans.yaml`` order."""
    catalog = plans.load(settings.plans_file)
    return PlansOut(
        currency=CURRENCY,
        sample_prices=catalog.sample_prices,
        simulated_checkout=settings.payment_effective_provider == FAKE_PROVIDER_NAME,
        plans=[
            PlanOut(
                code=spec.code,
                side=spec.side,
                name=spec.name,
                price_kes_minor=spec.price_kes_minor,
                interval=spec.interval,
                limits=spec.limits,
                is_default=spec.default,
                purchasable=spec.purchasable,
                upgrade_to=spec.upgrade_to,
            )
            for spec in catalog.plans.values()
            if side is None or spec.side == side
        ],
    )


async def _out(db: Db, payment: Payment) -> CheckoutOut:
    plan = await db.get(Plan, payment.plan_id)
    if plan is None:  # plans are never deleted (payments reference them)
        raise not_found()
    pending = payment.status is PaymentStatus.PENDING
    return CheckoutOut(
        id=payment.id,
        plan_code=plan.code,
        plan_name=plan.name,
        side=plan.side,
        org_id=payment.org_id,
        amount_kes_minor=payment.amount_kes_minor,
        currency=CURRENCY,
        status=payment.status,
        failure_code=payment.failure_code,
        simulated=payment.provider == FAKE_PROVIDER_NAME,
        plan_active=payment.subscription_id is not None,
        created_at=payment.created_at,
        settled_at=payment.settled_at,
        poll_after_seconds=checkout.POLL_AFTER_SECONDS if pending else None,
    )


_PROVIDER_ERRORS: dict[int | str, dict[str, Any]] = {502: {"model": ApiErrorBody}, 503: {"model": ApiErrorBody}}
_START_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": CheckoutOut, "description": "The checkout of that plan already in progress"},
    **_PROVIDER_ERRORS,
}


@router.post(
    "/checkouts",
    status_code=status.HTTP_201_CREATED,
    responses=_START_RESPONSES,
)
async def start_checkout(
    body: CheckoutIn, response: Response, live: CurrentSession, db: Db, settings: SettingsDep, provider: ProviderDep
) -> CheckoutOut:
    """Start a checkout of a paid plan: 422 ``plan_not_available`` (unknown, default, free, custom or approval
    plans), 422 ``plan_wrong_side``, 403 ``not_a_developer``, 409 ``already_on_plan``, 409 ``checkout_pending`` (with
    ``checkout_id``: another plan's checkout is in progress), 502 ``payment_provider_error``, 503 ``not_configured``."""
    if body.org_id is not None:
        await payer_of_org(body.org_id, live, db)  # 404 to a non-member, 403 to another role; binds the organisation
        subject = checkout.Subject(org_id=body.org_id)
    else:
        if await db.get(DeveloperProfile, live.user.id) is None:
            raise checkout.not_a_developer()
        subject = checkout.Subject(user_id=live.user.id)
    payment, created = await checkout.start(
        db,
        settings,
        provider,
        actor_id=live.user.id,
        subject=subject,
        plan_code=body.plan_code,
        simulate=body.simulate,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return await _out(db, payment)


@router.get("/checkouts/{checkout_id}")
async def get_checkout(checkout_id: UUID, live: CurrentSession, db: Db, provider: OptionalProviderDep) -> CheckoutOut:
    """A checkout of the caller's (404 otherwise). Settles it when the provider has a final answer and activates a
    success; without a provider on this server it is shown as it stands."""
    payment = (await db.execute(select(Payment).where(Payment.id == checkout_id))).scalar_one_or_none()
    if payment is None:  # RLS: only the subject sees it
        raise not_found()
    if payment.org_id is not None:
        await payer_of_org(payment.org_id, live, db)  # the organisation's second-factor rules; binds it
    if provider is not None:
        await checkout.refresh(db, provider, payment, actor_id=live.user.id)
        await db.commit()
    return await _out(db, payment)
