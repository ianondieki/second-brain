"""The REQ-BIL-04 interface on the real routes (D-36): the provider a server builds for itself, and what a provider may
put in the ledger.

- A server whose tests installed no provider builds the one the settings name (the fake in test) on first use and keeps
  it: the fake remembers its checkouts, so a later read finds the checkout pending instead of unknown.
- A provider that ends a checkout without a failure code, or with its own free text, is stored with the platform's code
  (``provider_failed`` / ``provider_cancelled``): ``payments.failure_code`` is a code, never provider text.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.billing.providers.base import ProviderStatus, QueryResult
from bridge.billing.providers.fake import FakePaymentProvider
from tests.integration.billing.checkout_helpers import buy, install, live_plans, payment_row, status_of
from tests.integration.proposals.helpers import Developers, user_of

pytestmark = pytest.mark.usefixtures("plans_seeded")


async def test_the_server_builds_the_configured_provider_once_and_keeps_it(
    developers: Developers, owner_engine: AsyncEngine
) -> None:
    client = await developers()
    app = client.app  # type: ignore[attr-defined]
    assert getattr(app.state, "payment_provider", None) is None  # nothing installed: the settings decide
    app.state.settings = app.state.settings.model_copy(update={"fake_payment_delay_seconds": 300})
    started = await buy(client, "dev_pro_monthly")
    assert started.status_code == 201, started.text
    built = app.state.payment_provider
    assert isinstance(built, FakePaymentProvider)
    assert built.delay == timedelta(seconds=300)

    again = await status_of(client, started.json()["id"])
    assert app.state.payment_provider is built  # kept, not rebuilt per request
    assert (again.json()["status"], again.json()["failure_code"]) == ("pending", None)  # a new fake would not know it
    assert (await payment_row(owner_engine, started.json()["id"])).status == "pending"


class _Scripted(FakePaymentProvider):
    """A provider that ends every checkout with ``status`` and ``failure_code`` as it chooses."""

    def __init__(self, status: ProviderStatus, failure_code: str | None) -> None:
        super().__init__(delay=timedelta(0))
        self.status, self.failure_code = status, failure_code

    @property
    def simulated(self) -> bool:
        return False

    async def query(self, provider_ref: str, *, now: datetime) -> QueryResult:
        return QueryResult(self.status, failure_code=self.failure_code)


@pytest.mark.parametrize(
    ("status", "said", "stored"),
    [
        (ProviderStatus.FAILED, None, "provider_failed"),
        (ProviderStatus.FAILED, "Insufficient funds (M-Pesa said so)", "provider_failed"),
        (ProviderStatus.CANCELLED, "x" * 41, "provider_cancelled"),  # a code shape, but too long
    ],
    ids=["no-code", "free-text", "too-long"],
)
async def test_a_providers_own_words_never_become_the_failure_code(
    developers: Developers, owner_engine: AsyncEngine, status: ProviderStatus, said: str | None, stored: str
) -> None:
    client = await developers()
    install(client, _Scripted(status, said))
    checkout_id = (await buy(client, "dev_pro_monthly")).json()["id"]
    ended = (await status_of(client, checkout_id)).json()
    assert (ended["status"], ended["failure_code"], ended["plan_active"]) == (status.value, stored, False)
    row = await payment_row(owner_engine, checkout_id)
    assert (row.status, row.failure_code, row.subscription_id) == (status.value, stored, None)
    assert await live_plans(owner_engine, user=user_of(client)) == []
