"""REQ-NOT-05 (P28 track B): the nudge job's edges.

- One engagement's failure is logged and reported, and never stops the run; the next run retries it.
- An engagement that ended meanwhile is not nudged; nothing is recorded for it.
- Telling: an unknown engagement is skipped, a recipient who left the organisation is skipped, the engagement's
  developer is never told as the organisation's, a person without a verified email address gets the bell only.
- An ended engagement's organisation tracker carries no escalation.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import create_session_factory
from bridge.engagements import nudges
from bridge.engagements.policy import get_policy
from bridge.engagements.service import all_holidays, app_now
from bridge.ids import uuid7
from bridge.models.enums import NudgeKind
from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import (
    Tracker,
    build,
    business_days_later,
    db_today,
    deals_on,
    moved_clock,
    open_engagement,
    run,
    seats,
)

SETTINGS = deals_on()


async def overdue(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> tuple[Any, Tracker]:
    """A world whose engagement is in stage 3 with today's contact-by date (the caller moves the clock)."""
    world = await build(owner_engine)
    async with seats(app_engine, SETTINGS, world) as s:
        today = await db_today(owner_engine)
        t = Tracker(await open_engagement(app_engine, world))
        await t.ok(s.reviewer, "start-review")
        body = {"contact_user_id": str(world.owner), "contact_channel": "phone", "contact_by": str(today)}
        await t.ok(s.signatory, "approve", body)
    return world, t


