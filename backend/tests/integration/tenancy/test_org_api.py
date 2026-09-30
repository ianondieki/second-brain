"""REQ-TEN-01 through the organisation API (``bridge/tenancy/router.py``; docs/spec/08 error semantics).

- ``GET /api/orgs``: the caller's active memberships only, by name, with their roles.
- ``PATCH /api/orgs/{org_id}``: an owner or admin changes the name and website (audited with the field names); a
  verified (E1/E2) organisation's name is locked (409), its website is not.
- ``GET /api/orgs/{org_id}/members``: active members only, by name, with their roles.
- ``PUT /api/orgs/{org_id}/members/{user_id}/roles``: someone who is not an active member of *this* organisation is
  404 (another organisation's member included) and nothing changes; an owner may be demoted while another owner remains.
- A membership removed while a request is in flight: the organisation is read under RLS as the caller, so the
  request answers 404 and changes nothing.
"""

from __future__ import annotations

from typing import Any, get_args
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.auth.deps import CurrentSession, Db
from bridge.ids import uuid7
from bridge.tenancy.deps import OrgAdmin, OrgContext, OrgMember
from tests.integration.proposals.helpers import rows
from tests.integration.proposals.pitch_helpers import Members, Org, add_member, add_org

NOT_FOUND = {"code": "not_found", "message": "Not found."}


async def org_with(owner_engine: AsyncEngine, verification: str, **members: str) -> tuple[Org, dict[str, UUID]]:
    """An organisation (a random tag in its name) and one member per keyword: display name -> roles."""
    org = await add_org(
        owner_engine, f"Maji Co {uuid4().hex[:8]}", verification=verification, niche_id=None, roles=None
    )
    ids: dict[str, UUID] = {}
    async with owner_engine.begin() as conn:
        for name, roles in members.items():
            ids[name] = await add_member(conn, org.id, roles)
            await conn.execute(text("UPDATE users SET display_name = :n WHERE id = :u"), {"n": name, "u": ids[name]})
    return org, ids


async def join(owner_engine: AsyncEngine, org_id: UUID, user_id: UUID, roles: str, status: str = "active") -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO memberships (id, org_id, user_id, roles, status) VALUES (:id, :org, :user,"
                " CAST(:roles AS org_role[]), CAST(:status AS membership_status))"
            ),
            {"id": uuid7(), "org": org_id, "user": user_id, "roles": roles, "status": status},
        )


async def remove(owner_engine: AsyncEngine, org_id: UUID, user_id: UUID) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE memberships SET status = 'removed' WHERE org_id = :org AND user_id = :user"),
            {"org": org_id, "user": user_id},
        )


async def org_row(owner_engine: AsyncEngine, org_id: UUID) -> Any:
    [row] = await rows(owner_engine, "SELECT legal_name, website FROM organizations WHERE id = :id", id=org_id)
    return row


async def audit(owner_engine: AsyncEngine, org_id: UUID, action: str) -> list[Any]:
    sql = (
        "SELECT actor_user_id, subject_type, subject_id, payload FROM audit_events"
        " WHERE org_id = :org AND action = :action ORDER BY occurred_at, seq"
    )
    return await rows(owner_engine, sql, org=org_id, action=action)


async def roles_of(owner_engine: AsyncEngine, org_id: UUID, user_id: UUID) -> tuple[list[str], str]:
    sql = "SELECT roles::text[] AS roles, status FROM memberships WHERE org_id = :org AND user_id = :user"
    [row] = await rows(owner_engine, sql, org=org_id, user=user_id)
    return list(row.roles), str(row.status)


# ---------------------------------------------------------------------------------------------- GET /api/orgs


async def test_my_organisations_are_my_active_memberships_by_name_with_roles(
    owner_engine: AsyncEngine, member_client: Members
) -> None:
    zeta, people = await org_with(owner_engine, "e2", Wanjiru="{owner,admin}")
    me = people["Wanjiru"]
    alpha, _ = await org_with(owner_engine, "e1", Other="{owner}")
    left, _ = await org_with(owner_engine, "pending", Other="{owner}")
    stranger, _ = await org_with(owner_engine, "e2", Other="{owner}")
    async with owner_engine.begin() as conn:  # "Alpha" sorts before "Maji Co" (zeta), whatever the random tags
        await conn.execute(
            text("UPDATE organizations SET legal_name = 'Alpha ' || legal_name WHERE id = :id"), {"id": alpha.id}
        )
    await join(owner_engine, alpha.id, me, "{viewer}")
    await join(owner_engine, left.id, me, "{admin}", status="removed")

    client = await member_client(me)
    response = await client.get("/api/orgs")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [(item["org"]["id"], sorted(item["roles"])) for item in body] == [
        (str(alpha.id), ["viewer"]),
        (str(zeta.id), ["admin", "owner"]),
    ]
    assert body[1]["org"] == {
        "id": str(zeta.id),
        "legal_name": zeta.name,
        "slug": zeta.slug,
        "kind": "company",
        "country": "KE",
        "verification": "e2",
        "website": None,
    }
    assert str(left.id) not in response.text  # a removed membership is not a membership
    assert str(stranger.id) not in response.text


