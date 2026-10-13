"""REQ-TEN-02 (P28 track C, AT-C-3): a niche default assigns a new engagement in that niche (N30), never overwriting.

- A signatory expresses interest (``ORG_INTEREST``) in a proposal of a niche whose default reviewer is set: the
  engagement is assigned to them through P27's assignments (``assigned_by`` the signatory, the database's policy),
  they get N30 with the default's title, the organisation's list shows them as the assignee, and the assignment is
  audited as a system event (``reason: niche_default``).
- A default on the niche's parent applies to its children; an exact niche's default wins over its parent's.
- The signatory who is the default themselves is assigned without a notice (they opened it).
- Never overwritten: an engagement with a live assignment, or one someone unassigned, keeps it as it is.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.engagements import team
from bridge.engagements.team import N30, default_title
from bridge.ids import uuid7
from tests.integration.engagements import api_world
from tests.integration.engagements.api_world import clients, db_today, deals_on
from tests.integration.matching.scout_world import ScoutWorld, build, publish, rows

SETTINGS = deals_on()
TITLE = "Mobile money savings for SACCO members"  # scout_world.Teaser's


def slug(world: ScoutWorld, key: str) -> str:
    return f"p10-{key}-{world.tag}"  # scout_world.build's niche slugs


async def express(signatory: httpx.AsyncClient, world: ScoutWorld, proposal: UUID, today: date) -> UUID:
    """The signatory expresses interest from the Browse repo (stage 0); the engagement's id."""
    body = {
        "proposal_id": str(proposal),
        "origin": "org_browse",
        "match_id": None,
        "contact_user_id": str(world.org.owner),
        "channel": "video_call",
        "contact_by": str(today + timedelta(days=1)),
    }
    created = await signatory.post(f"/api/orgs/{world.org.id}/interest", json=body)
    assert created.status_code == 201, created.text
    return UUID(created.json()["id"])


async def set_defaults(owner: httpx.AsyncClient, world: ScoutWorld, **defaults: UUID) -> None:
    items = [{"niche_slug": slug(world, key), "user_id": str(user)} for key, user in defaults.items()]
    response = await owner.put(f"/api/orgs/{world.org.id}/niche-defaults", json={"items": items})
    assert response.status_code == 200, response.text


async def live_assignee(owner_engine: AsyncEngine, engagement: UUID) -> list[tuple[UUID, UUID]]:
    found = await rows(
        owner_engine,
        "SELECT assignee_user_id, assigned_by FROM engagement_assignments"
        " WHERE engagement_id = :e AND unassigned_at IS NULL",
        e=engagement,
    )
    return [(r.assignee_user_id, r.assigned_by) for r in found]


async def n30s(owner_engine: AsyncEngine, user: UUID) -> list[Any]:
    return await rows(
        owner_engine,
        "SELECT title, body, link, org_id FROM in_app_notifications WHERE user_id = :u AND kind = :k",
        u=user,
        k=N30,
    )


