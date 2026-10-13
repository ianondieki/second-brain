"""REQ-TEN-02 (P28 track C): the database's backstops behind the Team API's own checks, and the remaining edges.

Each check the API makes first has a guard in revision 0015 behind it. A test stands in for the race by replacing the
API's check, so the database answers, and the API must give the same code: the niche default's guard (422
``invalid_default_reviewer``), the escalation contact's guard (422 ``invalid_member``), the last-owner guard (409
``last_owner``), and an invitation revoked or accepted between the read and the write (409 ``invitation_closed``).
And: a valid address that is not one plain mailbox is 422 ``invalid_email``; accepting with a malformed link is 404;
an active member accepting an invitation to their own address is 409 ``already_member``.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from bridge.auth.crypto import new_token, token_hash
from bridge.ids import uuid7
from bridge.models.enums import OrgRole
from bridge.tenancy import invitations, team, team_settings
from tests.integration.engagements.api_world import clients
from tests.integration.tenancy.team_helpers import SETTINGS, address, code, invite, person, rows, team_world


async def test_the_niche_default_guard_answers_as_the_api_does(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await team_world(owner_engine)
    [niche] = await rows(owner_engine, "SELECT niche_id FROM proposal_versions WHERE id = :v", v=world.version)
    [found] = await rows(owner_engine, "SELECT slug FROM niches WHERE id = :n", n=niche.niche_id)

    async def anyone_reviews(db: AsyncSession, org_id: UUID, user_ids: list[UUID]) -> dict[UUID, frozenset[OrgRole]]:
        return dict.fromkeys(user_ids, frozenset({OrgRole.REVIEWER}))

    monkeypatch.setattr(team_settings, "_active_roles", anyone_reviews)
    body = {"items": [{"niche_slug": found.slug, "user_id": str(world.finance)}]}
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        refused = await owner.put(f"/api/orgs/{world.org}/niche-defaults", json=body)
    assert code(refused) == (422, "invalid_default_reviewer")
    assert await rows(owner_engine, "SELECT 1 FROM org_niche_defaults WHERE org_id = :o", o=world.org) == []


async def test_the_escalation_contact_guard_answers_as_the_api_does(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await team_world(owner_engine)

    async def anyone_is_a_member(db: AsyncSession, org_id: UUID, user_id: UUID) -> str:
        return "Someone"

    monkeypatch.setattr(team_settings, "_member_name", anyone_is_a_member)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        refused = await owner.put(f"/api/orgs/{world.org}/escalation-contact", json={"user_id": str(world.outsider)})
    assert code(refused) == (422, "invalid_member")


async def test_the_last_owner_guard_answers_as_the_api_does(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await team_world(owner_engine)

    async def someone_else_owns(db: AsyncSession, org_id: UUID, user_id: UUID) -> bool:
        return True

    monkeypatch.setattr(team, "_another_owner", someone_else_owns)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        refused = await owner.delete(f"/api/orgs/{world.org}/members/{world.owner}")
    assert code(refused) == (409, "last_owner")
    [row] = await rows(
        owner_engine,
        "SELECT status::text AS status FROM memberships WHERE org_id = :o AND user_id = :u",
        o=world.org,
        u=world.owner,
    )
    assert row.status == "active"


async def test_an_invitation_closed_meanwhile_is_409(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await team_world(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        made = (await invite(owner, world.org, address())).json()

        async def closed_meanwhile(db: AsyncSession, invitation_id: UUID) -> bool:
            return False

        monkeypatch.setattr(invitations, "_close", closed_meanwhile)
        path = f"/api/orgs/{world.org}/invitations/{made['id']}"
        assert code(await owner.post(f"{path}/resend")) == (409, "invitation_closed")
        assert code(await owner.delete(path)) == (409, "invitation_closed")


async def test_an_address_that_is_not_one_plain_mailbox_is_422(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await team_world(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        assert code(await invite(owner, world.org, "jörg@example.com")) == (422, "invalid_email")


async def test_a_malformed_link_is_404_and_a_member_accepting_is_409(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await team_world(owner_engine)
    member, email = await person(owner_engine)
    token = new_token()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, '{viewer}')"),
            {"id": uuid7(), "org": world.org, "u": member},
        )
        await conn.execute(  # an invitation to someone who joined some other way meanwhile
            text(
                "INSERT INTO invitations (id, org_id, email, roles, token_hash, invited_by, expires_at)"
                " VALUES (:id, :org, :email, '{reviewer}', :hash, :by, app_clock_now() + :days)"
            ),
            {
                "id": uuid7(),
                "org": world.org,
                "email": email,
                "hash": token_hash(token),
                "by": world.owner,
                "days": timedelta(days=7),
            },
        )
    async with clients(app_engine, SETTINGS, member) as (joined,):
        assert code(await joined.post("/api/invitations/not-a-token/accept")) == (404, "not_found")
        assert code(await joined.post(f"/api/invitations/{token}/accept")) == (409, "already_member")
    [row] = await rows(
        owner_engine,
        "SELECT CAST(roles AS text[]) AS roles FROM memberships WHERE org_id = :o AND user_id = :u",
        o=world.org,
        u=member,
    )
    assert row.roles == ["viewer"]  # unchanged


async def test_two_invitations_to_one_address_at_once_meet_the_unique_index(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await team_world(owner_engine)
    to = address()
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        assert (await invite(owner, world.org, to)).status_code == 201

        async def none_open(db: AsyncSession, org_id: UUID, *, email: str | None = None) -> int:
            return 0

        monkeypatch.setattr(invitations, "_open_unexpired", none_open)  # as if the first had not committed yet
        assert code(await invite(owner, world.org, to)) == (409, "already_invited")  # uq_invitations_open
