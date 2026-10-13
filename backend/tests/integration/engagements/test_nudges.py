"""REQ-NOT-05, REQ-NOT-03, REQ-ENG-05 (P28 track B; AT-B-1, AT-B-2, AT-B-3; AC-MAIL-2): the nudge job on the shared
test clock, through the tracker API.

- AT-B-1: past +3 business days in INTEREST_CONFIRMED, one pass sends the escalation once to the admins and the
  escalation contact (in-app; email unless the person turned it off); a second pass sends nothing; a hold in between
  delays it by the business days paused.
- AT-B-2: a missed contact-by date sends EM6 to both sides (two versions) and sets ``escalated_at`` on the
  organisation's tracker only, never the developer's; the +10 BD expiry still ends the engagement, and nothing is
  nudged after.
- AT-B-3: the NDA reminders reach only the signers who have not signed, at 2 and 4 business days; the reminder is EM5
  (🔒: a preference does not stop it), while an escalation's email follows the person's preference.
- A milestone under review is reminded to the organisation's reviewers of the engagement (in-app) and escalated to its
  admins.

The job runs over this test's engagements only (``engagement_ids``): other tests' engagements share the database.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import create_session_factory
from bridge.engagements import nudges
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import add_business_days, local_date
from bridge.engagements.expiry import run_expiry
from bridge.engagements.nudges import NudgeReport, run_nudges
from bridge.models.enums import NudgeKind
from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import (
    Seats,
    Tracker,
    World,
    build,
    business_days_later,
    db_today,
    deals_on,
    holidays_of,
    moved_clock,
    open_engagement,
    run,
    seats,
    walk_to,
)

K = NudgeKind
SETTINGS = deals_on()


async def nudge(app_engine: AsyncEngine, t: Tracker, now: datetime | None = None) -> NudgeReport:
    """One pass of the job over this engagement (on the shared clock unless ``now`` is given)."""
    report = await run_nudges(create_session_factory(app_engine), now=now, engagement_ids={t.engagement})
    assert report.failed == ()
    return report


async def tell(owner_engine: AsyncEngine, app_engine: AsyncEngine, t: Tracker, provider: FakeEmailProvider) -> int:
    """Run the engagement's queued nudge notifications as the worker would, then delete them."""
    async with owner_engine.connect() as conn:
        jobs = (
            await conn.execute(
                text(
                    "SELECT id, args FROM procrastinate_jobs WHERE task_name = :t AND args->>'engagement_id' = :e"
                    " ORDER BY id"
                ),
                {"t": nudges.TASK, "e": str(t.engagement)},
            )
        ).all()
    factory = create_session_factory(app_engine)
    for _, args in jobs:
        values = dict(args)
        done = await nudges.deliver(
            factory,
            provider,
            SETTINGS,
            engagement_id=UUID(values.pop("engagement_id")),
            developer_id=UUID(values.pop("developer_id")),
            **values,
        )
        assert done
    if jobs:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM procrastinate_jobs WHERE id = ANY(:ids)"), {"ids": [j for j, _ in jobs]}
            )
    return len(jobs)


async def bell(owner_engine: AsyncEngine, t: Tracker, kind: str) -> dict[UUID, list[str]]:
    """Each user's in-app notices of ``kind`` about the engagement: their titles."""
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT user_id, title FROM in_app_notifications WHERE kind = :k AND link LIKE :l ORDER BY created_at"
            ),
            {"k": kind, "l": f"%/engagements/{t.engagement}"},
        )
        told: dict[UUID, list[str]] = {}
        for user, title in rows.tuples():
            told.setdefault(user, []).append(title)
        return told


async def emails_of(owner_engine: AsyncEngine, *users: UUID) -> dict[str, UUID]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(text("SELECT email, id FROM users WHERE id = ANY(:u)"), {"u": list(users)})
        return {str(email): user for email, user in rows.tuples()}