async def test_a_failing_engagement_is_reported_and_retried(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, t = await overdue(owner_engine, app_engine)
    factory = create_session_factory(app_engine)
    async with moved_clock(owner_engine) as advance:
        await business_days_later(owner_engine, advance, 1)
        real = nudges.nudge_one

        async def broken(*args: Any, **kwargs: Any) -> list[nudges.Sent]:
            raise RuntimeError("boom")

        monkeypatch.setattr(nudges, "nudge_one", broken)
        failed = await nudges.run_nudges(factory, engagement_ids={t.engagement})
        assert (failed.sent, failed.failed) == ((), (t.engagement,))
        monkeypatch.setattr(nudges, "nudge_one", real)
        retried = await nudges.run_nudges(factory, engagement_ids={t.engagement})
        assert [n.kind for n in retried.sent] == [NudgeKind.CONTACT_OVERDUE]
        assert retried.of(t.engagement) == list(retried.sent)


async def test_an_ended_engagement_is_not_nudged(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world, t = await overdue(owner_engine, app_engine)
    async with seats(app_engine, SETTINGS, world) as s, moved_clock(owner_engine) as advance:
        await t.ok(s.dev, "withdraw")
        await business_days_later(owner_engine, advance, 1)
        factory = create_session_factory(app_engine)
        async with factory() as db:
            now = await app_now(db)
            holidays = await all_holidays(db)
            sent = await nudges.nudge_one(
                db,
                engagement_id=t.engagement,
                developer_id=world.developer,
                member_id=world.owner,
                now=now,
                holidays=holidays,
                policy=get_policy(),
            )
            await db.commit()
        assert sent == []
        report = await nudges.run_nudges(factory, engagement_ids={t.engagement})
        assert report.sent == ()  # no longer a candidate
        org = await t.detail(s.owner)
        assert (org["state"], org["escalated_at"]) == ("WITHDRAWN", None)
    async with owner_engine.connect() as conn:
        assert await run(conn, "SELECT count(*) FROM engagement_nudges WHERE engagement_id = :e", e=t.engagement) == 0


async def test_telling_skips_whom_it_must(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """An unknown engagement tells nobody; a recipient who left, and the developer named as the organisation's, are
    skipped; an unverified address gets the bell only."""
    world, t = await overdue(owner_engine, app_engine)
    factory = create_session_factory(app_engine)
    provider = FakeEmailProvider()
    args: dict[str, Any] = {
        "kind": NudgeKind.CONTACT_OVERDUE.value,
        "key": "e2:2026-10-09",
        "developer": True,
        "on": "2026-10-09",
        "expires": "2026-10-19",
    }
    assert await nudges.deliver(
        factory, provider, SETTINGS, engagement_id=uuid7(), developer_id=world.developer, org_recipients=[], **args
    )
    async with owner_engine.begin() as conn:
        await run(conn, "UPDATE memberships SET status = 'removed' WHERE user_id = :u", u=world.finance)
        await run(conn, "UPDATE users SET email_verified_at = NULL WHERE id = :u", u=world.developer)
    recipients = [str(world.finance), str(world.developer), str(world.owner)]
    done = await nudges.deliver(
        factory,
        provider,
        SETTINGS,
        engagement_id=t.engagement,
        developer_id=world.developer,
        org_recipients=recipients,
        **args,
    )
    assert done
    async with owner_engine.connect() as conn:
        told = await run(
            conn,
            "SELECT array_agg(user_id ORDER BY user_id) FROM in_app_notifications WHERE kind = 'engagement.n05'"
            " AND link LIKE :l",
            l=f"%/engagements/{t.engagement}",
        )
    assert sorted(told) == sorted([world.owner, world.developer])  # the developer once, as the developer
    assert len(provider.outbox) == 1  # the owner's: the developer's address is not verified


async def test_a_nudge_for_a_deleted_copy_is_refused(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """A notice with no copy for its side tells nobody (an escalation has no developer version)."""
    world, t = await overdue(owner_engine, app_engine)
    factory = create_session_factory(app_engine)
    provider = FakeEmailProvider()
    done = await nudges.deliver(
        factory,
        provider,
        SETTINGS,
        engagement_id=t.engagement,
        developer_id=world.developer,
        kind=NudgeKind.CONTACT_ESCALATION.value,
        key="e2:bd3",
        org_recipients=[],
        developer=True,
        days=3,
        on="2026-10-09",
    )
    assert done
    assert provider.outbox == []
    async with owner_engine.connect() as conn:
        assert (
            await run(
                conn,
                "SELECT count(*) FROM in_app_notifications WHERE user_id = :u AND kind = 'engagement.n05'",
                u=world.developer,
            )
            == 0
        )


async def test_the_job_tells_nobody_when_the_organisation_has_no_member_to_read_its_roster(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Without a member to bind (``member_id`` NULL), the organisation's side is empty: an escalation is recorded and
    queues nothing; EM6 still reaches the developer."""
    world, t = await overdue(owner_engine, app_engine)
    factory = create_session_factory(app_engine)
    async with moved_clock(owner_engine) as advance:
        await business_days_later(owner_engine, advance, 4)
        async with factory() as db:
            sent = await nudges.nudge_one(
                db,
                engagement_id=t.engagement,
                developer_id=world.developer,
                member_id=None,
                now=await app_now(db),
                holidays=await all_holidays(db),
                policy=get_policy(),
            )
            await db.commit()
    assert [(n.kind, n.org_recipients, n.developer) for n in sent] == [
        (NudgeKind.CONTACT_ESCALATION, 0, False),
        (NudgeKind.CONTACT_OVERDUE, 0, True),
    ]
    async with owner_engine.connect() as conn:
        queued = await run(
            conn,
            "SELECT count(*) FROM procrastinate_jobs WHERE task_name = :t AND args->>'engagement_id' = :e",
            t=nudges.TASK,
            e=str(t.engagement),
        )
    assert queued == 1  # EM6 for the developer only


async def test_a_command_committed_while_the_job_decides_records_and_sends_nothing(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The job records a nudge only in the state it decided it in (``app_record_nudge``'s expected state): the
    organisation marks first contact between the job's read of an overdue stage 3 and its record, so EM6 is neither
    recorded nor queued."""
    world, t = await overdue(owner_engine, app_engine)
    factory = create_session_factory(app_engine)
    real = nudges.roster_of
    async with seats(app_engine, SETTINGS, world) as s, moved_clock(owner_engine) as advance:
        await business_days_later(owner_engine, advance, 1)

        async def meanwhile(db: Any, engagement: Any) -> nudges.Roster:
            await t.ok(s.owner, "mark-contacted")  # its own request and transaction, committed
            return await real(db, engagement)

        monkeypatch.setattr(nudges, "roster_of", meanwhile)
        report = await nudges.run_nudges(factory, engagement_ids={t.engagement})
        assert (report.sent, report.failed) == ((), ())
        assert (await t.detail(s.owner))["state"] == "CONTACT_MADE"
    async with owner_engine.connect() as conn:
        assert await run(conn, "SELECT count(*) FROM engagement_nudges WHERE engagement_id = :e", e=t.engagement) == 0
        queued = await run(
            conn,
            "SELECT count(*) FROM procrastinate_jobs WHERE task_name = :t AND args->>'engagement_id' = :e",
            t=nudges.TASK,
            e=str(t.engagement),
        )
    assert queued == 0