# ---------------------------------------------------------------------------------------------- PATCH /api/orgs/{id}


async def test_an_admin_changes_the_name_and_website_and_the_change_is_audited(
    owner_engine: AsyncEngine, member_client: Members
) -> None:
    org, people = await org_with(owner_engine, "pending", Achieng="{admin}")
    admin = await member_client(people["Achieng"])
    name = f"Maji Water Services {uuid4().hex[:6]}"
    changed = await admin.patch(
        f"/api/orgs/{org.id}", json={"legal_name": name, "website": "https://maji.example/about"}
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["legal_name"], changed.json()["website"]) == (name, "https://maji.example/about")
    assert tuple(await org_row(owner_engine, org.id)) == (name, "https://maji.example/about")

    cleared = await admin.patch(f"/api/orgs/{org.id}", json={"website": None})  # the name is left as it is
    assert cleared.status_code == 200, cleared.text
    assert (cleared.json()["legal_name"], cleared.json()["website"]) == (name, None)
    assert tuple(await org_row(owner_engine, org.id)) == (name, None)
    assert (await admin.get(f"/api/orgs/{org.id}")).json()["website"] is None

    events = await audit(owner_engine, org.id, "org.updated")
    assert [(e.actor_user_id, e.subject_type, e.subject_id) for e in events] == [
        (people["Achieng"], "organization", org.id)
    ] * 2
    assert [e.payload for e in events] == [{"fields": ["legal_name", "website"]}, {"fields": ["website"]}]


@pytest.mark.parametrize("verification", ["e1", "e2"])
async def test_a_verified_organisations_name_is_locked_but_its_website_is_not(
    owner_engine: AsyncEngine, member_client: Members, verification: str
) -> None:
    org, people = await org_with(owner_engine, verification, Otieno="{owner,admin}")
    owner = await member_client(people["Otieno"])
    refused = await owner.patch(
        f"/api/orgs/{org.id}", json={"legal_name": "Renamed Ltd", "website": "https://x.example"}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "verified_name_locked",
        "message": "A verified organisation's name changes only through verification.",
    }
    assert tuple(await org_row(owner_engine, org.id)) == (org.name, None)  # the website in the same body is not saved
    assert await audit(owner_engine, org.id, "org.updated") == []

    website = await owner.patch(f"/api/orgs/{org.id}", json={"website": "http://maji.example"})
    assert website.status_code == 200, website.text
    assert tuple(await org_row(owner_engine, org.id)) == (org.name, "http://maji.example/")


# ---------------------------------------------------------------------------------------------- GET members


async def test_members_are_the_active_ones_by_name_with_their_roles(
    owner_engine: AsyncEngine, member_client: Members
) -> None:
    org, people = await org_with(
        owner_engine, "e2", Wanjiru="{owner,admin}", Baraka="{reviewer}", Achieng="{reviewer,signatory}"
    )
    other, outsiders = await org_with(owner_engine, "e2", Njeri="{owner}")
    await remove(owner_engine, org.id, people["Baraka"])
    await join(owner_engine, other.id, people["Achieng"], "{viewer}")  # a membership elsewhere is not listed here

    reviewer = await member_client(people["Achieng"])
    response = await reviewer.get(f"/api/orgs/{org.id}/members")
    assert response.status_code == 200, response.text
    assert [(m["user_id"], m["display_name"], sorted(m["roles"])) for m in response.json()] == [
        (str(people["Achieng"]), "Achieng", ["reviewer", "signatory"]),
        (str(people["Wanjiru"]), "Wanjiru", ["admin", "owner"]),
    ]
    others = (await reviewer.get(f"/api/orgs/{other.id}/members")).json()
    assert [m["display_name"] for m in others] == ["Achieng", "Njeri"]
    assert str(outsiders["Njeri"]) not in response.text

    removed = await member_client(people["Baraka"])  # removed: no longer sees the organisation at all
    assert (await removed.get(f"/api/orgs/{org.id}/members")).json()["detail"] == NOT_FOUND


