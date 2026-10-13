"""REQ-TEN-02 (P28 track C, AT-C-1): invite by email, preview the link, accept with the matching verified address.

- An owner invites an address with roles: 201, one email to that address carrying the link; the open invitation shows
  on the Team page (owners and admins only); the public preview answers the organisation's name and the roles, with
  no session, no cookie and ``no-store``; the invitee, signed in with that verified address (in any letter case),
  accepts and is a member with those roles; the link is then dead (preview and accept 404).
- A different signed-in address, or the right one unverified, is 403 ``invitation_email_mismatch``; an active member's
  address is 409 ``already_member``; an address with an open invitation is 409 ``already_invited``.
- A revoked link, a resent-over link and an expired link are 404; an expired invitation is shown as expired and its
  address can be invited again; the 21st open invitation of an organisation is 409 ``too_many_invitations`` (an
  expired one does not count).
- An admin inviting an owner or a signatory is 403 ``protected_role``; a member who is not an admin is 403 and reads no
  invitations or addresses; another organisation's member is 404; another organisation's invitation is 404 by this
  organisation's path; without a fresh second factor 403 ``step_up_required``.
- Each step is audited by ids and roles; the token is in no audit row.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.ids import uuid7
from bridge.tenancy.invitations import MAX_OPEN
from bridge.tenancy.team_router import PREVIEWS_PER_MINUTE
from tests.integration.api import make_client
from tests.integration.engagements.api_world import build, clients
from tests.integration.tenancy.team_helpers import (
    SETTINGS,
    address,
    audit_actions,
    code,
    invite,
    mail_to,
    person,
    rows,
    token_in,
)


async def expire(owner_engine: AsyncEngine, invitation: str) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE invitations SET expires_at = app_clock_now() - interval '1 minute' WHERE id = :id"),
            {"id": invitation},
        )


async def test_an_invitation_is_emailed_previewed_and_accepted_by_its_address(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    invitee, email = await person(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner, invitee) as (owner, newcomer):
        created = await invite(owner, world.org, email.upper(), ["reviewer", "finance"])
        assert created.status_code == 201, created.text
        body = created.json()
        assert (body["email"], body["roles"], body["expired"]) == (email, ["finance", "reviewer"], False)
        assert body["invited_by_name"]
        assert "token" not in body
        [message] = mail_to(owner, email)
        token = token_in(message)
        assert message.subject.endswith(f"invited you to join {world.org_name} on {get_settings().product_name}")
        assert "as reviewer and finance" in message.text

        team = (await owner.get(f"/api/orgs/{world.org}/team")).json()
        assert [i["id"] for i in team["invitations"]] == [body["id"]]

        async with make_client(app_engine) as visitor:  # signed out: the link alone
            visitor.cookies.clear()
            preview = await visitor.get(f"/api/invitations/{token}")
            assert preview.status_code == 200, preview.text
            assert preview.json() == {"org_name": world.org_name, "roles": ["finance", "reviewer"]}
            assert preview.headers["cache-control"] == "no-store"
            assert "set-cookie" not in preview.headers

        accepted = await newcomer.post(f"/api/invitations/{token}/accept")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json() == {
            "org_id": str(world.org),
            "org_name": world.org_name,
            "roles": ["finance", "reviewer"],
        }
        assert code(await newcomer.post(f"/api/invitations/{token}/accept")) == (404, "not_found")
        assert (await newcomer.get(f"/api/invitations/{token}")).status_code == 404

        team = (await owner.get(f"/api/orgs/{world.org}/team")).json()
        assert team["invitations"] == []
        [joined] = [m for m in team["members"] if m["user_id"] == str(invitee)]
        assert (joined["roles"], joined["email"]) == (["finance", "reviewer"], email)
        mine = (await newcomer.get("/api/orgs")).json()
        assert [(o["org"]["id"], o["roles"]) for o in mine] == [(str(world.org), ["finance", "reviewer"])]

    events = await audit_actions(owner_engine, world.org, "org.invitation_")
    assert [(e.action, e.actor_user_id) for e in events] == [
        ("org.invitation_created", world.owner),
        ("org.invitation_accepted", invitee),
    ]
    assert events[0].payload == {"invitation_id": body["id"], "roles": ["finance", "reviewer"]}
    assert events[1].payload == {"user_id": str(invitee), "roles": ["finance", "reviewer"]}
    assert token not in str([e.payload for e in events])
    [stored] = await rows(owner_engine, "SELECT token_hash FROM invitations WHERE id = :id", id=body["id"])
    assert token.encode() not in bytes(stored.token_hash)
    sent = await rows(
        owner_engine,
        "SELECT status::text AS status, user_id, to_address FROM notification_deliveries"
        " WHERE org_id = :org AND kind = 'org.invitation'",
        org=world.org,
    )
    assert [(d.status, d.user_id, d.to_address) for d in sent] == [("sent", None, email)]  # the ledger's row


async def test_another_address_is_403_a_member_409_and_a_second_invitation_409(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    other, _ = await person(owner_engine)
    unverified, email = await person(owner_engine, verified=False)
    member, member_email = await person(owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, '{viewer}')"),
            {"id": uuid7(), "org": world.org, "u": member},
        )
    async with clients(app_engine, SETTINGS, world.owner, other, unverified) as (owner, stranger, unconfirmed):
        assert (await invite(owner, world.org, email)).status_code == 201
        token = token_in(mail_to(owner, email)[0])
        assert code(await stranger.post(f"/api/invitations/{token}/accept")) == (403, "invitation_email_mismatch")
        assert code(await unconfirmed.post(f"/api/invitations/{token}/accept")) == (403, "invitation_email_mismatch")
        assert (await stranger.get(f"/api/invitations/{token}")).status_code == 200  # still open

        assert code(await invite(owner, world.org, member_email.upper())) == (409, "already_member")
        assert code(await invite(owner, world.org, email.upper())) == (409, "already_invited")
        assert code(await invite(owner, world.org, "Not An Address <x@example.test>")) == (422, None)
    members = await rows(
        owner_engine, "SELECT 1 FROM memberships WHERE org_id = :o AND user_id = :u", o=world.org, u=other
    )
    assert members == []


async def test_revoked_resent_and_expired_links_are_404(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    revoked_to, resent_to, expired_to = address(), address(), address()
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        revoked = (await invite(owner, world.org, revoked_to)).json()
        resent = (await invite(owner, world.org, resent_to)).json()
        expired = (await invite(owner, world.org, expired_to)).json()
        tokens = {to: token_in(mail_to(owner, to)[0]) for to in (revoked_to, resent_to, expired_to)}

        gone = await owner.delete(f"/api/orgs/{world.org}/invitations/{revoked['id']}")
        assert gone.status_code == 204, gone.text
        assert code(await owner.delete(f"/api/orgs/{world.org}/invitations/{revoked['id']}")) == (
            409,
            "invitation_closed",
        )
        again = await owner.post(f"/api/orgs/{world.org}/invitations/{resent['id']}/resend")
        assert again.status_code == 200, again.text
        assert again.json()["id"] == resent["id"]
        old, new = tokens[resent_to], token_in(mail_to(owner, resent_to)[1])
        assert old != new
        await expire(owner_engine, expired["id"])

        for dead in (tokens[revoked_to], old, tokens[expired_to]):
            assert (await owner.get(f"/api/invitations/{dead}")).status_code == 404
        assert (await owner.get(f"/api/invitations/{new}")).status_code == 200
        assert (await owner.get(f"/api/invitations/{'x' * 10}")).status_code == 404  # malformed: no lookup

        listed = {i["id"]: i["expired"] for i in (await owner.get(f"/api/orgs/{world.org}/team")).json()["invitations"]}
        assert listed == {resent["id"]: False, expired["id"]: True}
        renewed = await invite(owner, world.org, expired_to)  # the expired one is revoked first
        assert renewed.status_code == 201, renewed.text
        listed = {i["id"] for i in (await owner.get(f"/api/orgs/{world.org}/team")).json()["invitations"]}
        assert listed == {resent["id"], renewed.json()["id"]}
    for dead_one in (revoked, expired):
        [row] = await rows(owner_engine, "SELECT revoked_at FROM invitations WHERE id = :id", id=dead_one["id"])
        assert row.revoked_at is not None
    events = [e.action for e in await audit_actions(owner_engine, world.org, "org.invitation_")]
    assert events.count("org.invitation_revoked") == 1
    assert events.count("org.invitation_resent") == 1


async def test_an_expired_link_is_404_when_accepted(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    invitee, email = await person(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner, invitee) as (owner, newcomer):
        made = (await invite(owner, world.org, email)).json()
        token = token_in(mail_to(owner, email)[0])
        await expire(owner_engine, made["id"])
        assert code(await newcomer.post(f"/api/invitations/{token}/accept")) == (404, "not_found")
        resent = await owner.post(f"/api/orgs/{world.org}/invitations/{made['id']}/resend")  # an expired one renews
        assert (resent.status_code, resent.json()["expired"]) == (200, False)
        fresh = token_in(mail_to(owner, email)[1])
        assert (await newcomer.post(f"/api/invitations/{fresh}/accept")).status_code == 200


async def test_the_21st_open_invitation_is_409(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        made = []
        for _ in range(MAX_OPEN):
            response = await invite(owner, world.org, address())
            assert response.status_code == 201, response.text
            made.append(response.json()["id"])
        refused = await invite(owner, world.org, address())
        assert code(refused) == (409, "too_many_invitations")
        assert refused.json()["detail"]["limit"] == MAX_OPEN
        await expire(owner_engine, made[0])  # an expired invitation does not count
        assert (await invite(owner, world.org, address())).status_code == 201
        assert code(await owner.post(f"/api/orgs/{world.org}/invitations/{made[0]}/resend")) == (
            409,
            "too_many_invitations",
        )
        assert (await owner.delete(f"/api/orgs/{world.org}/invitations/{made[1]}")).status_code == 204
        assert (await owner.post(f"/api/orgs/{world.org}/invitations/{made[0]}/resend")).status_code == 200


async def test_who_may_invite_what_and_whose(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    other = await build(owner_engine)
    admin, _ = await person(owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, '{admin}')"),
            {"id": uuid7(), "org": world.org, "u": admin},
        )
    async with clients(app_engine, SETTINGS, world.owner, admin, world.reviewer, other.owner) as (
        owner,
        an_admin,
        reviewer,
        outsider,
    ):
        for roles in (["signatory"], ["owner", "admin"]):
            assert code(await invite(an_admin, world.org, address(), roles)) == (403, "protected_role")
        mine = await invite(an_admin, world.org, address(), ["admin", "reviewer"])
        assert mine.status_code == 201, mine.text
        protected = (await invite(owner, world.org, address(), ["signatory"])).json()
        resend = f"/api/orgs/{world.org}/invitations/{protected['id']}/resend"
        assert code(await an_admin.post(resend)) == (403, "protected_role")
        revoke = f"/api/orgs/{world.org}/invitations/{protected['id']}"
        assert code(await an_admin.delete(revoke)) == (403, "protected_role")

        assert code(await invite(reviewer, world.org, address())) == (403, "forbidden")
        team = (await reviewer.get(f"/api/orgs/{world.org}/team")).json()
        assert team["invitations"] is None
        assert {m["email"] for m in team["members"]} == {None}
        assert code(await invite(outsider, world.org, address())) == (404, "not_found")
        assert (await outsider.get(f"/api/orgs/{world.org}/team")).status_code == 404
        theirs = (await invite(outsider, other.org, address())).json()
        assert code(await owner.delete(f"/api/orgs/{world.org}/invitations/{theirs['id']}")) == (404, "not_found")
        assert code(await owner.post(f"/api/orgs/{world.org}/invitations/{theirs['id']}/resend")) == (404, "not_found")
    async with clients(app_engine, SETTINGS, world.owner) as (stale,):
        async with owner_engine.begin() as conn:  # the second factor was 13 hours ago (ADR-002: 12 h)
            await conn.execute(
                text("UPDATE sessions SET mfa_verified_at = now() - interval '13 hours' WHERE user_id = :u"),
                {"u": world.owner},
            )
        assert code(await invite(stale, world.org, address())) == (403, "step_up_required")


async def test_the_public_demo_locks_accepting_but_not_the_preview(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    invitee, email = await person(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        assert (await invite(owner, world.org, email)).status_code == 201
        token = token_in(mail_to(owner, email)[0])
    demo = SETTINGS.model_copy(update={"public_demo": True})
    async with clients(app_engine, demo, world.owner, invitee) as (owner, newcomer):
        assert (await newcomer.get(f"/api/invitations/{token}")).status_code == 200
        assert code(await newcomer.post(f"/api/invitations/{token}/accept")) == (403, "public_demo_locked")
        assert code(await invite(owner, world.org, address())) == (403, "public_demo_locked")
        assert (await owner.get(f"/api/orgs/{world.org}/team")).status_code == 200


async def test_the_preview_is_one_404_for_every_dead_link_and_is_throttled_per_address(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The reviewer's notes: one uniform 404 (malformed, unknown, revoked, expired), only the name and the roles of a
    live link, every read counted against the client address (30 a minute, then 429); roles are never empty (422)."""
    world = await build(owner_engine)
    async with clients(app_engine, SETTINGS, world.owner) as (owner,):
        empty = await owner.post(f"/api/orgs/{world.org}/invitations", json={"email": address(), "roles": []})
        assert empty.status_code == 422
        revoked_to, expired_to, live_to = address(), address(), address()
        revoked = (await invite(owner, world.org, revoked_to)).json()
        expired = (await invite(owner, world.org, expired_to)).json()
        assert (await invite(owner, world.org, live_to)).status_code == 201
        tokens = {to: token_in(mail_to(owner, to)[0]) for to in (revoked_to, expired_to, live_to)}
        assert (await owner.delete(f"/api/orgs/{world.org}/invitations/{revoked['id']}")).status_code == 204
        await expire(owner_engine, expired["id"])
    ip = f"10.{uuid7().int % 250}.{uuid7().int % 250}.{uuid7().int % 250 + 1}"
    async with make_client(app_engine, SETTINGS, ip=ip) as visitor:
        dead = ["x" * 10, "A" * 43, tokens[revoked_to], tokens[expired_to]]
        answers = [await visitor.get(f"/api/invitations/{token}") for token in dead]
        assert {(a.status_code, a.text) for a in answers} == {(404, answers[0].text)}
        live = await visitor.get(f"/api/invitations/{tokens[live_to]}")
        assert set(live.json()) == {"org_name", "roles"}
        for _ in range(PREVIEWS_PER_MINUTE - len(dead) - 1):
            assert (await visitor.get(f"/api/invitations/{tokens[live_to]}")).status_code == 200
        assert code(await visitor.get(f"/api/invitations/{tokens[live_to]}")) == (429, "rate_limited")
        assert code(await visitor.get("/api/invitations/short")) == (429, "rate_limited")
