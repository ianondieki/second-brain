"""REQ-TEN-02 (P28 track C, AT-C-3 for ``SUBMITTED``): a Pitch's new engagement goes to the niche's default reviewer.

A Pitch opens ``SUBMITTED`` engagements in the developer's session, which reads none of the organisations' rows. After
it commits, ``app_niche_default_assignee`` (revision 0015) names each one's default; the app binds that member and the
organisation and assigns through P27's path (``assigned_by`` the member), and N30 tells them. Here:

- an organisation with a default for the proposal's niche gets the engagement assigned to it, once (N30 once);
  another organisation without one gets nothing;
- a later pass never overwrites a manual assignment;
- the developer reads no team data on their list or tracker, and gets no N30;
- a failure while assigning never undoes the Pitch.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from bridge.db import create_session_factory
from bridge.engagements import team
from bridge.engagements.team import N30, default_title
from bridge.ids import uuid7
from tests.integration.proposals.helpers import Developers, ProposalWorld, rows
from tests.integration.proposals.pitch_helpers import Members, PitchOrgs, add_member, pitch, pitchable


async def set_default(owner_engine: AsyncEngine, org: UUID, niche: UUID, user: UUID) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO org_niche_defaults (id, org_id, niche_id, user_id) VALUES (:id, :o, :n, :u)"),
            {"id": uuid7(), "o": org, "n": niche, "u": user},
        )


async def assignments(owner_engine: AsyncEngine, engagement: UUID) -> list[Any]:
    return await rows(
        owner_engine,
        "SELECT assignee_user_id, assigned_by, unassigned_at FROM engagement_assignments WHERE engagement_id = :e"
        " ORDER BY assigned_at",
        e=engagement,
    )


async def n30s(owner_engine: AsyncEngine, user: UUID) -> list[Any]:
    return await rows(
        owner_engine,
        "SELECT title, link FROM in_app_notifications WHERE user_id = :u AND kind = :k",
        u=user,
        k=N30,
    )


def opened(response: Any) -> dict[str, UUID]:
    return {tag["org"]["id"]: UUID(tag["engagement_id"]) for tag in response.json()["tags"]}


async def test_a_pitch_s_engagement_goes_to_the_niche_default_once(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    member_client: Members,
) -> None:
    reviewer = pitch_orgs.safaricom.member
    assert reviewer is not None
    await set_default(owner_engine, pitch_orgs.safaricom.id, proposal_world.niche_id, reviewer)
    dev, proposal_id = await pitchable(developers, proposal_world)
    response = await pitch(dev, proposal_id, pitch_orgs.safaricom, pitch_orgs.airtel)
    assert response.status_code == 201, response.text
    ids = opened(response)
    mine, theirs = ids[str(pitch_orgs.safaricom.id)], ids[str(pitch_orgs.airtel.id)]

    assert [(a.assignee_user_id, a.assigned_by, a.unassigned_at) for a in await assignments(owner_engine, mine)] == [
        (reviewer, reviewer, None)
    ]
    assert await assignments(owner_engine, theirs) == []  # no default there
    [notice] = await n30s(owner_engine, reviewer)
    [title] = await rows(
        owner_engine,
        "SELECT title FROM proposal_versions v JOIN engagements e ON e.version_id = v.id WHERE e.id = :e",
        e=mine,
    )
    assert (notice.title, notice.link) == (default_title(str(title.title)), f"/org/engagements/{mine}")
    events = await rows(
        owner_engine,
        "SELECT actor_kind::text AS kind, payload FROM audit_events"
        " WHERE org_id = :o AND action = 'engagement.assigned'",
        o=pitch_orgs.safaricom.id,
    )
    assert [(e.kind, e.payload["reason"], e.payload["engagement_id"]) for e in events] == [
        ("system", "niche_default", str(mine))
    ]

    # The developer reads no team data (D-68), and is told nothing of it.
    developer: UUID = dev.user_id  # type: ignore[attr-defined]
    listed = (await dev.get("/api/me/engagements")).json()["items"]
    assert listed
    assert all("team" not in item for item in listed)
    tracker = (await dev.get(f"/api/engagements/{mine}")).json()
    assert tracker["my_party"] == "developer"
    assert "team" not in tracker
    assert str(reviewer) not in (await dev.get(f"/api/engagements/{mine}")).text
    assert await n30s(owner_engine, developer) == []

    # Never overwritten: someone reassigns it, and a later pass changes nothing.
    async with owner_engine.begin() as conn:
        boss = await add_member(conn, pitch_orgs.safaricom.id, "{owner,admin}")
    manager = await member_client(boss)
    moved = await manager.put(
        f"/api/orgs/{pitch_orgs.safaricom.id}/engagements/{mine}/assignee", json={"user_id": str(boss)}
    )
    assert moved.status_code == 200, moved.text
    again = await team.apply_niche_defaults(
        create_session_factory(app_engine), developer, [(mine, pitch_orgs.safaricom.id), (theirs, pitch_orgs.airtel.id)]
    )
    assert again == []
    live = [a.assignee_user_id for a in await assignments(owner_engine, mine) if a.unassigned_at is None]
    assert live == [boss]
    assert len(await n30s(owner_engine, reviewer)) == 1


async def test_a_failure_while_assigning_never_undoes_the_pitch(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewer = pitch_orgs.safaricom.member
    assert reviewer is not None
    await set_default(owner_engine, pitch_orgs.safaricom.id, proposal_world.niche_id, reviewer)

    async def broken(db: AsyncSession, org_id: UUID, engagement_id: UUID, *, opener: UUID | None = None) -> None:
        raise RuntimeError("the assignment failed")

    monkeypatch.setattr(team, "assign_niche_default", broken)
    dev, proposal_id = await pitchable(developers, proposal_world)
    response = await pitch(dev, proposal_id, pitch_orgs.safaricom)
    assert response.status_code == 201, response.text
    engagement = opened(response)[str(pitch_orgs.safaricom.id)]
    [row] = await rows(owner_engine, "SELECT state::text AS state FROM engagements WHERE id = :e", e=engagement)
    assert row.state == "SUBMITTED"
    assert await assignments(owner_engine, engagement) == []
    assert await n30s(owner_engine, reviewer) == []