# ---------------------------------------------------------------------------------------------- PUT roles


async def test_roles_of_anyone_not_an_active_member_here_are_404_and_nothing_changes(
    owner_engine: AsyncEngine, member_client: Members
) -> None:
    org, people = await org_with(owner_engine, "e2", Wanjiru="{owner,admin}", Baraka="{reviewer}")
    other, outsiders = await org_with(owner_engine, "e2", Njeri="{reviewer}")
    await remove(owner_engine, org.id, people["Baraka"])
    owner = await member_client(people["Wanjiru"])
    for user_id in (outsiders["Njeri"], people["Baraka"], uuid4()):  # another org's member, removed, nobody
        refused = await owner.put(f"/api/orgs/{org.id}/members/{user_id}/roles", json={"roles": ["owner"]})
        assert (refused.status_code, refused.json()["detail"]) == (404, NOT_FOUND)
    assert await roles_of(owner_engine, other.id, outsiders["Njeri"]) == (["reviewer"], "active")
    assert await roles_of(owner_engine, org.id, people["Baraka"]) == (["reviewer"], "removed")
    assert await audit(owner_engine, org.id, "org.member_roles_changed") == []
    assert await audit(owner_engine, other.id, "org.member_roles_changed") == []


async def test_an_owner_is_demoted_while_another_owner_remains_and_the_last_one_is_kept(
    owner_engine: AsyncEngine, member_client: Members
) -> None:
    org, people = await org_with(owner_engine, "e2", Wanjiru="{owner,admin}", Otieno="{owner}")
    first = await member_client(people["Wanjiru"])
    demoted = await first.put(f"/api/orgs/{org.id}/members/{people['Otieno']}/roles", json={"roles": ["viewer"]})
    assert demoted.status_code == 200, demoted.text
    assert demoted.json() == {"user_id": str(people["Otieno"]), "display_name": "Otieno", "roles": ["viewer"]}
    assert await roles_of(owner_engine, org.id, people["Otieno"]) == (["viewer"], "active")
    [event] = await audit(owner_engine, org.id, "org.member_roles_changed")
    assert (event.actor_user_id, event.subject_type, event.payload) == (
        people["Wanjiru"],
        "membership",
        {"roles": ["viewer"]},
    )

    last = await first.put(f"/api/orgs/{org.id}/members/{people['Wanjiru']}/roles", json={"roles": ["admin"]})
    assert (last.status_code, last.json()["detail"]["code"]) == (409, "last_owner")
    assert await roles_of(owner_engine, org.id, people["Wanjiru"]) == (["owner", "admin"], "active")


# ---------------------------------------------------------------------------------------------- removed mid-request


def _dependency(annotated: object) -> Any:
    """The callable behind ``Annotated[OrgContext, Depends(...)]`` (what ``dependency_overrides`` is keyed by)."""
    return get_args(annotated)[1].dependency


@pytest.mark.parametrize("route", ["read", "update"])
async def test_a_membership_removed_while_the_request_runs_reads_no_organisation(
    owner_engine: AsyncEngine, member_client: Members, route: str
) -> None:
    """The membership check passes, then the membership is removed (another admin, committed) before the handler
    reads the organisation: RLS no longer shows it to the caller, so the answer is 404 and nothing is written. The
    organisation is unlisted (pending), so the directory's policy does not show it either."""
    org, people = await org_with(owner_engine, "pending", Achieng="{owner,admin}")
    client = await member_client(people["Achieng"])
    checked = _dependency(OrgMember if route == "read" else OrgAdmin)

    async def removed_meanwhile(org_id: UUID, live: CurrentSession, db: Db) -> OrgContext:
        context: OrgContext = await checked(org_id, live, db)
        await remove(owner_engine, org_id, live.user.id)
        return context

    client.app.dependency_overrides[checked] = removed_meanwhile  # type: ignore[attr-defined]
    if route == "read":
        response = await client.get(f"/api/orgs/{org.id}")
    else:
        response = await client.patch(f"/api/orgs/{org.id}", json={"website": "https://maji.example"})
    assert (response.status_code, response.json()["detail"]) == (404, NOT_FOUND)
    assert tuple(await org_row(owner_engine, org.id)) == (org.name, None)
    assert await audit(owner_engine, org.id, "org.updated") == []
