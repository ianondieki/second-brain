"""REQ-BIL-08 and the REQ-BIL-04 interface (P14; D-36, D-44): plans and the simulated M-Pesa checkout, on the real
routes, with ``FakePaymentProvider`` only.

- ``GET /api/plans``: the catalogue with the sample-price and simulated-checkout flags.
- ``POST /api/billing/checkouts``: a pending payment at the plan's price with a platform reference; refusals for an
  unknown, default, free, custom or approval plan, the wrong side, a non-developer, the current plan, a client-supplied
  id, reference or amount, and another plan's checkout in progress; the same plan's checkout in progress is answered
  again.
- ``GET /api/billing/checkouts/{id}``: pending until the provider answers (on the app clock), then succeeded (the plan
  active at once), failed or cancelled; an unknown reference fails; a success for another amount never activates.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.billing.providers.base import CheckoutRequest, Initiated, PaymentProviderError, QueryResult
from bridge.billing.providers.fake import FakePaymentProvider
from bridge.config import get_settings
from bridge.ids import uuid7
from tests.integration.api import refresh_csrf
from tests.integration.billing.checkout_helpers import (
    audit_actions,
    buy,
    install,
    instant,
    live_plans,
    payment_row,
    payments_of,
    slow,
    status_of,
)
from tests.integration.proposals.helpers import Developers, rows, user_of
from tests.integration.proposals.pitch_helpers import Members, add_org

pytestmark = pytest.mark.usefixtures("plans_seeded")

NOT_AVAILABLE = {"code": "plan_not_available", "message": "Choose a paid plan to upgrade to."}
WRONG_SIDE = {"code": "plan_wrong_side", "message": "This plan is for the other kind of account."}


# --- GET /api/plans ------------------------------------------------------------------------------------------------


async def test_the_plans_page_lists_sample_prices_and_a_simulated_checkout(developers: Developers) -> None:
    client = await developers()
    client.cookies.clear()  # public: no session needed
    body = (await client.get("/api/plans")).json()
    assert (body["currency"], body["sample_prices"], body["simulated_checkout"]) == ("KES", True, True)
    codes = [p["code"] for p in body["plans"]]
    assert codes == [
        "dev_free",
        "dev_pro_monthly",
        "dev_pro_yearly",
        "dev_student",
        "org_claimed",
        "org_starter",
        "org_growth",
        "org_enterprise",
        "org_social_impact",
    ]
    by_code = {p["code"]: p for p in body["plans"]}
    assert by_code["dev_pro_monthly"] | {"limits": None} == {
        "code": "dev_pro_monthly",
        "side": "developer",
        "name": "Pro (monthly)",
        "price_kes_minor": 49_900,
        "interval": "month",
        "limits": None,
        "is_default": False,
        "purchasable": True,
        "upgrade_to": None,
    }
    assert by_code["dev_pro_monthly"]["limits"]["active_proposals"] is None
    assert by_code["dev_free"]["upgrade_to"] == "dev_pro_monthly"
    sold = sorted(code for code, p in by_code.items() if p["purchasable"])
    assert sold == ["dev_pro_monthly", "dev_pro_yearly", "org_growth", "org_starter"]

    developer = (await client.get("/api/plans", params={"side": "developer"})).json()["plans"]
    assert {p["side"] for p in developer} == {"developer"}
    org = (await client.get("/api/plans", params={"side": "org"})).json()["plans"]
    assert [p["code"] for p in org] == codes[4:]
    assert (await client.get("/api/plans", params={"side": "staff"})).status_code == 422


# --- POST and GET: the developer's checkout ------------------------------------------------------------------------


async def test_a_checkout_starts_pending_at_the_plans_price_and_settles_on_the_providers_answer(
    developers: Developers, owner_engine: AsyncEngine
) -> None:
    client = await developers()
    instant(client)
    started = await buy(client, "dev_pro_monthly")
    assert started.status_code == 201, started.text
    body = started.json()
    checkout_id = body["id"]
    assert body | {"id": None, "created_at": None} == {
        "id": None,
        "plan_code": "dev_pro_monthly",
        "plan_name": "Pro (monthly)",
        "side": "developer",
        "org_id": None,
        "amount_kes_minor": 49_900,
        "currency": "KES",
        "status": "pending",
        "failure_code": None,
        "simulated": True,
        "plan_active": False,
        "created_at": None,
        "settled_at": None,
        "poll_after_seconds": 2,
    }
    row = await payment_row(owner_engine, checkout_id)
    assert (row.user_id, row.org_id, row.initiated_by) == (user_of(client), None, user_of(client))
    assert (row.amount_kes_minor, row.provider, row.status, row.plan_code) == (
        49_900,
        "fake",
        "pending",
        "dev_pro_monthly",
    )
    assert row.provider_ref.startswith("chk_")
    assert len(row.provider_ref) == 36
    assert "phone" not in row._mapping

    settled = (await status_of(client, checkout_id)).json()
    assert (settled["status"], settled["plan_active"], settled["poll_after_seconds"]) == ("succeeded", True, None)
    assert settled["settled_at"] is not None
    assert await live_plans(owner_engine, user=user_of(client)) == ["dev_pro_monthly"]
    ent = (await client.get("/api/me/entitlements")).json()
    assert (ent["plan"], ent["limits"]["active_proposals"]) == ("dev_pro_monthly", None)
    assert await audit_actions(owner_engine, checkout_id) == ["billing.checkout_started", "billing.checkout_settled"]

    again = (await status_of(client, checkout_id)).json()  # a repeated poll changes nothing
    assert again == settled
    assert len(await payments_of(owner_engine, user=user_of(client))) == 1
    assert await audit_actions(owner_engine, checkout_id) == ["billing.checkout_started", "billing.checkout_settled"]


async def test_a_paid_plan_replaces_the_free_subscription(developers: Developers, owner_engine: AsyncEngine) -> None:
    """A developer who signed up (free subscription row) ends with one live subscription: the paid one."""
    client = await developers()
    instant(client)
    [free] = await rows(owner_engine, "SELECT id FROM plans WHERE code = 'dev_free'")
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO subscriptions (id, user_id, plan_id, status, current_period_start)"
                " VALUES (:id, :u, :p, 'active', now())"
            ),
            {"id": uuid7(), "u": user_of(client), "p": free.id},
        )
    assert (await client.get("/api/me/entitlements")).json()["plan"] == "dev_free"
    checkout_id = (await buy(client, "dev_pro_yearly")).json()["id"]
    assert (await status_of(client, checkout_id)).json()["status"] == "succeeded"
    assert await live_plans(owner_engine, user=user_of(client)) == ["dev_pro_yearly"]
    sql = "SELECT pl.code, s.status FROM subscriptions s JOIN plans pl ON pl.id = s.plan_id WHERE s.user_id = :u"
    history = sorted((r.code, r.status) for r in await rows(owner_engine, sql, u=user_of(client)))
    assert history == [("dev_free", "cancelled"), ("dev_pro_yearly", "active")]


@pytest.mark.parametrize(
    ("simulate", "status", "code"),
    [("fail", "failed", "insufficient_funds"), ("cancel", "cancelled", "cancelled_by_customer")],
)
async def test_a_failed_or_cancelled_checkout_activates_nothing_and_a_new_one_may_start(
    developers: Developers, owner_engine: AsyncEngine, simulate: str, status: str, code: str
) -> None:
    client = await developers()
    instant(client)
    first = (await buy(client, "dev_pro_monthly", simulate=simulate)).json()
    ended = (await status_of(client, first["id"])).json()
    assert (ended["status"], ended["failure_code"], ended["plan_active"]) == (status, code, False)
    assert await live_plans(owner_engine, user=user_of(client)) == []
    assert (await client.get("/api/me/entitlements")).json()["plan"] == "dev_free"
    assert await audit_actions(owner_engine, first["id"]) == ["billing.checkout_started", "billing.checkout_settled"]
    # Settled: a new checkout starts (the ended one is not "in progress").
    retry = await buy(client, "dev_pro_monthly")
    assert retry.status_code == 201
    assert retry.json()["id"] != first["id"]
    assert (await status_of(client, retry.json()["id"])).json()["status"] == "succeeded"
    assert (await status_of(client, first["id"])).json()["status"] == status  # never changes afterwards


async def test_the_delay_runs_on_the_app_clock(
    developers: Developers, owner_engine: AsyncEngine, moved_clock: Any
) -> None:
    """Pending until the fake's delay has passed on app_clock_now(): moving the dev/test clock settles it."""
    client = await developers()
    slow(client, timedelta(minutes=10))
    checkout_id = (await buy(client, "dev_pro_monthly")).json()["id"]
    for _ in range(2):
        pending = (await status_of(client, checkout_id)).json()
        assert (pending["status"], pending["poll_after_seconds"]) == ("pending", 2)
    assert (await payment_row(owner_engine, checkout_id)).status == "pending"
    await moved_clock(timedelta(minutes=9))
    assert (await status_of(client, checkout_id)).json()["status"] == "pending"
    await moved_clock(timedelta(minutes=2))
    assert (await status_of(client, checkout_id)).json()["status"] == "succeeded"
    assert await live_plans(owner_engine, user=user_of(client)) == ["dev_pro_monthly"]


