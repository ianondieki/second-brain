"""REQ-TEN-02 (P28 track C, "Joining by invitation"; D-72: one account, one side).

- ``POST /api/auth/signup`` with ``invitation`` (the link's token), side "org" and no ``org``: while the link is open,
  an account with no developer profile, no organisation, no membership and no subscription; a dead link (revoked) or
  no link is 422 ``org_details_required`` (as without one); ``invitation`` with side "developer" or with ``org`` is
  422 ``invitation_conflict``; a malformed one is the request's 422. Nothing is created by a refusal.
- That account confirms its address, signs in (``/me``: side "org", no memberships), accepts, and ``/me`` shows the
  membership.
- ``/me`` for an account without a developer profile is "org" whether or not it has memberships (a removed member).
- Accepting from an account with a developer profile is 409 ``developer_account`` and writes nothing.
- Two accepts at the seat limit at once: the organisation's invitation lock serialises the seat count, so one joins
  and the other is 402 ``plan_limit``.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.ids import uuid7
from bridge.profiles.consents import consents_version
from bridge.seed.reference import seed_all
from tests.integration.api import make_client, outbox, refresh_csrf
from tests.integration.engagements.api_world import clients
from tests.integration.proposals.helpers import add_developer
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

PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="module", autouse=True)
async def seeded(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())


def signup_body(email: str, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "email": email,
        "password": PASSWORD,
        "display_name": "Wanjiku Invitee",
        "side": "org",
        "accept_terms": True,
        "consents": {"reminders": True},
        "consents_version": consents_version(get_settings()),
    }
    return body | changes


def link_token(client: httpx.AsyncClient, to: str) -> str:
    message = [m for m in outbox(client).outbox if m.to == to][-1]
    found = re.search(r"/auth/link#token=([A-Za-z0-9_\-]+)", message.text)
    assert found, message.text
    return found.group(1)


async def account(owner_engine: AsyncEngine, email: str) -> Any:
    found = await rows(
        owner_engine,
        "SELECT u.id,"
        " EXISTS (SELECT 1 FROM developer_profiles d WHERE d.user_id = u.id) AS profile,"
        " (SELECT count(*) FROM memberships m WHERE m.user_id = u.id) AS memberships,"
        " (SELECT count(*) FROM subscriptions s WHERE s.user_id = u.id) AS subscriptions,"
        " (SELECT count(*) FROM organizations o WHERE o.created_by = u.id) AS organisations"
        " FROM users u WHERE u.email = :e",
        e=email,
    )
    return found[0] if found else None


async def test_an_invitee_signs_up_confirms_signs_in_and_joins(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await team_world(owner_engine)
    email = address()
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        assert (await invite(owner, world.org, email, ["reviewer"])).status_code == 201
        token = token_in(mail_to(owner, email)[0])
    async with make_client(app_engine) as browser:
        signed_up = await browser.post("/api/auth/signup", json=signup_body(email, invitation=token))
        assert signed_up.status_code == 202, signed_up.text
        made = await account(owner_engine, email)
        assert made is not None
        assert (made.profile, made.memberships, made.subscriptions, made.organisations) == (False, 0, 0, 0)
        [event] = await rows(
            owner_engine, "SELECT payload FROM audit_events WHERE action = 'auth.signup' AND subject_id = :u", u=made.id
        )
        assert (event.payload["side"], event.payload["invited"]) == ("org", True)

        consumed = await browser.post("/api/auth/magic-link/consume", json={"token": link_token(browser, email)})
        assert consumed.status_code == 200, consumed.text
        await refresh_csrf(browser)
        before = (await browser.get("/api/auth/me")).json()
        assert (before["side"], before["memberships"]) == ("org", [])
        joined = await browser.post(f"/api/invitations/{token}/accept")
        assert joined.status_code == 200, joined.text
        after = (await browser.get("/api/auth/me")).json()
        assert after["side"] == "org"
        assert [(m["org_id"], m["roles"]) for m in after["memberships"]] == [(str(world.org), ["reviewer"])]


async def test_a_dead_or_absent_link_and_the_conflicts_create_nothing(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await team_world(owner_engine)
    email = address()
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        made = (await invite(owner, world.org, email)).json()
        token = token_in(mail_to(owner, email)[0])
        assert (await owner.delete(f"/api/orgs/{world.org}/invitations/{made['id']}")).status_code == 204
    org = {"legal_name": "Maji Co (fixture)", "kind": "company"}
    async with make_client(app_engine) as browser:
        for body, refused in (
            (signup_body(email, invitation=token), (422, "org_details_required")),  # revoked: as without a link
            (signup_body(email), (422, "org_details_required")),
            (signup_body(email, side="developer", invitation=token), (422, "invitation_conflict")),
            (signup_body(email, org=org, invitation=token), (422, "invitation_conflict")),
            (signup_body(email, invitation="A" * 42), (422, None)),  # malformed: the request's own 422
        ):
            assert code(await browser.post("/api/auth/signup", json=body)) == refused
        assert [m for m in outbox(browser).outbox if m.to == email] == []
    assert await account(owner_engine, email) is None


async def test_me_is_org_for_an_account_without_a_profile_member_or_not(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await team_world(owner_engine)
    leaver, _ = await person(owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO memberships (id, org_id, user_id, roles, status)"
                " VALUES (:id, :o, :u, '{viewer}', 'removed')"
            ),
            {"id": uuid7(), "o": world.org, "u": leaver},
        )
    developer = await add_developer(owner_engine)
    async with clients(app_engine, SETTINGS, leaver, developer, world.viewer) as (removed, dev, member):
        assert (await removed.get("/api/auth/me")).json()["side"] == "org"
        assert (await removed.get("/api/auth/me")).json()["memberships"] == []
        assert (await dev.get("/api/auth/me")).json()["side"] == "developer"
        assert (await member.get("/api/auth/me")).json()["side"] == "org"


async def test_a_developer_account_cannot_accept_and_nothing_is_written(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await team_world(owner_engine)
    developer = await add_developer(owner_engine)
    [row] = await rows(owner_engine, "SELECT email::text AS email FROM users WHERE id = :u", u=developer)
    email = f"dev-{uuid7().hex[:10]}@example.com"
    async with owner_engine.begin() as conn:  # an address an invitation can be sent to (EmailStr refuses .test)
        await conn.execute(text("UPDATE users SET email = :e WHERE id = :u"), {"e": email, "u": developer})
    assert row.email != email
    async with clients(app_engine, SETTINGS, world.owner, developer) as (owner, dev):
        made = (await invite(owner, world.org, email)).json()
        token = token_in(mail_to(owner, email)[0])
        assert code(await dev.post(f"/api/invitations/{token}/accept")) == (409, "developer_account")
        assert (await dev.get(f"/api/invitations/{token}")).status_code == 200  # still open
    assert await rows(owner_engine, "SELECT 1 FROM memberships WHERE user_id = :u", u=developer) == []
    [still] = await rows(owner_engine, "SELECT accepted_at FROM invitations WHERE id = :i", i=made["id"])
    assert still.accepted_at is None


async def test_two_accepts_at_the_seat_limit_are_counted_one_after_the_other(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await team_world(owner_engine, plan="org_starter")  # 5 seats, 5 members
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE memberships SET status = 'removed' WHERE org_id = :o AND user_id = ANY(:u)"),
            {"o": world.org, "u": [world.viewer, world.finance]},
        )
    (first, first_email), (second, second_email) = await person(owner_engine), await person(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        for email in (first_email, second_email):  # 3 members + 2 invitations = 5 seats
            assert (await invite(owner, world.org, email)).status_code == 201
        tokens = [token_in(mail_to(owner, email)[0]) for email in (first_email, second_email)]
    async with owner_engine.begin() as conn:  # a fourth member joins another way: one seat is left
        await conn.execute(
            text("UPDATE memberships SET status = 'active' WHERE org_id = :o AND user_id = :u"),
            {"o": world.org, "u": world.viewer},
        )
    async with clients(app_engine, SETTINGS, first, second) as (a, b):
        answers = await asyncio.gather(
            a.post(f"/api/invitations/{tokens[0]}/accept"), b.post(f"/api/invitations/{tokens[1]}/accept")
        )
    assert sorted(code(answer) for answer in answers) == [(200, None), (402, "plan_limit")]
    active = await rows(
        owner_engine, "SELECT count(*) FROM memberships WHERE org_id = :o AND status = 'active'", o=world.org
    )
    assert active[0][0] == 5
    joined = {
        UUID(str(r.user_id))
        for r in await rows(
            owner_engine,
            "SELECT user_id FROM memberships WHERE org_id = :o AND user_id = ANY(:u)",
            o=world.org,
            u=[first, second],
        )
    }
    assert len(joined) == 1
