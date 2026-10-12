"""REQ-ENG-15 (P27 track C; D-68; docs/spec/03 ``reviewer``: "may Recommend internally without changing state").

Acceptance 3: a reviewer at Telco A assigns an engagement to a colleague, who gets N30 and finds it assigned to them
(the organisation's list, its tracker and its Inbox carry ``team``); a reviewer's recommendation shows to another member
with its note and in the tally; the developer's list and tracker carry no ``team`` key and no recommendation text; a
``viewer`` or ``finance`` member cannot assign or recommend (403); a member of another organisation gets 404; a
developer who is also a member of the organisation never reads its triage of their engagement. Every change appends an
audit row with ids and the stance only; nothing of it enters the engagement's chain."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.engagements.team import N30, assigned_title
from bridge.ids import uuid7
from tests.integration.engagements.api_world import (
    PROPOSAL_TITLE,
    Seats,
    World,
    build,
    clients,
    deals_on,
    open_engagement,
    run,
    seats,
)

SETTINGS = deals_on()
NOTE = "Overlaps our 2025 rural pilot, ask Wanjiku first"


def team_path(world: World, engagement: UUID, suffix: str = "team") -> str:
    return f"/api/orgs/{world.org}/engagements/{engagement}/{suffix}"


def code(response: httpx.Response) -> tuple[int, str | None]:
    body = response.json()
    detail = body.get("detail") if isinstance(body, dict) else None
    return response.status_code, detail.get("code") if isinstance(detail, dict) else None


async def rows(engine: AsyncEngine, sql: str, **params: object) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def name_of(engine: AsyncEngine, user: UUID) -> str:
    [row] = await rows(engine, "SELECT display_name FROM users WHERE id = :u", u=user)
    return str(row.display_name)


async def org_item(client: httpx.AsyncClient, world: World, engagement: UUID) -> dict[str, Any]:
    listed = await client.get(f"/api/orgs/{world.org}/engagements")
    assert listed.status_code == 200, listed.text
    [item] = [i for i in listed.json()["items"] if i["id"] == str(engagement)]
    return dict(item)


async def assign(client: httpx.AsyncClient, world: World, engagement: UUID, user: UUID | None) -> httpx.Response:
    body = {"user_id": str(user) if user else None}
    return await client.put(team_path(world, engagement, "assignee"), json=body)


async def test_a_reviewer_assigns_a_colleague_who_is_told_and_finds_it_assigned_to_them(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    async with seats(app_engine, SETTINGS, world) as s:
        before = await org_item(s.signatory, world, engagement)
        assert before["team"] == {
            "assignee": None,
            "recommendations": {"pursue": 0, "pass": 0, "discuss": 0},
            "mine": None,
        }

        assigned = await assign(s.reviewer, world, engagement, world.signatory)
        assert assigned.status_code == 200, assigned.text
        signatory_name = await name_of(owner_engine, world.signatory)
        assert assigned.json()["assignee"] == {"user_id": str(world.signatory), "display_name": signatory_name}
        members = {m["user_id"]: m["role"] for m in assigned.json()["members"]}
        assert members == {
            str(world.owner): "owner",
            str(world.signatory): "signatory",
            str(world.reviewer): "reviewer",
        }  # finance and viewer are not assignable

        # N30, in-app, to the assignee: the idea's title and who assigned
        [notice] = await rows(
            owner_engine,
            "SELECT kind, title, body, link, org_id FROM in_app_notifications WHERE user_id = :u",
            u=world.signatory,
        )
        reviewer_name = await name_of(owner_engine, world.reviewer)
        assert notice.kind == N30
        assert notice.title == assigned_title(reviewer_name, PROPOSAL_TITLE)
        assert PROPOSAL_TITLE in notice.title
        assert reviewer_name in notice.title
        assert notice.link == f"/org/engagements/{engagement}"
        assert notice.org_id == world.org

        # "Assigned to me": the list, the tracker and the Inbox say who
        mine = await org_item(s.signatory, world, engagement)
        assert mine["team"]["assignee"]["user_id"] == str(world.signatory)
        detail = (await s.signatory.get(f"/api/engagements/{engagement}")).json()
        assert detail["my_party"] == "org"
        assert detail["team"] == mine["team"]
        inbox = (await s.signatory.get(f"/api/orgs/{world.org}/inbox")).json()
        [pitched] = [i for i in inbox["items"] if i["engagement"] and i["engagement"]["id"] == str(engagement)]
        assert pitched["engagement"]["team"] == mine["team"]

        assert code(await assign(s.owner, world, engagement, world.signatory)) == (409, "unchanged")
        for wrong in (world.finance, world.viewer, world.outsider, world.developer, uuid7()):
            assert code(await assign(s.owner, world, engagement, wrong)) == (422, "invalid_assignee")

        # reassigning closes the live row; self-assignment tells nobody; unassigning leaves none
        assert (await assign(s.owner, world, engagement, world.owner)).status_code == 200
        assert (await assign(s.owner, world, engagement, None)).json()["assignee"] is None
        assert code(await assign(s.owner, world, engagement, None)) == (409, "unchanged")
    history = await rows(
        owner_engine,
        "SELECT assignee_user_id, assigned_by, unassigned_at FROM engagement_assignments WHERE engagement_id = :e"
        " ORDER BY assigned_at",
        e=engagement,
    )
    assert [(r.assignee_user_id, r.assigned_by) for r in history] == [
        (world.signatory, world.reviewer),
        (world.owner, world.owner),
    ]
    assert all(r.unassigned_at is not None for r in history)
    told = await rows(owner_engine, "SELECT 1 FROM in_app_notifications WHERE user_id = :u", u=world.owner)
    assert told == []  # the owner assigned themselves
    audits = await rows(
        owner_engine,
        "SELECT actor_user_id, org_id, payload FROM audit_events WHERE action = 'engagement.assigned'"
        " AND subject_id = :e ORDER BY seq",
        e=engagement,
    )
    assert [a.payload["assignee_user_id"] for a in audits] == [str(world.signatory), str(world.owner), None]
    assert {a.org_id for a in audits} == {world.org}
    assert all(set(a.payload) == {"engagement_id", "assignment_id", "assignee_user_id"} for a in audits)


async def test_recommendations_show_to_members_with_their_notes_and_in_the_tally(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    path = team_path(world, engagement, "recommendation")
    async with seats(app_engine, SETTINGS, world) as s:
        state = (await s.owner.get(f"/api/engagements/{engagement}")).json()
        recommended = await s.reviewer.put(path, json={"stance": "pass", "note": f"  {NOTE} "})
        assert recommended.status_code == 200, recommended.text
        assert (await s.signatory.put(path, json={"stance": "pursue", "note": "   "})).status_code == 200
        assert (await s.owner.put(path, json={"stance": "pursue"})).status_code == 200

        sheet = (await s.owner.get(team_path(world, engagement))).json()
        by = {r["user_id"]: (r["stance"], r["note"]) for r in sheet["recommendations"]}
        assert by == {
            str(world.reviewer): ("pass", NOTE),  # trimmed
            str(world.signatory): ("pursue", None),  # blank is no note
            str(world.owner): ("pursue", None),
        }
        seen = (await s.signatory.get(f"/api/engagements/{engagement}")).json()
        assert seen["team"]["recommendations"] == {"pursue": 2, "pass": 1, "discuss": 0}
        assert seen["team"]["mine"] == {"stance": "pursue", "note": None}
        reviewer_view = await org_item(s.reviewer, world, engagement)
        assert reviewer_view["team"]["mine"] == {"stance": "pass", "note": NOTE}
        assert (seen["state"], seen["lock_version"]) == (state["state"], state["lock_version"])  # no state change

        # one row per member, upserted; the same again is no change; withdrawing removes it
        changed = await s.reviewer.put(path, json={"stance": "discuss", "note": NOTE})
        assert [r["stance"] for r in changed.json()["recommendations"]].count("discuss") == 1
        assert (await s.reviewer.put(path, json={"stance": "discuss", "note": NOTE})).status_code == 200
        withdrawn = await s.reviewer.delete(path)
        assert withdrawn.status_code == 200, withdrawn.text
        assert str(world.reviewer) not in {r["user_id"] for r in withdrawn.json()["recommendations"]}
        assert (await s.reviewer.delete(path)).status_code == 200  # nothing left to withdraw: no change
        tally = (await org_item(s.owner, world, engagement))["team"]["recommendations"]
        assert tally == {"pursue": 2, "pass": 0, "discuss": 0}

        for bad in ("two\nlines", "x" * 201, "zero\u200bwidth", "bidi\u202eright", "no\u00a0break"):
            assert code(await s.reviewer.put(path, json={"stance": "pass", "note": bad})) == (422, "invalid_note")
        assert (await s.reviewer.put(path, json={"stance": "maybe"})).status_code == 422

    audits = await rows(
        owner_engine,
        "SELECT a.action, a.payload, d.details FROM audit_events a LEFT JOIN event_details d ON d.event_id = a.id"
        " WHERE a.subject_id = :e AND a.action LIKE 'engagement.recommend%' ORDER BY a.seq",
        e=engagement,
    )
    assert [(a.action, a.payload.get("stance")) for a in audits] == [
        ("engagement.recommended", "pass"),
        ("engagement.recommended", "pursue"),
        ("engagement.recommended", "pursue"),
        ("engagement.recommended", "discuss"),
        ("engagement.recommendation_withdrawn", None),
    ]
    assert all(a.details is None for a in audits)
    assert "Wanjiku" not in json.dumps([a.payload for a in audits])
    events = await rows(
        owner_engine, "SELECT payload::text AS p FROM engagement_events WHERE engagement_id = :e", e=engagement
    )
    assert all("Wanjiku" not in e.p and "recommend" not in e.p for e in events)


async def test_the_developer_never_sees_the_organisations_triage(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    async with seats(app_engine, SETTINGS, world) as s:
        assert (await assign(s.reviewer, world, engagement, world.signatory)).status_code == 200
        note = {"stance": "pass", "note": NOTE}
        assert (await s.reviewer.put(team_path(world, engagement, "recommendation"), json=note)).status_code == 200
        listed = await s.dev.get("/api/me/engagements")
        detail = await s.dev.get(f"/api/engagements/{engagement}")
        history = await s.dev.get(f"/api/engagements/{engagement}/history")
        for response in (listed, detail, history):
            assert response.status_code == 200, response.text
            for leaked in ("Wanjiku", "Overlaps", '"team"', "recommendation"):
                assert leaked not in response.text
        [item] = [i for i in listed.json()["items"] if i["id"] == str(engagement)]
        assert "team" not in item
        assert "team" not in detail.json()
        assert detail.json()["my_party"] == "developer"
        assert (await s.dev.get(team_path(world, engagement))).status_code == 404  # not a member
        assert code(await assign(s.dev, world, engagement, world.signatory))[0] == 404


async def test_a_viewer_or_finance_member_cannot_assign_or_recommend(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    async with clients(app_engine, SETTINGS, world.viewer, world.finance) as people:
        for person in people:
            assert code(await assign(person, world, engagement, world.signatory)) == (403, "role_not_allowed")
            recommend = await person.put(team_path(world, engagement, "recommendation"), json={"stance": "pursue"})
            assert code(recommend) == (403, "role_not_allowed")
            assert (await person.get(team_path(world, engagement))).status_code == 200  # members read the sheet
            assert (await person.delete(team_path(world, engagement, "recommendation"))).status_code == 200
    assert await rows(owner_engine, "SELECT 1 FROM engagement_assignments WHERE engagement_id = :e", e=engagement) == []
    assert (
        await rows(owner_engine, "SELECT 1 FROM engagement_recommendations WHERE engagement_id = :e", e=engagement)
        == []
    )


async def test_a_member_of_another_organisation_gets_404(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    other = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    async with clients(app_engine, SETTINGS, other.owner) as (stranger,):
        for org in (world.org, other.org):  # not a member of Telco A; Telco A's engagement is not theirs
            base = f"/api/orgs/{org}/engagements/{engagement}"
            assert code(await stranger.get(f"{base}/team"))[0] == 404
            assert code(await stranger.put(f"{base}/assignee", json={"user_id": str(other.owner)}))[0] == 404
            assert code(await stranger.put(f"{base}/recommendation", json={"stance": "pursue"}))[0] == 404
            assert code(await stranger.delete(f"{base}/recommendation"))[0] == 404


async def test_a_developer_who_is_also_a_member_never_reads_the_triage_of_their_engagement(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The security review of revision 0013: the developer of an engagement who is (or becomes) a viewer of its
    organisation reads none of the organisation's triage of it, on either side's routes."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    async with seats(app_engine, SETTINGS, world) as s:
        assert (await assign(s.reviewer, world, engagement, world.signatory)).status_code == 200
        note = {"stance": "pass", "note": NOTE}
        assert (await s.reviewer.put(team_path(world, engagement, "recommendation"), json=note)).status_code == 200
    async with owner_engine.begin() as conn:
        await run(
            conn,
            "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :o, :u, '{viewer}')",
            id=uuid7(),
            o=world.org,
            u=world.developer,
        )
    async with clients(app_engine, SETTINGS, world.developer) as (dev,):
        assert code(await dev.get(team_path(world, engagement))) == (403, "both_parties")
        assert code(await assign(dev, world, engagement, world.owner)) == (403, "role_not_allowed")
        listed = await dev.get(f"/api/orgs/{world.org}/engagements")
        assert listed.status_code == 200, listed.text
        [item] = [i for i in listed.json()["items"] if i["id"] == str(engagement)]
        assert item["team"] is None
        assert "Wanjiku" not in listed.text
        inbox = await dev.get(f"/api/orgs/{world.org}/inbox")
        assert "Wanjiku" not in inbox.text
        assert all(i["engagement"] is None or i["engagement"]["team"] is None for i in inbox.json()["items"])
        mine = await dev.get("/api/me/engagements")
        assert '"team"' not in mine.text
        assert "Wanjiku" not in mine.text
        assert code(await dev.get(f"/api/engagements/{engagement}")) == (403, "both_parties")


async def test_the_developer_is_never_assigned_their_own_engagement_even_as_a_reviewer(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """D-68 (the review of P27-BE-2): a developer who is also a reviewer of the organisation is not assignable to their
    own proposal's engagement (N30 would tell them the organisation's triage of it) and is never on its roster."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    async with owner_engine.begin() as conn:
        await run(
            conn,
            "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :o, :u, '{reviewer}')",
            id=uuid7(),
            o=world.org,
            u=world.developer,
        )
    recommendation = team_path(world, engagement, "recommendation")
    async with seats(app_engine, SETTINGS, world) as s:
        refused = await assign(s.signatory, world, engagement, world.developer)
        assert code(refused) == (422, "invalid_assignee")
        assert str(world.developer) not in refused.text  # no echo
        sheets = [
            await s.owner.get(team_path(world, engagement)),
            await s.reviewer.put(recommendation, json={"stance": "pursue"}),
            await assign(s.owner, world, engagement, world.signatory),
            await s.reviewer.delete(recommendation),
        ]
        for sheet in sheets:
            assert sheet.status_code == 200, sheet.text
            assert {m["user_id"] for m in sheet.json()["members"]} == {
                str(world.owner),
                str(world.signatory),
                str(world.reviewer),
            }
        assert code(await assign(s.owner, world, engagement, world.developer)) == (422, "invalid_assignee")
    assignees = await rows(
        owner_engine, "SELECT assignee_user_id FROM engagement_assignments WHERE engagement_id = :e", e=engagement
    )
    assert [r.assignee_user_id for r in assignees] == [world.signatory]
    told = await rows(
        owner_engine, "SELECT 1 FROM in_app_notifications WHERE user_id = :u AND kind = :k", u=world.developer, k=N30
    )
    assert told == []


async def test_each_member_reads_their_own_recommendation_as_mine(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The org list's ``team`` is the same for every member but ``mine``: each reads their own recommendation."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    async with seats(app_engine, SETTINGS, world) as s:
        await s.owner.put(team_path(world, engagement, "recommendation"), json={"stance": "discuss", "note": "Why"})
        views = [await org_item(c, world, engagement) for c in _members(s)]
    assert [v["team"]["mine"] for v in views] == [{"stance": "discuss", "note": "Why"}, None, None, None]
    assert len({json.dumps(v["team"]["recommendations"]) for v in views}) == 1


def _members(s: Seats) -> list[httpx.AsyncClient]:
    return [s.owner, s.signatory, s.reviewer, s.finance]