async def test_a_checkout_the_provider_never_started_fails_instead_of_staying_pending(
    developers: Developers, owner_engine: AsyncEngine
) -> None:
    """The API restarted (a new fake): the reference is unknown, so the checkout fails and a new one may start."""
    client = await developers()
    slow(client)
    checkout_id = (await buy(client, "dev_pro_monthly")).json()["id"]
    instant(client)  # a fresh provider that never heard of it
    ended = (await status_of(client, checkout_id)).json()
    assert (ended["status"], ended["failure_code"], ended["plan_active"]) == ("failed", "unknown_checkout", False)
    assert (await buy(client, "dev_pro_monthly")).status_code == 201


# --- refusals --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "plan_code",
    [
        "dev_free",
        "dev_student",
        "no_such_plan",
        "DEV_PRO_MONTHLY",
        "org_enterprise",
        "org_social_impact",
        "org_claimed",
    ],
)
async def test_only_a_paid_self_serve_plan_is_sold(
    developers: Developers, owner_engine: AsyncEngine, plan_code: str
) -> None:
    client = await developers()
    instant(client)
    refused = await buy(client, plan_code)
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == NOT_AVAILABLE
    assert await payments_of(owner_engine, user=user_of(client)) == []


async def test_a_plan_of_the_other_side_is_refused(
    developers: Developers, member_client: Members, owner_engine: AsyncEngine
) -> None:
    client = await developers()
    instant(client)
    for plan_code in ("org_starter", "org_growth"):
        refused = await buy(client, plan_code)
        assert (refused.status_code, refused.json()["detail"]) == (422, WRONG_SIDE)
    org = await add_org(owner_engine, "Sidecar Ltd", verification="e1", niche_id=None, roles="{finance}")
    assert org.member is not None
    finance = await member_client(org.member)
    instant(finance)
    refused = await buy(finance, "dev_pro_monthly", org_id=str(org.id))
    assert (refused.status_code, refused.json()["detail"]) == (422, WRONG_SIDE)
    # A finance member without a developer profile cannot buy a developer plan for themselves either.
    refused = await buy(finance, "dev_pro_monthly")
    assert refused.status_code == 403
    assert refused.json()["detail"] == {
        "code": "not_a_developer",
        "message": "Developer plans are for developer accounts.",
    }
    assert await payments_of(owner_engine, org=org.id) == []
    assert await payments_of(owner_engine, user=org.member) == []