async def escalation_contact(owner_engine: AsyncEngine, world: World, user: UUID) -> None:
    async with owner_engine.begin() as conn:
        await run(conn, "UPDATE organizations SET escalation_contact_user_id = :u WHERE id = :o", u=user, o=world.org)


async def mute(owner_engine: AsyncEngine, user: UUID, kind: str) -> None:
    """The person turned the email of ``kind`` off (a row of their preferences)."""
    async with owner_engine.begin() as conn:
        await run(
            conn,
            "INSERT INTO notification_preferences (user_id, kind, channel, enabled) VALUES (:u, :k, 'email', false)",
            u=user,
            k=kind,
        )


async def confirmed(app_engine: AsyncEngine, world: World, s: Seats, contact_by: date) -> Tracker:
    """Approved to proceed (stage 3), the owner named as the contact, by ``contact_by``."""
    t = Tracker(await open_engagement(app_engine, world))
    await t.ok(s.reviewer, "start-review")
    body = {"contact_user_id": str(world.owner), "contact_channel": "phone", "contact_by": str(contact_by)}
    detail = await t.ok(s.signatory, "approve", body)
    assert detail["state"] == "INTEREST_CONFIRMED"
    return t


async def test_the_contact_escalation_is_sent_once_after_three_business_days(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AT-B-1: Given stage 3 with a contact-by date 5 business days ahead and an escalation contact who turned the
    escalation emails off, When the clock passes +3 BD and the job runs, Then the owner (admin) and the escalation
    contact are told in-app once, only the owner by email; a second pass sends nothing; the organisation's tracker
    shows the escalation, the developer's never."""
    world = await build(owner_engine)
    await escalation_contact(owner_engine, world, world.reviewer)
    await mute(owner_engine, world.reviewer, "engagement.n05")
    provider = FakeEmailProvider()
    off = await holidays_of(owner_engine)
    async with seats(app_engine, SETTINGS, world) as s, moved_clock(owner_engine) as advance:
        today = await db_today(owner_engine)
        t = await confirmed(app_engine, world, s, add_business_days(today, 5, off))
        entered = local_date(datetime.fromisoformat((await t.detail(s.owner))["stage_entered_at"]))
        assert entered == today
        third = add_business_days(entered, 3, off)
        assert (await nudge(app_engine, t, now=sm.end_of_day(third))).sent == ()  # not before the 3rd BD has ended
        await business_days_later(owner_engine, advance, 4)
        first = await nudge(app_engine, t)
        assert [(n.kind, n.key, n.org_recipients, n.developer) for n in first.sent] == [
            (K.CONTACT_ESCALATION, first.sent[0].key, 2, False)
        ]
        assert first.sent[0].key.endswith(":bd3")
        assert (await nudge(app_engine, t)).sent == ()  # once
        assert await tell(owner_engine, app_engine, t, provider) == 1
        told = await bell(owner_engine, t, "engagement.n05")
        assert told == {world.owner: ["First contact is late"], world.reviewer: ["First contact is late"]}
        addresses = await emails_of(owner_engine, world.owner, world.reviewer, world.developer)
        assert [addresses[m.to] for m in provider.outbox] == [world.owner]  # the reviewer muted it (mutable)
        [email] = provider.outbox
        assert email.subject == 'Escalation: first contact on "RLS proposal" is late'
        assert (email.tag, "3 business days" in email.text) == ("escalation", True)
        assert await tell(owner_engine, app_engine, t, provider) == 0
        org = await t.detail(s.owner)
        assert org["escalated_at"] is not None
        assert "escalated_at" not in await t.detail(s.dev)


async def test_a_hold_delays_the_escalation_by_the_business_days_paused(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AT-B-1's last clause: held for two business days, the escalation is not due on the day it would have been,
    and is due two business days later."""
    world = await build(owner_engine)
    off = await holidays_of(owner_engine)
    async with seats(app_engine, SETTINGS, world) as s, moved_clock(owner_engine) as advance:
        today = await db_today(owner_engine)
        t = await confirmed(app_engine, world, s, add_business_days(today, 5, off))
        hold = {"reason": "Budget sign-off", "resume_at": str(add_business_days(today, 9, off))}
        held = await t.ok(s.owner, "pause", hold)
        assert held["state"] == "ON_HOLD"
        await business_days_later(owner_engine, advance, 2)
        assert (await nudge(app_engine, t)).sent == ()  # on hold: not a candidate
        resumed = await t.ok(s.owner, "resume", {"reason": "Budget approved"})
        assert resumed["state"] == "INTEREST_CONFIRMED"
        await business_days_later(owner_engine, advance, 2)  # 4 BD after entry: due without the hold
        assert (await nudge(app_engine, t)).sent == ()
        await business_days_later(owner_engine, advance, 2)  # 6 BD after entry: 3 + the 2 paused have run out
        assert [n.kind for n in (await nudge(app_engine, t)).sent] == [K.CONTACT_ESCALATION]


async def test_a_missed_contact_by_date_sends_em6_to_both_sides_and_flags_the_admins(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AT-B-2 (AC-MAIL-2's first clause): Given stage 3 with today's contact-by date, When the date has passed and the
    job runs, Then EM6 reaches the named contact (the owner, an admin) in its organisation version and the developer
    in theirs, each once; the organisation's tracker shows when it was escalated and the developer's does not carry
    the field; at +10 BD the expiry job still ends the engagement (CONTACT_NOT_MADE) and the job nudges nothing more."""
    world = await build(owner_engine)
    provider = FakeEmailProvider()
    off = await holidays_of(owner_engine)
    async with seats(app_engine, SETTINGS, world) as s, moved_clock(owner_engine) as advance:
        today = await db_today(owner_engine)
        t = await confirmed(app_engine, world, s, today)
        assert (await nudge(app_engine, t)).sent == ()
        await business_days_later(owner_engine, advance, 1)
        report = await nudge(app_engine, t)
        assert [(n.kind, n.key, n.org_recipients, n.developer) for n in report.sent] == [
            (K.CONTACT_OVERDUE, report.sent[0].key, 1, True)
        ]
        assert report.sent[0].key.endswith(f":{today.isoformat()}")
        assert (await nudge(app_engine, t)).sent == ()
        assert await tell(owner_engine, app_engine, t, provider) == 1
        addresses = await emails_of(owner_engine, world.owner, world.developer)
        by_person = {addresses[m.to]: m for m in provider.outbox}
        assert set(by_person) == {world.owner, world.developer}
        org_email, developer_email = by_person[world.owner], by_person[world.developer]
        assert org_email.subject == developer_email.subject == 'Contact overdue: "RLS proposal"'
        assert (org_email.tag, developer_email.tag) == ("em6", "em6")
        assert "first contact with the developer has not been marked" in org_email.text
        assert f"{world.org_name} said its contact would reach you" in developer_email.text
        expires = add_business_days(today, 10, off)
        for message in (org_email, developer_email):
            assert f"expires on {expires.day} {expires:%b %Y}" in message.text
        told = await bell(owner_engine, t, "engagement.n05")
        assert told == {world.owner: ["Contact overdue"], world.developer: ["Contact overdue"]}
        org = await t.detail(s.owner)
        async with owner_engine.connect() as conn:
            sent_at = await run(
                conn, "SELECT max(sent_at) FROM engagement_nudges WHERE engagement_id = :e", e=t.engagement
            )
        assert datetime.fromisoformat(org["escalated_at"]) == sent_at
        developer = await t.detail(s.dev)
        assert "escalated_at" not in developer
        assert developer["my_party"] == "developer"
        await business_days_later(owner_engine, advance, 10)
        expired = await run_expiry(create_session_factory(app_engine), user_ids=[world.developer])
        assert [o.state.value if o.state else None for o in expired.outcomes] == ["EXPIRED"]
        assert (await t.detail(s.dev))["end_reason"] == "CONTACT_NOT_MADE"
        assert (await nudge(app_engine, t)).sent == ()


async def test_nda_reminders_reach_only_the_signers_who_have_not_signed(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AT-B-3: Given NDA_PENDING signed by the developer and a signatory who turned N07's emails off, When 2 and then
    4 business days pass, Then each reminder reaches the signatory only, in-app and by email (EM5 is 🔒), once."""
    world = await build(owner_engine)
    await mute(owner_engine, world.signatory, "engagement.n07")
    provider = FakeEmailProvider()
    async with seats(app_engine, SETTINGS, world) as s, moved_clock(owner_engine) as advance:
        today = await db_today(owner_engine)
        t = Tracker(await open_engagement(app_engine, world))
        await walk_to(t, s, world, today, "NDA_PENDING")
        await t.ok(s.dev, "sign-nda")
        await business_days_later(owner_engine, advance, 1)
        assert (await nudge(app_engine, t)).sent == ()
        await business_days_later(owner_engine, advance, 2)  # past the end of the 2nd business day
        second = await nudge(app_engine, t)
        assert [(n.kind, n.org_recipients, n.developer) for n in second.sent] == [(K.NDA_REMINDER, 1, False)]
        assert second.sent[0].key.endswith(":bd2")
        await business_days_later(owner_engine, advance, 2)  # past the end of the 4th
        fourth = await nudge(app_engine, t)
        assert [n.key.split(":")[-1] for n in fourth.sent] == ["bd4"]
        assert (await nudge(app_engine, t)).sent == ()
        assert await tell(owner_engine, app_engine, t, provider) == 2
        told = await bell(owner_engine, t, "engagement.n07")
        assert told == {world.signatory: ["Signature needed", "Signature needed"]}
        addresses = await emails_of(owner_engine, world.signatory)
        assert [addresses.get(m.to) for m in provider.outbox] == [world.signatory, world.signatory]
        assert {m.tag for m in provider.outbox} == {"em5"}
        assert provider.outbox[0].subject == 'Signature needed: the mutual NDA for "RLS proposal"'


async def test_a_milestone_under_review_is_reminded_then_escalated(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """N12: a submitted milestone unreviewed 3 business days reminds the organisation's reviewers of the engagement
    (in-app only); at 5 it is escalated to the admins (in-app and email); each once per submission."""
    world = await build(owner_engine)
    provider = FakeEmailProvider()
    async with seats(app_engine, SETTINGS, world) as s, moved_clock(owner_engine) as advance:
        today = await db_today(owner_engine)
        t = Tracker(await open_engagement(app_engine, world))
        detail = await walk_to(t, s, world, today, "IN_IMPLEMENTATION")
        milestone = detail["agreements"][0]["milestones"][0]["id"]
        await t.ok(s.dev, f"milestones/{milestone}/start")
        await t.ok(s.dev, f"milestones/{milestone}/submit")
        await business_days_later(owner_engine, advance, 4)
        reminded = await nudge(app_engine, t)
        assert [(n.kind, n.key) for n in reminded.sent] == [(K.MILESTONE_REMINDER, reminded.sent[0].key)]
        assert reminded.sent[0].key.startswith(milestone)
        await business_days_later(owner_engine, advance, 2)
        escalated = await nudge(app_engine, t)
        assert [(n.kind, n.org_recipients) for n in escalated.sent] == [(K.MILESTONE_ESCALATION, 1)]
        assert await tell(owner_engine, app_engine, t, provider) == 2
        told = await bell(owner_engine, t, "engagement.n12")
        # The reminder: the members who may accept a milestone among those on the engagement (the reviewer who
        # started the review, the signatory who approved and signed, the owner who drafted and is the contact).
        assert set(told) == {world.owner, world.signatory, world.reviewer}
        assert told[world.owner] == ["Milestone review due", "Milestone review late"]
        addresses = await emails_of(owner_engine, world.owner)
        assert [addresses.get(m.to) for m in provider.outbox] == [world.owner]  # the reminder is in-app only
        org: dict[str, Any] = await t.detail(s.owner)
        assert org["escalated_at"] is not None
