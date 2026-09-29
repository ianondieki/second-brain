"""``FakePaymentProvider``: the prototype's simulated M-Pesa checkout (D-36; REQ-BIL-04 interface only).

It moves no money and calls nothing. ``initiate`` remembers the checkout; ``query`` answers **pending** until
``delay`` has passed on the app clock since ``initiate`` (the caller passes ``now`` from ``app_clock_now()``, so the
dev/test clock drives it), then the scripted outcome:

- ``succeed`` (the default): succeeded, for the amount initiated;
- ``fail``: failed with ``insufficient_funds``;
- ``cancel``: cancelled with ``cancelled_by_customer``.

The demo and the tests choose the outcome with the checkout's ``simulated_outcome`` (``POST /api/billing/checkouts``
field ``simulate``); no phone number is asked for or kept. A reference it never started (the API process restarted
since) answers failed with ``unknown_checkout``, so a checkout never stays pending for ever. It keeps at most
``MAX_CHECKOUTS`` checkouts in memory (the oldest go first, then answer ``unknown_checkout``).

It runs only where ``APP_ENV`` is dev or test: ``payment_provider_from_settings`` refuses it elsewhere, and the
settings refuse ``PAYMENT_PROVIDER=fake`` in staging and production at start-up. It has no callbacks: every
``verify_callback`` is refused.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from bridge.billing.providers.base import (
    CallbackVerification,
    CheckoutRequest,
    Initiated,
    ProviderStatus,
    QueryResult,
    SimulatedOutcome,
)

FAKE_PROVIDER_NAME = "fake"  # payments.provider (revision 0005 admits only this value)
MAX_CHECKOUTS = 10_000
UNKNOWN_CHECKOUT = "unknown_checkout"
OUTCOMES: dict[SimulatedOutcome, tuple[ProviderStatus, str | None]] = {
    SimulatedOutcome.SUCCEED: (ProviderStatus.SUCCEEDED, None),
    SimulatedOutcome.FAIL: (ProviderStatus.FAILED, "insufficient_funds"),
    SimulatedOutcome.CANCEL: (ProviderStatus.CANCELLED, "cancelled_by_customer"),
}


@dataclass(frozen=True, slots=True)
class _Checkout:
    started_at: datetime
    amount_kes_minor: int
    outcome: SimulatedOutcome


class FakePaymentProvider:
    """A simulated checkout that settles ``delay`` after it starts (see the module docstring)."""

    def __init__(self, *, delay: timedelta) -> None:
        if delay < timedelta(0):
            raise ValueError("the delay cannot be negative")
        self.delay = delay
        self._checkouts: OrderedDict[str, _Checkout] = OrderedDict()

    @property
    def name(self) -> str:
        return FAKE_PROVIDER_NAME

    @property
    def simulated(self) -> bool:
        return True

    async def initiate(self, request: CheckoutRequest, *, now: datetime) -> Initiated:
        if request.provider_ref in self._checkouts:
            raise ValueError("a checkout with this reference was already started")
        outcome = request.simulated_outcome or SimulatedOutcome.SUCCEED
        self._checkouts[request.provider_ref] = _Checkout(now, request.amount_kes_minor, outcome)
        while len(self._checkouts) > MAX_CHECKOUTS:
            self._checkouts.popitem(last=False)
        return Initiated(request.provider_ref, ProviderStatus.PENDING)

    async def query(self, provider_ref: str, *, now: datetime) -> QueryResult:
        checkout = self._checkouts.get(provider_ref)
        if checkout is None:
            return QueryResult(ProviderStatus.FAILED, failure_code=UNKNOWN_CHECKOUT)
        if now < checkout.started_at + self.delay:
            return QueryResult(ProviderStatus.PENDING)
        status, failure_code = OUTCOMES[checkout.outcome]
        amount = checkout.amount_kes_minor if status is ProviderStatus.SUCCEEDED else None
        return QueryResult(status, amount_kes_minor=amount, failure_code=failure_code)

    async def verify_callback(self, headers: Mapping[str, str], body: bytes) -> CallbackVerification:
        """The fake is polled only: it never sends a callback, so none is ever verified."""
        return CallbackVerification(verified=False)