@pytest.mark.parametrize(
    "extra",
    [
        {"id": "01900000-0000-7000-8000-000000000001"},
        {"provider_ref": "chk_chosen_by_the_client_0000000000000"},
        {"amount_kes_minor": 1},
        {"provider": "fake"},
        {"user_id": "01900000-0000-7000-8000-000000000002"},
    ],
)
async def test_the_client_never_supplies_an_id_reference_or_amount(
    developers: Developers, owner_engine: AsyncEngine, extra: dict[str, Any]
) -> None:
    client = await developers()
    instant(client)
    refused = await buy(client, "dev_pro_monthly", **extra)
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["type"] == "extra_forbidden"
    assert await payments_of(owner_engine, user=user_of(client)) == []


async def test_a_checkout_in_progress_is_answered_again_and_blocks_another_plan(
    developers: Developers, owner_engine: AsyncEngine
) -> None:
    client = await developers()
    slow(client)
    first = await buy(client, "dev_pro_monthly")
    assert first.status_code == 201
    again = await buy(client, "dev_pro_monthly")
    assert again.status_code == 200
    assert again.json() == first.json()
    other = await buy(client, "dev_pro_yearly")
    assert other.status_code == 409
    assert other.json()["detail"] == {
        "code": "checkout_pending",
        "message": "Another checkout is still in progress. Wait for it to finish, then try again.",
        "checkout_id": first.json()["id"],
    }
    assert len(await payments_of(owner_engine, user=user_of(client))) == 1