async def test_a_niche_default_takes_a_new_engagement_and_is_told(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    today = await db_today(owner_engine)
    exact = (await publish(owner_engine, world, "exact"))[0]
    child = (await publish(owner_engine, world, "child", niche=world.sibling))[0]
    async with clients(app_engine, SETTINGS, world.org.owner, world.org.signatory, world.org.reviewer) as (
        owner,
        signatory,
        reviewer,
    ):
        await set_defaults(owner, world, niche=world.org.reviewer, parent=world.org.owner)
        engagement = await express(signatory, world, exact, today)
        assert await live_assignee(owner_engine, engagement) == [(world.org.reviewer, world.org.signatory)]
        [notice] = await n30s(owner_engine, world.org.reviewer)
        assert (notice.title, notice.link, notice.org_id) == (
            default_title(TITLE),
            f"/org/engagements/{engagement}",
            world.org.id,
        )
        listed = (await reviewer.get(f"/api/orgs/{world.org.id}/engagements")).json()["items"]
        [item] = [i for i in listed if i["id"] == str(engagement)]
        assert item["team"]["assignee"]["user_id"] == str(world.org.reviewer)

        sibling = await express(signatory, world, child, today)  # Insurance: no default, its parent's applies
        assert await live_assignee(owner_engine, sibling) == [(world.org.owner, world.org.signatory)]
        assert len(await n30s(owner_engine, world.org.owner)) == 1
    events = await rows(
        owner_engine,
        "SELECT actor_user_id, actor_kind::text AS kind, subject_id, payload FROM audit_events"
        " WHERE org_id = :o AND action = 'engagement.assigned' ORDER BY occurred_at, seq",
        o=world.org.id,
    )
    assert [(e.actor_user_id, e.kind, e.subject_id, e.payload["reason"]) for e in events] == [
        (None, "system", engagement, "niche_default"),
        (None, "system", sibling, "niche_default"),
    ]
    assert events[0].payload["assignee_user_id"] == str(world.org.reviewer)


async def test_no_default_no_assignment_and_the_signatory_s_own_default_is_not_told(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    today = await db_today(owner_engine)
    elsewhere = (await publish(owner_engine, world, "elsewhere", niche=world.elsewhere))[0]
    mine = (await publish(owner_engine, world, "mine"))[0]
    async with clients(app_engine, SETTINGS, world.org.owner, world.org.signatory) as (owner, signatory):
        await set_defaults(owner, world, niche=world.org.signatory)
        unassigned = await express(signatory, world, elsewhere, today)
        assert await live_assignee(owner_engine, unassigned) == []
        own = await express(signatory, world, mine, today)
        assert await live_assignee(owner_engine, own) == [(world.org.signatory, world.org.signatory)]
    assert await n30s(owner_engine, world.org.signatory) == []


async def test_a_default_never_overwrites_an_assignment(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    today = await db_today(owner_engine)
    first = (await publish(owner_engine, world, "first"))[0]
    second = (await publish(owner_engine, world, "second"))[0]
    async with clients(app_engine, SETTINGS, world.org.owner, world.org.signatory) as (owner, signatory):
        manual = await express(signatory, world, first, today)  # no default yet
        cleared = await express(signatory, world, second, today)
        path = f"/api/orgs/{world.org.id}/engagements"
        assert (await owner.put(f"{path}/{manual}/assignee", json={"user_id": str(world.org.signatory)})).is_success
        assert (await owner.put(f"{path}/{cleared}/assignee", json={"user_id": str(world.org.owner)})).is_success
        assert (await owner.put(f"{path}/{cleared}/assignee", json={"user_id": None})).is_success
        await set_defaults(owner, world, niche=world.org.reviewer)
    factory = create_session_factory(app_engine)
    for engagement in (manual, cleared):
        async with factory() as db:
            await bind_tenant(db, user_id=world.org.reviewer, org_id=world.org.id)
            assert await team.assign_niche_default(db, world.org.id, engagement) is None
            await db.commit()
    assert await live_assignee(owner_engine, manual) == [(world.org.signatory, world.org.owner)]
    assert await live_assignee(owner_engine, cleared) == []
    assert await n30s(owner_engine, world.org.reviewer) == []


async def test_the_rule_on_a_submitted_engagement_and_its_refusals(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule itself, bound to a member: a SUBMITTED engagement takes the default too (a Pitch's hook binds the
    member ``app_niche_default_assignee`` names: test_niche_default_on_pitch.py); not in an opening state, or with no
    member bound, nothing; and the assignment guard is the backstop when the member checks are bypassed (nothing
    assigned, no error)."""
    world = await api_world.build(owner_engine)
    engagement = await api_world.open_engagement(app_engine, world)
    [version] = await rows(owner_engine, "SELECT niche_id FROM proposal_versions WHERE id = :v", v=world.version)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO org_niche_defaults (id, org_id, niche_id, user_id) VALUES (:id, :o, :n, :u)"),
            {"id": uuid7(), "o": world.org, "n": version.niche_id, "u": world.reviewer},
        )
    factory = create_session_factory(app_engine)

    async def apply(user: UUID | None) -> team.DefaultAssigned | None:
        async with factory() as db:
            await bind_tenant(db, user_id=user, org_id=world.org)
            done = await team.assign_niche_default(db, world.org, engagement)
            await db.commit()
            return done

    async def finance_default(db: Any, org_id: UUID, niche_id: UUID | None) -> UUID:
        return world.finance

    async def anyone_triages(db: Any, org_id: UUID, user_id: UUID) -> bool:
        return True

    with monkeypatch.context() as patched:
        patched.setattr(team, "_default_for", finance_default)
        patched.setattr(team, "_is_triage_member", anyone_triages)
        assert await apply(world.signatory) is None  # engagement_assignments_guard: finance never triages
    assert await live_assignee(owner_engine, engagement) == []
    assert await apply(None) is None  # no member bound: the job of nobody
    done = await apply(world.signatory)
    assert done is not None
    assert (done.assignee_id, done.tell, done.title) == (world.reviewer, True, api_world.PROPOSAL_TITLE)
    assert await live_assignee(owner_engine, engagement) == [(world.reviewer, world.signatory)]
    async with owner_engine.begin() as conn:  # unassigned again: a closed row is a choice, never overwritten
        await conn.execute(
            text("UPDATE engagement_assignments SET unassigned_at = now() WHERE engagement_id = :e"), {"e": engagement}
        )
    async with api_world.clients(app_engine, SETTINGS, world.reviewer) as (reviewer,):
        assert (await api_world.Tracker(engagement).post(reviewer, "start-review")).status_code == 200
    assert await apply(world.signatory) is None  # under review, and someone chose: nothing


async def test_a_failure_in_the_rule_never_undoes_the_interest(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's MINOR: the ORG_INTEREST rule runs in a savepoint; an error is logged and the interest stands."""
    world = await build(owner_engine)
    today = await db_today(owner_engine)
    proposal = (await publish(owner_engine, world, "broken"))[0]

    async def broken(db: Any, org_id: UUID, niche_id: UUID | None) -> UUID:
        raise RuntimeError("the defaults could not be read")

    monkeypatch.setattr(team, "_default_for", broken)
    async with clients(app_engine, SETTINGS, world.org.owner, world.org.signatory) as (owner, signatory):
        await set_defaults(owner, world, niche=world.org.reviewer)
        engagement = await express(signatory, world, proposal, today)
    assert await live_assignee(owner_engine, engagement) == []
    [row] = await rows(owner_engine, "SELECT state::text AS state FROM engagements WHERE id = :e", e=engagement)
    assert row.state == "ORG_INTEREST"
