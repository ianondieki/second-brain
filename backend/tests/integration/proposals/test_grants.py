"""``grant_on_tag`` (REQ-REPO-01, REQ-BIL-03; docs/spec/06 6.1): the owner's default policy, "auto-grant to orgs I
tagged", as the Pitch flow (P4) will call it after delivering a tag to an E2 organisation."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from bridge.proposals.grants import GrantError
from tests.integration.proposals.helpers import Developers, ProposalWorld, published, rows, user_of
from tests.integration.proposals.tier2_scene import add_e2_org, apply_grant, deliver_tag, new_template, run

GRANTS = (
    "SELECT id, status, source, tier, counts_as_unlock, billing_month, granted_by, granted_at IS NOT NULL AS granted"
    " FROM disclosure_grants WHERE proposal_id = :p AND org_id = :org"
)
EVENTS = (
    "SELECT action, payload FROM audit_events WHERE actor_user_id = :u AND action LIKE 'tier2.grant_%' ORDER BY seq"
)


async def _setup(
    developers: Developers, world: ProposalWorld, owner_engine: AsyncEngine, *, tag: bool = True
) -> tuple[UUID, UUID, UUID]:
    owner = await developers()
    proposal_id = UUID((await published(owner, world))["proposal_id"])
    async with owner_engine.begin() as conn:
        terms = await new_template(conn, "master_enterprise_terms")
        org = await add_e2_org(conn, "Grantee Limited", f"g-{uuid7().hex[-10:]}.example.test", terms, "{signatory}")
    if tag:
        await deliver_tag(owner_engine, proposal_id, org, user_of(owner))
    return user_of(owner), proposal_id, org


async def test_a_delivered_tag_grants_tier2_once_and_never_counts_as_an_unlock(
    developers: Developers, proposal_world: ProposalWorld, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    owner, proposal, org = await _setup(developers, proposal_world, owner_engine)
    first = await apply_grant(app_engine, owner, proposal, org)
    again = await apply_grant(app_engine, owner, proposal, org)
    assert first is not None
    assert again == first
    [grant] = await rows(owner_engine, GRANTS, p=proposal, org=org)
    assert (grant.id, grant.status, grant.source, grant.tier) == (first, "active", "auto_tagged", 2)
    assert (grant.counts_as_unlock, grant.billing_month, grant.granted_by, grant.granted) == (False, None, owner, True)
    [event] = await rows(owner_engine, EVENTS, u=owner)
    assert event.action == "tier2.grant_created"
    assert event.payload == {"grant_id": str(first), "org_id": str(org), "tier": 2, "source": "auto_tagged"}


async def test_an_organisations_pending_request_is_activated_by_the_tag(
    developers: Developers, proposal_world: ProposalWorld, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    owner, proposal, org = await _setup(developers, proposal_world, owner_engine)
    requested = uuid7()
    async with owner_engine.begin() as conn:
        await run(
            conn,
            "INSERT INTO disclosure_grants (id, proposal_id, org_id, owner_id, tier, status, source)"
            " VALUES (:id, :p, :org, :owner, 2, 'requested', 'org_interest')",
            id=requested,
            p=proposal,
            org=org,
            owner=owner,
        )
    assert await apply_grant(app_engine, owner, proposal, org) == requested
    [grant] = await rows(owner_engine, GRANTS, p=proposal, org=org)
    assert (grant.status, grant.source, grant.granted_by) == ("active", "org_interest", owner)
    assert [e.action for e in await rows(owner_engine, EVENTS, u=owner)] == ["tier2.grant_activated"]


async def test_the_manual_policy_grants_nothing_on_a_tag(
    developers: Developers, proposal_world: ProposalWorld, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    owner, proposal, org = await _setup(developers, proposal_world, owner_engine)
    async with owner_engine.begin() as conn:
        await run(conn, "UPDATE proposals SET tier2_policy = 'manual' WHERE id = :p", p=proposal)
    assert await apply_grant(app_engine, owner, proposal, org) is None
    assert await rows(owner_engine, GRANTS, p=proposal, org=org) == []


@pytest.mark.parametrize("case", ["no_tag", "not_the_owner", "withdrawn_tag"])
async def test_a_grant_needs_the_owner_and_their_open_delivered_tag(
    developers: Developers,
    proposal_world: ProposalWorld,
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    case: str,
) -> None:
    owner, proposal, org = await _setup(developers, proposal_world, owner_engine, tag=case != "no_tag")
    caller = owner
    if case == "not_the_owner":
        caller = user_of(await developers())
    if case == "withdrawn_tag":
        async with owner_engine.begin() as conn:
            await run(conn, "UPDATE tags SET status = 'withdrawn' WHERE proposal_id = :p", p=proposal)
    with pytest.raises(GrantError):
        await apply_grant(app_engine, caller, proposal, org)
    assert await rows(owner_engine, GRANTS, p=proposal, org=org) == []
