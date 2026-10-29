"""REQ-BIL-04 (the interface; D-36, ADR-006 point 2): a confirmation is the provider's answer to the platform's own
query, never a message someone sends. On ``FakePaymentProvider`` with a delay on the app clock: a forged confirmation
(the client claiming success on the checkout, restarting it with a status, or a callback naming its real reference)
settles and records nothing; after the configured delay the checkout succeeds once, however often and however
concurrently it is confirmed. (The delay itself, the repeated poll and parallel first reads are ``test_checkouts.py``'s
and ``test_checkout_tenancy.py``'s.)
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.billing.checkout_helpers import (
    audit_actions,
    buy,
    live_plans,
    payment_row,
    payments_of,
    slow,
    status_of,
)
from tests.integration.proposals.helpers import Developers, rows, user_of

pytestmark = pytest.mark.usefixtures("plans_seeded")


async def test_a_forged_confirmation_settles_nothing_and_the_real_one_settles_once(
    developers: Developers, owner_engine: AsyncEngine, moved_clock: Any
) -> None:
    client = await developers()
    provider = slow(client, timedelta(minutes=10))
    started = await buy(client, "dev_pro_monthly")
    assert started.status_code == 201, started.text
    checkout_id = started.json()["id"]
    reference = (await payment_row(owner_engine, checkout_id)).provider_ref
    forged = {"status": "succeeded", "provider_ref": reference, "amount_kes_minor": 49_900}

    for method in ("POST", "PUT", "PATCH"):  # no route writes a checkout's status
        claimed = await client.request(method, f"/api/billing/checkouts/{checkout_id}", json=forged)
        assert claimed.status_code == 405, (method, claimed.text)
    restarted = await buy(client, "dev_pro_monthly", status="succeeded")
    assert restarted.status_code == 422
    assert restarted.json()["detail"][0]["type"] == "extra_forbidden"
    callback = await provider.verify_callback({"x-signature": "forged"}, json.dumps(forged).encode())
    assert (callback.verified, callback.provider_ref, callback.event_id) == (False, None, None)

    pending = (await status_of(client, checkout_id)).json()
    assert (pending["status"], pending["plan_active"], pending["settled_at"]) == ("pending", False, None)
    assert (await payment_row(owner_engine, checkout_id)).status == "pending"
    assert await live_plans(owner_engine, user=user_of(client)) == []
    assert (await client.get("/api/me/entitlements")).json()["plan"] == "dev_free"
    assert await audit_actions(owner_engine, checkout_id) == ["billing.checkout_started"]

    await moved_clock(timedelta(minutes=10))  # the configured delay has passed: the provider now says succeeded
    reads = await asyncio.gather(*(status_of(client, checkout_id) for _ in range(4)))
    reads.append(await status_of(client, checkout_id))
    assert {(r.status_code, r.json()["status"], r.json()["plan_active"]) for r in reads} == {(200, "succeeded", True)}
    assert len({r.json()["settled_at"] for r in reads}) == 1  # settled once; later reads show that settlement
    assert await live_plans(owner_engine, user=user_of(client)) == ["dev_pro_monthly"]
    [subscription] = await rows(owner_engine, "SELECT id FROM subscriptions WHERE user_id = :u", u=user_of(client))
    assert (await payment_row(owner_engine, checkout_id)).subscription_id == subscription.id
    assert len(await payments_of(owner_engine, user=user_of(client))) == 1
    assert await audit_actions(owner_engine, checkout_id) == ["billing.checkout_started", "billing.checkout_settled"]
