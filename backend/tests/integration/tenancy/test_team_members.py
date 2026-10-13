"""REQ-TEN-02 (P28 track C, AT-C-2; the Team page's read and settings).

- ``GET …/team``: every active member by name with roles and joined date; addresses and open invitations for owners
  and admins only; the niche defaults and the escalation contact.
- Removing a member (owner or admin, a fresh second factor): the last owner is 409 ``last_owner``; an admin removing
  an owner or a signatory is 403 ``protected_member`` (an owner may); a member who is not an admin is 403; another
  organisation's member is 404. A removed member's open assignments are cleared in the same transaction (each audited
  as an unassignment), and so are their niche defaults and escalation-contact seat (the database's trigger).
- Niche defaults (owner or admin): the whole set; an unknown niche, a repeated niche or a member who is not a reviewer,
  signatory or admin is 422; a non-admin is 403. Escalation contact: an active member or nobody; anyone else 422.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration.engagements.api_world import World, build, clients, open_engagement
from tests.integration.tenancy.team_helpers import SETTINGS, audit_actions, code, person, rows


async def niche_of(owner_engine: AsyncEngine, world: World) -> tuple[UUID, str]:
    [row] = await rows(
        owner_engine,
        "SELECT n.id, n.slug FROM niches n JOIN proposal_versions v ON v.niche_id = n.id WHERE v.id = :v",
        v=world.version,
    )
    return row.id, str(row.slug)


async def join(owner_engine: AsyncEngine, org: UUID, user: UUID, roles: str) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, CAST(:r AS org_role[]))"),
            {"id": uuid7(), "org": org, "u": user, "r": roles},
        )


async def test_the_team_page_shows_members_and_addresses_to_admins_only(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner, world.viewer) as (owner, viewer):
        mine = (await owner.get(f"/api/orgs/{world.org}/team")).json()
        theirs = (await viewer.get(f"/api/orgs/{world.org}/team")).json()
    people = {world.owner, world.signatory, world.reviewer, world.finance, world.viewer}
    assert {UUID(m["user_id"]) for m in mine["members"]} == people
    assert all(m["email"] and "@" in m["email"] for m in mine["members"])
    assert all(m["joined_at"] for m in mine["members"])
    assert [m["name"] for m in mine["members"]] == sorted(m["name"] for m in mine["members"])
    [owner_row] = [m for m in mine["members"] if m["user_id"] == str(world.owner)]
    assert owner_row["roles"] == ["admin", "owner"]
    assert "verification" not in owner_row  # no person-level organisation verification is modelled
    assert (mine["invitations"], mine["niche_defaults"], mine["escalation_contact"]) == ([], [], None)
    assert theirs["invitations"] is None
    assert {m["email"] for m in theirs["members"]} == {None}
    assert {m["user_id"] for m in theirs["members"]} == {m["user_id"] for m in mine["members"]}


async def test_removing_a_member_clears_their_assignments_defaults_and_escalation_seat(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    _, slug = await niche_of(owner_engine, world)
    async with clients(app_engine, SETTINGS, world.owner, world.reviewer) as (owner, reviewer):
        assigned = await owner.put(
            f"/api/orgs/{world.org}/engagements/{engagement}/assignee", json={"user_id": str(world.reviewer)}
        )
        assert assigned.status_code == 200, assigned.text
        defaults = await owner.put(
            f"/api/orgs/{world.org}/niche-defaults",
            json={"items": [{"niche_slug": slug, "user_id": str(world.reviewer)}]},
        )
        assert defaults.status_code == 200, defaults.text
        contact = await owner.put(f"/api/orgs/{world.org}/escalation-contact", json={"user_id": str(world.reviewer)})
        assert contact.status_code == 200, contact.text
        team = (await owner.get(f"/api/orgs/{world.org}/team")).json()
        assert [d["user_id"] for d in team["niche_defaults"]] == [str(world.reviewer)]
        assert team["escalation_contact"]["user_id"] == str(world.reviewer)

        removed = await owner.delete(f"/api/orgs/{world.org}/members/{world.reviewer}")
        assert removed.status_code == 204, removed.text
        team = (await owner.get(f"/api/orgs/{world.org}/team")).json()
        assert str(world.reviewer) not in {m["user_id"] for m in team["members"]}
        assert (team["niche_defaults"], team["escalation_contact"]) == ([], None)
        listed = (await owner.get(f"/api/orgs/{world.org}/engagements")).json()["items"]
        assert [item["team"]["assignee"] for item in listed if item["id"] == str(engagement)] == [None]
        assert (await reviewer.get(f"/api/orgs/{world.org}/team")).status_code == 404  # no longer a member
        assert code(await owner.delete(f"/api/orgs/{world.org}/members/{world.reviewer}")) == (404, "not_found")
    [row] = await rows(
        owner_engine,
        "SELECT status::text AS status FROM memberships WHERE org_id = :o AND user_id = :u",
        o=world.org,
        u=world.reviewer,
    )
    assert row.status == "removed"
    live = await rows(
        owner_engine,
        "SELECT 1 FROM engagement_assignments WHERE engagement_id = :e AND unassigned_at IS NULL",
        e=engagement,
    )
    assert live == []
    events = await audit_actions(owner_engine, world.org, "")
    cleared = [e for e in events if e.action == "engagement.assigned" and e.payload.get("reason") == "member_removed"]
    assert [(e.subject_id, e.actor_user_id, e.payload["assignee_user_id"]) for e in cleared] == [
        (engagement, world.owner, None)
    ]
    [gone] = [e for e in events if e.action == "org.member_removed"]
    assert gone.payload == {"user_id": str(world.reviewer), "assignments_cleared": 1}


async def test_the_last_owner_stays_and_only_an_owner_removes_owners_and_signatories(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    other = await build(owner_engine)
    admin, _ = await person(owner_engine)
    await join(owner_engine, world.org, admin, "{admin}")
    async with clients(app_engine, SETTINGS, world.owner, admin, world.reviewer, other.owner) as (
        owner,
        an_admin,
        reviewer,
        outsider,
    ):
        assert code(await owner.delete(f"/api/orgs/{world.org}/members/{world.owner}")) == (409, "last_owner")
        assert code(await an_admin.delete(f"/api/orgs/{world.org}/members/{world.owner}")) == (403, "protected_member")
        assert code(await an_admin.delete(f"/api/orgs/{world.org}/members/{world.signatory}")) == (
            403,
            "protected_member",
        )
        assert code(await reviewer.delete(f"/api/orgs/{world.org}/members/{world.viewer}")) == (403, "forbidden")
        assert code(await outsider.delete(f"/api/orgs/{world.org}/members/{world.viewer}")) == (404, "not_found")
        assert code(await owner.delete(f"/api/orgs/{world.org}/members/{other.viewer}")) == (404, "not_found")
        assert (await an_admin.delete(f"/api/orgs/{world.org}/members/{world.viewer}")).status_code == 204
        assert (await owner.delete(f"/api/orgs/{world.org}/members/{world.signatory}")).status_code == 204
    statuses = await rows(
        owner_engine,
        "SELECT user_id, status::text AS status FROM memberships WHERE org_id = :o",
        o=world.org,
    )
    assert {r.user_id: r.status for r in statuses} == {
        world.owner: "active",
        world.signatory: "removed",
        world.reviewer: "active",
        world.finance: "active",
        world.viewer: "removed",
        admin: "active",
    }


async def test_niche_defaults_are_reviewers_signatories_or_admins_by_niche(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    _, slug = await niche_of(owner_engine, world)
    second = f"p28-{uuid4().hex[:8]}"
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Agriculture P28')"),
            {"id": uuid7(), "s": second},
        )
    path = f"/api/orgs/{world.org}/niche-defaults"

    def item(niche: str, user: UUID) -> dict[str, str]:
        return {"niche_slug": niche, "user_id": str(user)}

    async with clients(app_engine, SETTINGS, world.owner, world.reviewer) as (owner, reviewer):
        both = await owner.put(path, json={"items": [item(slug, world.reviewer), item(second, world.signatory)]})
        assert both.status_code == 200, both.text
        assert {(d["niche_slug"], d["user_id"]) for d in both.json()} == {
            (slug, str(world.reviewer)),
            (second, str(world.signatory)),
        }
        assert {d["niche_name"] for d in both.json()} == {"P5", "Agriculture P28"}
        moved = await owner.put(path, json={"items": [item(slug, world.owner)]})  # replace the set: second goes
        assert [(d["niche_slug"], d["user_id"]) for d in moved.json()] == [(slug, str(world.owner))]
        for wrong in (world.finance, world.viewer, world.developer, uuid7()):
            assert code(await owner.put(path, json={"items": [item(slug, wrong)]})) == (422, "invalid_default_reviewer")
        assert code(await owner.put(path, json={"items": [item("no-such-niche", world.reviewer)]})) == (
            422,
            "unknown_niche",
        )
        twice = {"items": [item(slug, world.reviewer), item(slug, world.signatory)]}
        assert code(await owner.put(path, json=twice)) == (422, "duplicate_niche")
        assert code(await reviewer.put(path, json={"items": []})) == (403, "forbidden")
        assert (await owner.put(path, json={"items": []})).json() == []
    events = [e.action for e in await audit_actions(owner_engine, world.org, "org.niche_defaults_set")]
    assert len(events) == 3


async def test_the_escalation_contact_is_an_active_member_or_nobody(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    other = await build(owner_engine)
    path = f"/api/orgs/{world.org}/escalation-contact"
    async with clients(app_engine, SETTINGS, world.owner, world.signatory) as (owner, signatory):
        named = await owner.put(path, json={"user_id": str(world.finance)})
        assert named.status_code == 200, named.text
        assert named.json()["user_id"] == str(world.finance)
        assert named.json()["name"]
        for wrong in (other.owner, world.developer, uuid7()):
            assert code(await owner.put(path, json={"user_id": str(wrong)})) == (422, "invalid_member")
        assert code(await signatory.put(path, json={"user_id": None})) == (403, "forbidden")
        team = (await signatory.get(f"/api/orgs/{world.org}/team")).json()
        assert team["escalation_contact"] == named.json()
        cleared = await owner.put(path, json={"user_id": None})
        assert (cleared.status_code, cleared.json()) == (200, None)
    [row] = await rows(owner_engine, "SELECT escalation_contact_user_id FROM organizations WHERE id = :o", o=world.org)
    assert row.escalation_contact_user_id is None
    payloads = [e.payload for e in await audit_actions(owner_engine, world.org, "org.escalation_contact_set")]
    assert payloads == [{"user_id": str(world.finance)}, {"user_id": None}]
