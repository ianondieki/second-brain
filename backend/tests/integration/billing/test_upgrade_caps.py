"""REQ-BIL-08 with AC-SUB-1 re-run (P14 walkthrough step 2: 402 -> simulated M-Pesa upgrade -> publish): after an
activation the entitlements are the new plan's at once, so the 402 caps that stopped the subject allow more.

- A Free developer with 3 active proposals gets 402 on the 4th, follows the 402's upgrade plan through a checkout,
  and publishes the 4th.
- A Free developer with 5 tags on a proposal gets 402 on the 6th, upgrades, and pitches the 6th.
- An organisation on Claimed (1 scout agent) upgrades to Growth: its entitlements allow 5 scout agents (the scouts
  API, P10, reads the same entitlements).
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.billing.checkout_helpers import buy, instant, live_plans, status_of
from tests.integration.proposals.helpers import (
    Developers,
    ProposalWorld,
    create,
    draft_body,
    publish,
    published,
    user_of,
)
from tests.integration.proposals.pitch_helpers import Members, add_org, pitch, pitchable

pytestmark = pytest.mark.usefixtures("plans_seeded")


async def _upgrade(client: httpx.AsyncClient, plan: str) -> None:
    started = await buy(client, plan)
    assert started.status_code == 201, started.text
    ended = await status_of(client, started.json()["id"])
    assert (ended.json()["status"], ended.json()["plan_active"]) == ("succeeded", True)


async def test_an_upgraded_developer_publishes_past_the_free_cap(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    client = await developers()
    instant(client)
    for n in range(3):
        await published(client, proposal_world, title=f"Capped {n}")
    fourth = await create(client, draft_body(proposal_world, title="Capped 4"))
    refused = await publish(client, fourth["id"])
    assert refused.status_code == 402
    upgrade = refused.json()["detail"]["upgrade"]
    assert upgrade == {"plan": "dev_pro_monthly", "url": "/billing/upgrade?plan=dev_pro_monthly"}

    await _upgrade(client, upgrade["plan"])
    assert await live_plans(owner_engine, user=user_of(client)) == ["dev_pro_monthly"]
    allowed = await publish(client, fourth["id"])
    assert allowed.status_code == 200, allowed.text
    fifth = await published(client, proposal_world, title="Capped 5")  # unlimited on Pro
    assert fifth["proposal_id"]


async def test_an_upgraded_developer_pitches_past_the_free_tag_cap(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    orgs = [
        await add_org(owner_engine, f"Tagcap {n}", verification="unclaimed", niche_id=None, roles=None)
        for n in range(6)
    ]
    client, proposal_id = await pitchable(developers, proposal_world)
    instant(client)
    assert (await pitch(client, proposal_id, *orgs[:5])).status_code == 201
    refused = await pitch(client, proposal_id, orgs[5])
    assert refused.status_code == 402
    assert (refused.json()["detail"]["limit_key"], refused.json()["detail"]["limit"]) == ("tags_per_proposal", 5)

    await _upgrade(client, refused.json()["detail"]["upgrade"]["plan"])
    allowed = await pitch(client, proposal_id, orgs[5])
    assert allowed.status_code == 201, allowed.text


async def test_an_upgraded_organisation_is_allowed_more_scout_agents_at_once(
    member_client: Members, owner_engine: AsyncEngine
) -> None:
    org = await add_org(owner_engine, "Scoutco", verification="e2", niche_id=None, roles="{owner}")
    assert org.member is not None
    owner = await member_client(org.member)
    instant(owner)
    before = (await owner.get(f"/api/orgs/{org.id}/entitlements")).json()
    assert (before["plan"], before["limits"]["scout_agents"]) == ("org_claimed", 1)
    started = await buy(owner, "org_growth", org_id=str(org.id))
    assert (await status_of(owner, started.json()["id"])).json()["plan_active"] is True
    after = (await owner.get(f"/api/orgs/{org.id}/entitlements")).json()
    assert (after["plan"], after["limits"]["scout_agents"]) == ("org_growth", 5)
    assert after["limits"]["scout_frequencies"] == ["daily", "weekly", "on_new"]
