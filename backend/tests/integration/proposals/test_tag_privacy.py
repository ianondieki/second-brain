"""AC-REPO-6/a (REQ-REPO-03; docs/spec/06 6.1, 6.3): for a proposal tagged to Safaricom, Airtel and Telkom, a Tier-1
GET, search results and another organisation's Inbox contain none of those organisation names or ids. A tagged
organisation's own Inbox names none of the others either, and Row-Level Security shows an organisation's members its
own delivered tag only."""

from __future__ import annotations

from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from tests.integration.proposals.helpers import Developers, ProposalWorld
from tests.integration.proposals.pitch_helpers import Members, Org, PitchOrgs, pitch, pitchable


def assert_names_none_of(body: str, orgs: list[Org], engagement_ids: list[str], where: str) -> None:
    for org in orgs:
        assert org.name not in body, f"{org.name} in {where}"
        assert str(org.id) not in body, f"{org.name}'s id in {where}"
        assert org.slug not in body, f"{org.name}'s slug in {where}"
    for engagement_id in engagement_ids:
        assert engagement_id not in body, f"another organisation's engagement in {where}"


async def visible_tags(app_engine: AsyncEngine, user_id: UUID, proposal_id: str) -> list[UUID]:
    async with create_session_factory(app_engine)() as db:
        await bind_tenant(db, user_id=user_id)
        result = await db.execute(text("SELECT org_id FROM tags WHERE proposal_id = :p"), {"p": proposal_id})
        return list(result.scalars().all())


async def test_tagged_organisations_never_leak(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    member_client: Members,
    app_engine: AsyncEngine,
) -> None:
    token = "tp" + pitch_orgs.tag
    dev, proposal_id = await pitchable(developers, proposal_world, title=f"Signal gaps {token}")
    tagged = [pitch_orgs.safaricom, pitch_orgs.airtel, pitch_orgs.telkom]
    response = await pitch(dev, proposal_id, *tagged)
    assert response.status_code == 201, response.text
    engagement = {tag["org"]["id"]: tag["engagement_id"] for tag in response.json()["tags"]}
    safaricom_engagement = engagement[str(pitch_orgs.safaricom.id)]
    airtel_engagement = engagement[str(pitch_orgs.airtel.id)]

    bystander = await member_client(pitch_orgs.bystander.member)  # type: ignore[arg-type]
    other_developer = await developers()
    pages: dict[str, httpx.Response] = {
        "Tier-1 GET (another organisation)": await bystander.get(f"/api/proposals/{proposal_id}"),
        "Tier-1 GET (another developer)": await other_developer.get(f"/api/proposals/{proposal_id}"),
        "search": await bystander.get("/api/proposals", params={"q": token}),
        "another organisation's Inbox": await bystander.get(f"/api/orgs/{pitch_orgs.bystander.id}/inbox"),
    }
    for where, page in pages.items():
        assert page.status_code == 200, (where, page.text)
        assert_names_none_of(page.text, tagged, [safaricom_engagement, airtel_engagement], where)
    assert proposal_id in pages["search"].text  # the search did find the proposal
    assert pages["another organisation's Inbox"].json()["items"] == []

    # A tagged organisation sees the proposal and its own engagement, and nothing of the other two.
    airtel = await member_client(pitch_orgs.airtel.member)  # type: ignore[arg-type]
    inbox = await airtel.get(f"/api/orgs/{pitch_orgs.airtel.id}/inbox")
    [item] = inbox.json()["items"]
    assert (item["proposal"]["id"], item["engagement"]["id"]) == (proposal_id, airtel_engagement)
    assert_names_none_of(
        inbox.text, [pitch_orgs.safaricom, pitch_orgs.telkom], [safaricom_engagement], "Airtel's Inbox"
    )

    # The database agrees: members see their own delivered tag only; another organisation sees none.
    assert await visible_tags(app_engine, pitch_orgs.airtel.member, proposal_id) == [pitch_orgs.airtel.id]  # type: ignore[arg-type]
    assert await visible_tags(app_engine, pitch_orgs.bystander.member, proposal_id) == []  # type: ignore[arg-type]


async def test_the_inbox_is_members_only(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, member_client: Members
) -> None:
    dev, proposal_id = await pitchable(developers, proposal_world)
    assert (await pitch(dev, proposal_id, pitch_orgs.safaricom)).status_code == 201
    # The developer who pitched is not a member: 404 (the organisation's existence is not confirmed).
    refused = await dev.get(f"/api/orgs/{pitch_orgs.safaricom.id}/inbox")
    assert (refused.status_code, refused.json()["detail"]["code"]) == (404, "not_found")
    bystander = await member_client(pitch_orgs.bystander.member)  # type: ignore[arg-type]
    assert (await bystander.get(f"/api/orgs/{pitch_orgs.safaricom.id}/inbox")).status_code == 404