async def test_a_pending_checkout_that_has_ended_no_longer_blocks(
    developers: Developers, owner_engine: AsyncEngine
) -> None:
    """Starting a checkout first asks the provider about the subject's pending ones: a finished one settles (and
    activates) instead of blocking, even when nobody polled it."""
    client = await developers()
    instant(client)
    first = (await buy(client, "dev_pro_monthly", simulate="cancel")).json()
    other = await buy(client, "dev_pro_yearly")  # never polled the first: it is settled now
    assert other.status_code == 201
    assert (await payment_row(owner_engine, first["id"])).status == "cancelled"


async def test_the_current_plan_is_not_sold_again(developers: Developers, owner_engine: AsyncEngine) -> None:
    client = await developers()
    instant(client)
    checkout_id = (await buy(client, "dev_pro_monthly")).json()["id"]
    assert (await status_of(client, checkout_id)).json()["plan_active"] is True
    refused = await buy(client, "dev_pro_monthly")
    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "already_on_plan", "message": "You are already on this plan."}
    assert len(await payments_of(owner_engine, user=user_of(client))) == 1
    assert (await buy(client, "dev_pro_yearly")).status_code == 201  # another plan is fine


async def test_a_session_is_needed(developers: Developers) -> None:
    client = await developers()
    instant(client)
    client.cookies.delete(get_settings().session_cookie_name)
    await refresh_csrf(client)  # a CSRF token of the signed-out browser
    for response in (await buy(client, "dev_pro_monthly"), await status_of(client, str(UUID(int=1)))):
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "unauthenticated"


# --- provider edges -------------------------------------------------------------------------------------------------


class _Broken(FakePaymentProvider):
    """A provider that cannot start a checkout."""

    def __init__(self, *, transient: bool) -> None:
        super().__init__(delay=timedelta(0))
        self.transient = transient

    async def initiate(self, request: CheckoutRequest, *, now: datetime) -> Initiated:
        raise PaymentProviderError("upstream_down", transient=self.transient)


class _ShortChange(FakePaymentProvider):
    """A real-looking provider (no simulation) that reports a success for another amount."""

    @property
    def simulated(self) -> bool:
        return False

    async def query(self, provider_ref: str, *, now: datetime) -> QueryResult:
        result = await super().query(provider_ref, now=now)
        return QueryResult(result.status, amount_kes_minor=1, failure_code=result.failure_code)


