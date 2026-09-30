"""The ``PaymentProvider`` interface (docs/spec/05 "Rails, behind a PaymentProvider interface"; REQ-BIL-04, interface
only; ADR-006).

Three calls, whatever the rail:

- ``initiate``: start a checkout for a pending ``payments`` row. The platform generates the row's ``provider_ref``
  (never the client, never the provider) and passes it in; M-Pesa's STK Push would send it as the account reference.
- ``query``: ask the provider how the checkout ended (Daraja: STK Push Query). This is the only answer that settles a
  payment: **callbacks never activate anything alone** (docs/spec/05, ADR-006 point 2).
- ``verify_callback``: check a callback's signature or lookup before anything reads it; a verified callback only tells
  the platform which checkout to ``query``.

The prototype has one implementation, ``FakePaymentProvider`` (D-36: no Daraja or Paystack code or accounts). Times
come from the caller as ``now`` on the app clock (``app_clock_now()``), so the dev/test clock drives the fake; a real
provider ignores it. No phone number crosses this interface or is stored.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

# A failure code is a code, never provider free text (payments.failure_code CHECK in revision 0005).
FAILURE_CODE_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"


class ProviderStatus(StrEnum):
    """How a checkout stands at the provider (the ``payment_status`` values)."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SimulatedOutcome(StrEnum):
    """What a simulated checkout does (``FakePaymentProvider`` only): the demo and the tests pick it; a real provider
    refuses any."""

    SUCCEED = "succeed"
    FAIL = "fail"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class CheckoutRequest:
    provider_ref: str  # platform-generated, unique (payments.provider_ref)
    amount_kes_minor: int  # the plan's price, as on the payments row
    plan_code: str
    simulated_outcome: SimulatedOutcome | None = None


@dataclass(frozen=True, slots=True)
class Initiated:
    provider_ref: str
    status: ProviderStatus  # pending: the customer still has to confirm


@dataclass(frozen=True, slots=True)
class QueryResult:
    status: ProviderStatus
    # The amount the provider took (checked against the payments row before a success settles anything); None while
    # pending or when the provider did not say.
    amount_kes_minor: int | None = None
    failure_code: str | None = None  # a code (FAILURE_CODE_PATTERN), for failed or cancelled only


@dataclass(frozen=True, slots=True)
class CallbackVerification:
    """A callback's verdict: ``provider_ref`` names the checkout to ``query`` when ``verified``; nothing else in the
    callback is trusted. ``event_id`` is the provider's id for the idempotency record (``webhook_events``,
    REQ-BIL-04)."""

    verified: bool
    provider_ref: str | None = None
    event_id: str | None = None


class PaymentProviderError(Exception):
    """The provider could not be reached or refused the request. ``transient`` follows the classification ported from
    ``reminder/notify.py`` (retry later) versus permanent (do not retry). ``code`` is a code, never provider text."""

    def __init__(self, code: str, *, transient: bool) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


class PaymentProvider(Protocol):
    """A payment rail. ``name`` is what ``payments.provider`` records; ``simulated`` is true only for the fake (the UI
    labels its checkout "Simulated M-Pesa", D-44)."""

    @property
    def name(self) -> str: ...

    @property
    def simulated(self) -> bool: ...

    async def initiate(self, request: CheckoutRequest, *, now: datetime) -> Initiated: ...

    async def query(self, provider_ref: str, *, now: datetime) -> QueryResult: ...

    async def verify_callback(self, headers: Mapping[str, str], body: bytes) -> CallbackVerification: ...
