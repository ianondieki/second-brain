"""REQ-BIL-08 (P14 demo seed; D-36): nothing paid, and a used database keeps what the walkthrough bought.

``seed_demo_subscriptions`` gives demo developers and organisations with a demo member their side's free plan when
they have no live subscription; running it again adds nothing, keeps a plan bought through the simulated checkout,
writes no payment and never touches accounts that are not demo accounts. It refuses to run outside dev and test.
P28 (REQ-TEN-02, REQ-ENG-17): State Department D, by its name and with a demo member, starts on Growth instead, a
seeded row with no payment, once.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.seed.demo.data import STATE_D
from bridge.seed.demo.subscriptions import DemoSeedRefused, seed_demo_subscriptions
from tests.integration.billing.checkout_helpers import buy, instant, live_plans, status_of
from tests.integration.proposals.helpers import Developers, add_developer, rows, user_of
from tests.integration.proposals.pitch_helpers import add_org

pytestmark = pytest.mark.usefixtures("plans_seeded")


async def _demo(owner_engine: AsyncEngine, *users: UUID) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET demo_account = true WHERE id = ANY(:ids)"), {"ids": list(users)})


async def _seed(owner_engine: AsyncEngine) -> dict[str, int]:
    async with owner_engine.begin() as conn:
        return await seed_demo_subscriptions(conn, get_settings())


async def _payment_count(owner_engine: AsyncEngine) -> int:
    return int((await rows(owner_engine, "SELECT count(*) FROM payments"))[0][0])


async def test_demo_subjects_start_free_and_a_reseed_keeps_what_the_walkthrough_bought(
    developers: Developers, owner_engine: AsyncEngine
) -> None:
    fresh = await add_developer(owner_engine)
    upgraded = await developers()
    bystander = await add_developer(owner_engine)  # not a demo account
    org = await add_org(owner_engine, "Demo Telco (fixture)", verification="e2", niche_id=None, roles="{owner}")
    plain_org = await add_org(owner_engine, "Plain Org", verification="e1", niche_id=None, roles="{owner}")
    assert org.member is not None
    await _demo(owner_engine, fresh, user_of(upgraded), org.member)
    payments_before = await _payment_count(owner_engine)

    first = await _seed(owner_engine)
    assert first["developer"] >= 2
    assert first["org"] >= 1
    assert await live_plans(owner_engine, user=fresh) == ["dev_free"]
    assert await live_plans(owner_engine, user=user_of(upgraded)) == ["dev_free"]
    assert await live_plans(owner_engine, org=org.id) == ["org_claimed"]
    assert await live_plans(owner_engine, user=bystander) == []
    assert await live_plans(owner_engine, org=plain_org.id) == []
    assert await _payment_count(owner_engine) == payments_before  # nothing paid by default

    # The walkthrough upgrades live; the seed runs again on the used database.
    instant(upgraded)
    checkout_id = (await buy(upgraded, "dev_pro_monthly")).json()["id"]
    assert (await status_of(upgraded, checkout_id)).json()["plan_active"] is True
    payments_after_walkthrough = await _payment_count(owner_engine)

    again = await _seed(owner_engine)
    assert again == {"showcase": 0, "developer": 0, "org": 0}
    assert await live_plans(owner_engine, user=user_of(upgraded)) == ["dev_pro_monthly"]
    assert await live_plans(owner_engine, user=fresh) == ["dev_free"]
    assert await live_plans(owner_engine, org=org.id) == ["org_claimed"]
    assert await _payment_count(owner_engine) == payments_after_walkthrough
    [payment] = await rows(owner_engine, "SELECT status, subscription_id FROM payments WHERE id = :id", id=checkout_id)
    assert payment.status == "succeeded"
    assert payment.subscription_id is not None


@pytest.mark.parametrize("env", ["staging", "production"])
async def test_the_demo_seed_refuses_outside_dev_and_test(owner_engine: AsyncEngine, env: str) -> None:
    settings = get_settings().model_copy(update={"app_env": env})
    async with owner_engine.begin() as conn:
        with pytest.raises(DemoSeedRefused, match="only in dev and test"):
            await seed_demo_subscriptions(conn, settings)


async def test_state_department_d_starts_on_growth_once_with_no_payment(owner_engine: AsyncEngine) -> None:
    """Its free plan (the sign-up's) is moved to Growth; a plan another way gave it is kept; a lookalike without a demo
    member gets nothing; no payment is written; a re-run changes nothing."""
    showcase = await add_org(owner_engine, "State D (test)", verification="e2", niche_id=None, roles="{owner,admin}")
    lookalike = await add_org(owner_engine, "Lookalike (test)", verification="e2", niche_id=None, roles="{owner}")
    assert showcase.member is not None
    async with owner_engine.begin() as conn:
        renamed = {"n": STATE_D.legal_name, "o": showcase.id}
        await conn.execute(text("UPDATE organizations SET legal_name = :n WHERE id = :o"), renamed)
        await conn.execute(  # as the owner's sign-up starts it
            text(
                "INSERT INTO subscriptions (id, org_id, plan_id, status, current_period_start)"
                " SELECT uuid7(), :o, id, 'active', now() FROM plans WHERE code = 'org_claimed'"
            ),
            {"o": showcase.id},
        )
    await _demo(owner_engine, showcase.member)  # the lookalike has no demo member: never a showcase
    payments_before = await _payment_count(owner_engine)
    first = await _seed(owner_engine)
    assert first["showcase"] == 1
    assert await live_plans(owner_engine, org=showcase.id) == ["org_growth"]
    assert await live_plans(owner_engine, org=lookalike.id) == []
    again = await _seed(owner_engine)
    assert again["showcase"] == 0
    assert await live_plans(owner_engine, org=showcase.id) == ["org_growth"]
    async with owner_engine.begin() as conn:  # as if the walkthrough had bought Enterprise
        await conn.execute(
            text(
                "UPDATE subscriptions SET plan_id = (SELECT id FROM plans WHERE code = 'org_enterprise')"
                " WHERE org_id = :o"
            ),
            {"o": showcase.id},
        )
    assert (await _seed(owner_engine))["showcase"] == 0
    assert await live_plans(owner_engine, org=showcase.id) == ["org_enterprise"]
    assert await _payment_count(owner_engine) == payments_before