class _Unreachable(FakePaymentProvider):
    async def query(self, provider_ref: str, *, now: datetime) -> QueryResult:
        raise PaymentProviderError("timeout", transient=True)

    async def verify_callback(self, headers: Mapping[str, str], body: bytes) -> Any:
        raise AssertionError("never called by the checkout routes")


@pytest.mark.parametrize(("transient", "code"), [(True, "provider_unavailable"), (False, "provider_refused")])
async def test_a_provider_that_cannot_start_the_checkout_fails_it(
    developers: Developers, owner_engine: AsyncEngine, transient: bool, code: str
) -> None:
    client = await developers()
    install(client, _Broken(transient=transient))
    refused = await buy(client, "dev_pro_monthly")
    assert refused.status_code == 502
    assert refused.json()["detail"] == {
        "code": "payment_provider_error",
        "message": "The payment could not be started. Try again in a few minutes.",
    }
    [row] = await payments_of(owner_engine, user=user_of(client))
    assert (row.status, row.failure_code, row.subscription_id) == ("failed", code, None)
    instant(client)
    assert (await buy(client, "dev_pro_monthly")).status_code == 201  # a failed checkout never blocks


async def test_a_success_for_another_amount_never_activates(developers: Developers, owner_engine: AsyncEngine) -> None:
    client = await developers()
    install(client, _ShortChange(delay=timedelta(0)))
    started = await buy(client, "dev_pro_monthly")
    assert started.json()["simulated"] is True  # recorded as the fake (the only provider the schema admits)
    ended = (await status_of(client, started.json()["id"])).json()
    assert (ended["status"], ended["failure_code"], ended["plan_active"]) == ("failed", "amount_mismatch", False)
    assert await live_plans(owner_engine, user=user_of(client)) == []


async def test_a_simulated_outcome_needs_a_simulating_provider(
    developers: Developers, owner_engine: AsyncEngine
) -> None:
    client = await developers()
    install(client, _ShortChange(delay=timedelta(0)))
    refused = await buy(client, "dev_pro_monthly", simulate="succeed")
    assert refused.status_code == 422
    assert refused.json()["detail"] == {
        "code": "simulation_not_available",
        "message": "This checkout cannot be simulated.",
    }
    assert await payments_of(owner_engine, user=user_of(client)) == []


async def test_an_unreachable_provider_leaves_the_checkout_pending(
    developers: Developers, owner_engine: AsyncEngine
) -> None:
    client = await developers()
    install(client, _Unreachable(delay=timedelta(0)))
    checkout_id = (await buy(client, "dev_pro_monthly")).json()["id"]
    assert (await status_of(client, checkout_id)).json()["status"] == "pending"
    assert (await payment_row(owner_engine, checkout_id)).status == "pending"


async def test_without_a_provider_checkouts_answer_503_and_existing_ones_are_shown(
    developers: Developers, owner_engine: AsyncEngine
) -> None:
    """Fail closed: a server with no payment provider (staging and production today) starts nothing."""
    client = await developers()
    slow(client)
    checkout_id = (await buy(client, "dev_pro_monthly")).json()["id"]
    app = client.app  # type: ignore[attr-defined]
    app.state.payment_provider = None
    app.state.settings = app.state.settings.model_copy(update={"app_env": "staging"})
    refused = await buy(client, "dev_pro_yearly")
    assert refused.status_code == 503
    assert refused.json()["detail"] == {
        "code": "not_configured",
        "message": "Payments are not available on this server.",
    }
    shown = await status_of(client, checkout_id)
    assert (shown.status_code, shown.json()["status"]) == (200, "pending")
    assert (await client.get("/api/plans")).json()["simulated_checkout"] is False
    assert len(await payments_of(owner_engine, user=user_of(client))) == 1
