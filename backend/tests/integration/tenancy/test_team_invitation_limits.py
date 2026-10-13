"""REQ-TEN-02 (P28 track C): the reviews' controls on invitations.

- Only an organisation at least E1 invites or resends (403 ``org_not_verified``).
- Each email counts first against the send limits (``bridge.tenancy.invitation_limits``): 10 an hour per caller, 30 a
  day per organisation, 3 per recipient address and IP in 15 minutes and 20 per address a day, invite and resend
  alike; past one, 429 ``rate_limited`` with ``Retry-After`` and no invitation row.
- Re-inviting an address over an expired open invitation that holds owner or signatory is an owner's (403
  ``protected_role``; the old invitation is left as it is).
- The plan's ``seats`` bound active members plus unexpired open invitations (402 ``plan_limit`` naming ``seats``),
  and accepting re-checks them with the joiner counted (402, nothing joined).
- A resend to an address that has become a member is 409 ``already_member``.
- An invitation's link lasts 7 days from its creation on the shared clock, the test clock moved included.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from bridge.tenancy import invitation_limits, team_router
from tests.integration.api import make_client
from tests.integration.engagements.api_world import World, clients
from tests.integration.tenancy.team_helpers import (
    SETTINGS,
    address,
    code,
    invite,
    mail_to,
    person,
    rows,
    team_world,
    token_in,
)


async def run(owner_engine: AsyncEngine, sql: str, **params: object) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(text(sql), params)


async def join(owner_engine: AsyncEngine, org: UUID, user: UUID, roles: str = "{viewer}") -> None:
    await run(
        owner_engine,
        "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :o, :u, CAST(:r AS org_role[]))",
        id=uuid7(),
        o=org,
        u=user,
        r=roles,
    )


async def invitations_of(owner_engine: AsyncEngine, org: UUID) -> list[Any]:
    return await rows(
        owner_engine,
        "SELECT id, email::text AS email, revoked_at, accepted_at FROM invitations WHERE org_id = :o"
        " ORDER BY created_at",
        o=org,
    )


def retry_after(response: Any) -> int:
    assert code(response) == (429, "rate_limited"), response.text
    seconds = int(response.headers["retry-after"])
    assert seconds > 0
    return seconds


async def test_only_an_organisation_at_least_e1_invites(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await team_world(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        made = (await invite(owner, world.org, address())).json()
        for level in ("pending", "unclaimed"):
            level_sql = "UPDATE organizations SET verification = CAST(:v AS org_verification) WHERE id = :o"
            await run(owner_engine, level_sql, v=level, o=world.org)
            assert code(await invite(owner, world.org, address())) == (403, "org_not_verified")
            resend = await owner.post(f"/api/orgs/{world.org}/invitations/{made['id']}/resend")
            assert code(resend) == (403, "org_not_verified")
        await run(owner_engine, "UPDATE organizations SET verification = 'e1' WHERE id = :o", o=world.org)
        assert (await invite(owner, world.org, address())).status_code == 201
    assert len(await invitations_of(owner_engine, world.org)) == 2


async def test_a_caller_sends_at_most_ten_an_hour_invites_and_resends_alike(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await team_world(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        first = (await invite(owner, world.org, address())).json()
        assert (await owner.post(f"/api/orgs/{world.org}/invitations/{first['id']}/resend")).status_code == 200
        for _ in range(invitation_limits.SENDS_PER_HOUR - 2):
            assert (await invite(owner, world.org, address())).status_code == 201
        retry_after(await invite(owner, world.org, address()))
        newest = (await owner.get(f"/api/orgs/{world.org}/team")).json()["invitations"][0]
        retry_after(await owner.post(f"/api/orgs/{world.org}/invitations/{newest['id']}/resend"))
    assert len(await invitations_of(owner_engine, world.org)) == invitation_limits.SENDS_PER_HOUR  # nothing more


async def test_an_organisation_sends_a_bounded_number_a_day_whoever_sends(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(invitation_limits, "ORG_SENDS_PER_DAY", 3)
    world = await team_world(owner_engine)
    admin, _ = await person(owner_engine)
    await join(owner_engine, world.org, admin, "{admin}")
    async with clients(app_engine, SETTINGS, world.owner, admin) as (owner, second):
        for sender in (owner, second, owner):
            assert (await invite(sender, world.org, address())).status_code == 201
        retry_after(await invite(second, world.org, address()))


async def test_one_address_gets_a_bounded_number_across_organisations(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(invitation_limits, "ADDRESS_PER_DAY", invitation_limits.ADDRESS_PER_WINDOW + 1)
    world, other = await team_world(owner_engine), await team_world(owner_engine)
    target = address()
    async with clients(app_engine, SETTINGS, world.owner, other.owner) as (owner, elsewhere):  # two client IPs
        for _ in range(invitation_limits.ADDRESS_PER_WINDOW):
            made = await invite(owner, world.org, target)
            assert made.status_code == 201, made.text
            assert (await owner.delete(f"/api/orgs/{world.org}/invitations/{made.json()['id']}")).status_code == 204
        seconds = retry_after(await invite(owner, world.org, target))  # 3 from this address and IP in 15 minutes
        assert seconds <= int(invitation_limits.ADDRESS_WINDOW.total_seconds())
        assert (await invite(elsewhere, other.org, target)).status_code == 201  # another IP: the daily count is 4
        theirs = (await elsewhere.get(f"/api/orgs/{other.org}/team")).json()["invitations"][0]
        retry_after(await elsewhere.post(f"/api/orgs/{other.org}/invitations/{theirs['id']}/resend"))  # the day's
    assert len(mail_to(owner, target)) == invitation_limits.ADDRESS_PER_WINDOW
    assert len(mail_to(elsewhere, target)) == 1


async def test_an_admin_never_reinvites_over_a_protected_expired_invitation(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await team_world(owner_engine)
    admin, _ = await person(owner_engine)
    await join(owner_engine, world.org, admin, "{admin}")
    target = address()
    async with clients(app_engine, SETTINGS, world.owner, admin) as (owner, an_admin):
        made = (await invite(owner, world.org, target, ["signatory"])).json()
        expire = "UPDATE invitations SET expires_at = app_clock_now() - interval '1 minute' WHERE id = :i"
        await run(owner_engine, expire, i=made["id"])
        assert code(await invite(an_admin, world.org, target, ["reviewer"])) == (403, "protected_role")
        [old] = [i for i in await invitations_of(owner_engine, world.org) if str(i.id) == made["id"]]
        assert old.revoked_at is None  # left as it was
        assert (await invite(owner, world.org, target, ["reviewer"])).status_code == 201  # an owner may


async def test_the_plan_s_seats_bound_members_and_open_invitations(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    free = await team_world(owner_engine, plan=None)  # Claimed (Free): 2 seats, 5 members already
    starter = await team_world(owner_engine, plan="org_starter")  # 5 seats, 5 members
    async with clients(app_engine, SETTINGS, free.owner, starter.owner) as (free_owner, owner):
        refused = await invite(free_owner, free.org, address())
        assert code(refused) == (402, "plan_limit")
        detail = refused.json()["detail"]
        assert (detail["limit_key"], detail["limit"], detail["used"], detail["plan"]) == ("seats", 2, 5, "org_claimed")
        assert detail["upgrade"]["plan"] == "org_starter"
        assert code(await invite(owner, starter.org, address())) == (402, "plan_limit")
        await run(
            owner_engine,
            "UPDATE memberships SET status = 'removed' WHERE org_id = :o AND user_id = :u",
            o=starter.org,
            u=starter.viewer,
        )
        invitee, email = await person(owner_engine)
        assert (await invite(owner, starter.org, email)).status_code == 201  # 4 members + 1 invitation = 5
        refused = await invite(owner, starter.org, address())
        assert (code(refused), refused.json()["detail"]["used"]) == ((402, "plan_limit"), 5)
        token = token_in(mail_to(owner, email)[0])
        await join(owner_engine, starter.org, (await person(owner_engine))[0])  # a fifth member joins another way
    async with clients(app_engine, SETTINGS, invitee) as (newcomer,):
        accepted = await newcomer.post(f"/api/invitations/{token}/accept")
        assert code(accepted) == (402, "plan_limit")
        assert accepted.json()["detail"]["limit_key"] == "seats"
        assert (await newcomer.get(f"/api/invitations/{token}")).status_code == 200  # still open
    joined = await rows(
        owner_engine, "SELECT 1 FROM memberships WHERE org_id = :o AND user_id = :u", o=starter.org, u=invitee
    )
    assert joined == []


async def test_a_resend_to_someone_who_joined_meanwhile_is_409(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await team_world(owner_engine)
    joiner, email = await person(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        made = (await invite(owner, world.org, email)).json()
        await join(owner_engine, world.org, joiner)
        assert code(await owner.post(f"/api/orgs/{world.org}/invitations/{made['id']}/resend")) == (
            409,
            "already_member",
        )


@pytest.fixture
async def moved_clock(owner_engine: AsyncEngine) -> AsyncIterator[timedelta]:
    """The shared test clock moved 10 days ahead for one test, then put back as it was."""
    [before] = await rows(owner_engine, "SELECT enabled, clock_offset FROM test_clock WHERE singleton")
    await run(owner_engine, "UPDATE test_clock SET enabled = true, clock_offset = clock_offset + interval '10 days'")
    try:
        yield timedelta(days=10)
    finally:
        await run(
            owner_engine,
            "UPDATE test_clock SET enabled = :e, clock_offset = :o",
            e=before.enabled,
            o=before.clock_offset,
        )


async def test_a_link_lasts_seven_days_on_the_shared_clock(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, moved_clock: timedelta
) -> None:
    world: World = await team_world(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        made = (await invite(owner, world.org, address())).json()
        resent = (await owner.post(f"/api/orgs/{world.org}/invitations/{made['id']}/resend")).json()
    for invitation in (made, resent):
        [row] = await rows(
            owner_engine,
            "SELECT expires_at - created_at AS lasts, created_at - clock_timestamp() AS ahead FROM invitations"
            " WHERE id = :i",
            i=invitation["id"],
        )
        assert abs(row.lasts - timedelta(days=7)) < timedelta(seconds=1)
        assert abs(row.ahead - moved_clock) < timedelta(minutes=1)  # created on the moved clock, not the wall's


async def test_sends_the_database_refuses_still_count(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The count is committed before the invitation is checked: SENDS_PER_HOUR invites refused with 409
    already_member still use the hour, so the next one is 429 (a refused send is not free)."""
    monkeypatch.setattr(invitation_limits, "SENDS_PER_HOUR", 3)
    world = await team_world(owner_engine)
    member, email = await person(owner_engine)
    await join(owner_engine, world.org, member)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        for _ in range(3):
            assert code(await invite(owner, world.org, email)) == (409, "already_member")
        retry_after(await invite(owner, world.org, address()))
    assert await invitations_of(owner_engine, world.org) == []


async def test_visitors_behind_a_shared_address_share_one_capped_bucket(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The preview's shared bucket (non-global or trusted-proxy addresses) has its own cap: past it, 429."""
    monkeypatch.setattr(team_router, "SHARED_PREVIEWS_PER_MINUTE", 2)
    monkeypatch.setattr(team_router, "SHARED_PREVIEW_PURPOSE", f"preview-shared-{uuid7().hex}")  # a fresh bucket
    world = await team_world(owner_engine)
    email = address()
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        assert (await invite(owner, world.org, email)).status_code == 201
        token = token_in(mail_to(owner, email)[0])
    async with (
        make_client(app_engine, SETTINGS, ip="192.168.7.20") as first,
        make_client(app_engine, SETTINGS, ip="10.1.2.3") as second,
    ):
        assert (await first.get(f"/api/invitations/{token}")).status_code == 200
        assert (await second.get(f"/api/invitations/{token}")).status_code == 200
        assert code(await first.get(f"/api/invitations/{token}")) == (429, "rate_limited")  # one bucket for both
        assert code(await second.get(f"/api/invitations/{token}")) == (429, "rate_limited")
