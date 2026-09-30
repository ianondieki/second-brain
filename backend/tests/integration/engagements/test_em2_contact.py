"""AC-MAIL-1 (REQ-NOT-04) and AC-TRACK-9's contact half (REQ-ENG-05).

- Entering INTEREST_CONFIRMED sends EM2 to the developer exactly once (the job may run again: one email), with the
  spec's copy, the named contact, the contact-by date and a ``tier2_status`` that matches the Tier-2 access log.
- Before INTEREST_CONFIRMED nobody at the organisation reads the developer's contact details (403); afterwards the
  named contact does (verified email; audit-logged), and nobody else.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import (
    PROPOSAL_TITLE,
    Tracker,
    World,
    build,
    clients,
    db_today,
    deals_on,
    notification_jobs,
    open_engagement,
    run_notifications,
    seats,
    walk_to,
)


async def display_name(owner_engine: AsyncEngine, user: UUID) -> str:
    async with owner_engine.connect() as conn:
        return str((await conn.execute(text("SELECT display_name FROM users WHERE id = :u"), {"u": user})).scalar_one())


async def cert_id(owner_engine: AsyncEngine, world: World) -> str:
    async with owner_engine.connect() as conn:
        found = await conn.execute(text("SELECT cert_id FROM proposal_versions WHERE id = :v"), {"v": world.version})
        return str(found.scalar_one())


async def approve(owner_engine: AsyncEngine, app_engine: AsyncEngine, world: World, today: date) -> UUID:
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    async with seats(app_engine, deals_on(), world) as s:
        await walk_to(t, s, world, today, "INTEREST_CONFIRMED")
    return engagement


def eat(day: date) -> str:
    return f"{day.day} {day:%b %Y}"


async def test_em2_is_sent_once_with_the_spec_copy(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    today = await db_today(owner_engine)
    engagement = await approve(owner_engine, app_engine, world, today)
    provider = FakeEmailProvider()
    assert await run_notifications(owner_engine, app_engine, engagement, provider, keep=True) == 2  # N03, N04
    await run_notifications(owner_engine, app_engine, engagement, provider)  # a retried job sends nothing more
    [message] = provider.outbox
    assert message.to == world.developer_email
    assert message.subject == f'Good news: {world.org_name} approved "{PROPOSAL_TITLE}" to proceed (non-binding)'
    contact = await display_name(owner_engine, world.owner)
    for part in (message.text, message.html or ""):
        assert "will contact you shortly to agree on pursuing the project" in part
        assert "not a contract or a commitment to buy" in part
        assert f"Your contact: {contact}, Owner, via phone before" in part
        assert eat(today) in part
        assert await cert_id(owner_engine, world) in part
        assert "Your full proposal has not been shared yet." in part
        assert f"/dev/engagements/{engagement}" in part  # the developer's own tracker
        assert "Public bodies may need to run a competitive process" not in part
    assert message.text.count("Open your tracker") == 1
    assert (message.html or "").count("<a href") == 3  # one CTA, and the footer's two links
    async with owner_engine.connect() as conn:
        sent = (
            await conn.execute(
                text("SELECT count(*) FROM notification_deliveries WHERE dedupe_key = :k AND status = 'sent'"),
                {"k": f"em2:{engagement}"},
            )
        ).scalar_one()
        in_app = (
            await conn.execute(
                text("SELECT count(*) FROM in_app_notifications WHERE user_id = :u AND kind = 'engagement.n04'"),
                {"u": world.developer},
            )
        ).scalar_one()
    assert (sent, in_app) == (1, 1)
    assert await notification_jobs(owner_engine, engagement) == []


async def test_tier2_status_counts_the_named_people_who_viewed_under_nda(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """``tier2_status`` from the access log and the grants; a public entity gets the procurement sentence."""
    world = await build(owner_engine, public_entity=True)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO disclosure_grants (id, proposal_id, org_id, owner_id, tier, status, source)"
                " VALUES (:id, :p, :o, :d, 2, 'active', 'auto_tagged')"
            ),
            {"id": uuid7(), "p": world.proposal, "o": world.org, "d": world.developer},
        )
        for _ in range(2):  # two views by the same person count once
            await conn.execute(
                text(
                    "INSERT INTO document_views (id, proposal_id, version_id, owner_id, viewer_user_id, org_id,"
                    " render_kind, fingerprint_seed) VALUES (:id, :p, :v, :d, :viewer, :o, 'html', '\\x00')"
                ),
                {
                    "id": uuid7(),
                    "p": world.proposal,
                    "v": world.version,
                    "d": world.developer,
                    "viewer": world.reviewer,
                    "o": world.org,
                },
            )
    engagement = await approve(owner_engine, app_engine, world, await db_today(owner_engine))
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, engagement, provider)
    [message] = provider.outbox
    assert (
        f"1 named, verified person at {world.org_name} has viewed your full proposal under NDA (see Who has seen"
        " this)." in message.text
    )
    assert "Public bodies may need to run a competitive process, and you may be asked to bid." in message.text


async def test_contact_details_reach_only_the_named_contact_after_approval(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        for client in (s.owner, s.signatory, s.dev):
            before = await client.get(t.path("/contact"))
            assert before.status_code == 403
        await walk_to(t, s, world, today, "UNDER_REVIEW")
        assert (await s.owner.get(t.path("/contact"))).status_code == 403
        await walk_to(t, s, world, today, "INTEREST_CONFIRMED")  # the signatory names the owner as contact
        revealed = await s.owner.get(t.path("/contact"))
        assert revealed.status_code == 200
        assert revealed.json()["email"] == world.developer_email
        assert revealed.json()["phone"] is None
        other = await s.signatory.get(t.path("/contact"))
        assert (other.status_code, other.json()["detail"]["code"]) == (403, "not_the_contact")
        assert (await s.dev.get(t.path("/contact"))).status_code == 403
        await t.ok(s.dev, "withdraw")
        ended = await s.owner.get(t.path("/contact"))
        assert (ended.status_code, ended.json()["detail"]["code"]) == (403, "contact_not_revealed")
    async with clients(app_engine, deals_on(), world.outsider) as (outsider,):
        assert (await outsider.get(t.path("/contact"))).status_code == 404
    async with owner_engine.connect() as conn:
        reveals = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM audit_events WHERE action = 'engagement.contact_revealed'"
                    " AND subject_id = :e AND actor_user_id = :u"
                ),
                {"e": engagement, "u": world.owner},
            )
        ).scalar_one()
    assert reveals == 1
