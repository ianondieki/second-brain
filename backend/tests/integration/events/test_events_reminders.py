"""REQ-DEV-02 (D-61; P22 card B test B4; ``REQUIREMENTS.md`` §5 N26, N27): the reminder job on the shared clock.

An event on Wednesday 18:00 to 20:00 in Nairobi that a developer asked to be reminded of: at 17:59 on Tuesday nothing,
at 18:00 one email (N26, "Tomorrow: ..."), at 18:15 nothing more; at 07:59 on Wednesday nothing, at 08:00 one in-app
notice (N27, "Today at 18:00 · ..."), once. No email without the reminders consent or with an unverified address,
while the in-app notice still comes; nothing after Decline or after ``app_cancel_event``; a reminder made on the day
itself gets the notice, never a "Tomorrow" email; the job is silent when nothing is due; wired as the worker wires it.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from bridge.config import get_settings
from bridge.db import bind_tenant, create_session_factory
from bridge.events.reminders import Deps, EventReminderRuntime, run_event_reminders
from bridge.notifications.email import FakeEmailProvider
from tests.integration.events.api_world import (
    NAIROBI_CITY,
    People,
    WeekDb,
    at,
    cancel,
    cast,
    consent,
    nairobi,
    owner_rows,
    owner_run,
    published,
)
from tests.unit.events.test_reminders import decoded_links

EVENT_START = time(18, 0)


def deps(week: WeekDb, mail: FakeEmailProvider) -> Deps:
    return Deps(create_session_factory(week.app), get_settings(), mail)


async def remind(week: WeekDb, user: UUID, event_id: UUID) -> None:
    """Remind me, as the developer (the reminder's INSERT policy)."""
    async with create_session_factory(week.app)() as session:
        await bind_tenant(session, user_id=user)
        await session.execute(
            text("INSERT INTO event_reminders (user_id, event_id) VALUES (:u, :e)"), {"u": user, "e": event_id}
        )
        await session.commit()


async def notices(week: WeekDb, user: UUID) -> list[Any]:
    return await owner_rows(
        week, "SELECT kind, title, body, link FROM in_app_notifications WHERE user_id = :u ORDER BY created_at", u=user
    )


async def scene(week: WeekDb) -> tuple[People, UUID, Any]:
    """Monday noon: Wednesday's event, published, and the developer's reminder on it."""
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    wednesday = monday + timedelta(days=2)
    event_id = await published(week, p, nairobi(wednesday, EVENT_START), county=NAIROBI_CITY, title="Rust night")
    await remind(week, p.developer, event_id)
    return p, event_id, monday


async def test_one_email_the_day_before_and_one_notice_the_morning_of(week: WeekDb) -> None:
    p, event_id, monday = await scene(week)
    tuesday, wednesday = monday + timedelta(days=1), monday + timedelta(days=2)
    mail = FakeEmailProvider()
    await at(week, tuesday, time(17, 59))
    first = await run_event_reminders(deps(week, mail))
    assert (first.due, mail.outbox) == (1, [])  # due today or tomorrow, but not yet
    await at(week, tuesday, time(18, 0))
    await run_event_reminders(deps(week, mail))
    [email] = mail.outbox
    [address] = await owner_rows(week, "SELECT email FROM users WHERE id = :u", u=p.developer)
    assert (email.to, email.subject, email.tag) == (address.email, "Tomorrow: Rust night", "n26")
    assert "Wednesday" in email.text
    assert "18:00 to 20:00 (Nairobi time)" in email.text
    assert "iHub, Senteu Plaza, Nairobi City" in email.text
    assert f"/api/events/{event_id}/calendar.ics" in email.text
    assert "https://calendar.google.com/calendar/render?action=TEMPLATE" in email.text
    for body in (email.text, email.html or ""):  # never the description, in the text or in any link's query
        assert "Talks and a workshop" not in body
        for link, query in decoded_links(body):
            assert "Talks and a workshop" not in link + " ".join(v for values in query.values() for v in values)
            assert "details" not in query
    await at(week, tuesday, time(18, 15))
    await run_event_reminders(deps(week, mail))
    assert len(mail.outbox) == 1
    await at(week, wednesday, time(7, 59))
    await run_event_reminders(deps(week, mail))
    assert await notices(week, p.developer) == []
    await at(week, wednesday, time(8, 0))
    await run_event_reminders(deps(week, mail))
    await at(week, wednesday, time(8, 15))
    await run_event_reminders(deps(week, mail))
    [notice] = await notices(week, p.developer)
    body = "Today at 18:00 · iHub, Senteu Plaza, Nairobi City"
    assert tuple(notice) == ("n27", "Rust night", body, f"/dev/events/{event_id}")
    assert len(mail.outbox) == 1
    deliveries = await owner_rows(
        week,
        "SELECT kind, channel::text AS channel, status::text AS status, dedupe_key FROM notification_deliveries"
        " WHERE user_id = :u ORDER BY created_at",
        u=p.developer,
    )
    assert [tuple(d) for d in deliveries] == [
        ("n26", "email", "sent", f"n26:email:{p.developer}:{event_id}"),
        ("n27", "in_app", "sent", f"n27:in_app:{p.developer}:{event_id}"),
    ]


async def test_no_email_without_the_consent_or_a_verified_address_but_the_notice_comes(week: WeekDb) -> None:
    p, event_id, monday = await scene(week)
    await remind(week, p.other, event_id)
    async with week.owner.begin() as conn:
        await consent(conn, p.developer, granted=False)
    await owner_run(week, "UPDATE users SET email_verified_at = NULL WHERE id = :u", u=p.other)
    mail = FakeEmailProvider()
    await at(week, monday + timedelta(days=1), time(18, 30))
    report = await run_event_reminders(deps(week, mail))
    assert mail.outbox == []
    assert sorted((o.user_id == p.developer, o.status) for o in report.outcomes) == [
        (False, "unverified"),
        (True, "no_consent"),
    ]
    await at(week, monday + timedelta(days=2), time(9, 0))
    await run_event_reminders(deps(week, mail))
    assert [n.kind for n in await notices(week, p.developer)] == ["n27"]
    assert [n.kind for n in await notices(week, p.other)] == ["n27"]
    assert mail.outbox == []


async def test_nothing_after_decline_or_cancellation(week: WeekDb) -> None:
    p, event_id, monday = await scene(week)
    other_event = await published(
        week, p, nairobi(monday + timedelta(days=2), time(19, 0)), county=NAIROBI_CITY, title="Go night"
    )
    await remind(week, p.developer, other_event)
    async with create_session_factory(week.app)() as session:  # Decline the first
        await bind_tenant(session, user_id=p.developer)
        await session.execute(text("DELETE FROM event_reminders WHERE event_id = :e"), {"e": event_id})
        await session.commit()
    await cancel(week, other_event, p.org.owner)  # the organisation cancels the second
    mail = FakeEmailProvider()
    for day, clock in ((1, time(18, 0)), (2, time(8, 0)), (2, time(12, 0))):
        await at(week, monday + timedelta(days=day), clock)
        assert (await run_event_reminders(deps(week, mail))).due == 0  # neither is listed
    assert mail.outbox == []
    assert await notices(week, p.developer) == []
    assert await owner_rows(week, "SELECT 1 FROM notification_deliveries WHERE user_id = :u", u=p.developer) == []


async def test_a_reminder_made_on_the_day_gets_the_notice_never_a_tomorrow_email(week: WeekDb) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    event_id = await published(week, p, nairobi(monday + timedelta(days=1), time(18, 0)))  # Tuesday, online
    await at(week, monday + timedelta(days=1), time(10, 0))
    await remind(week, p.developer, event_id)
    mail = FakeEmailProvider()
    await run_event_reminders(deps(week, mail))
    assert mail.outbox == []
    [notice] = await notices(week, p.developer)
    assert (notice.kind, notice.body) == ("n27", "Today at 18:00 · Online")
    await at(week, monday + timedelta(days=1), time(20, 0))  # ended: not due any more
    assert (await run_event_reminders(deps(week, mail))).due == 0


async def test_the_job_is_silent_when_nothing_is_due_and_runs_as_the_worker_wires_it(week: WeekDb) -> None:
    monday = week.monday()
    await at(week, monday, time(18, 0))
    p = await cast(week)
    mail = FakeEmailProvider()
    quiet = await run_event_reminders(deps(week, mail))
    assert (quiet.due, quiet.outcomes, mail.attempts) == (0, (), 0)
    event_id = await published(week, p, nairobi(monday + timedelta(days=1), time(9, 0)), county=NAIROBI_CITY)
    await remind(week, p.developer, event_id)
    runtime = EventReminderRuntime(get_settings(), factory=create_session_factory(week.app), email=mail)
    report = await run_event_reminders(runtime.deps())
    assert [(o.kind, o.status) for o in report.outcomes] == [("n26", "sent")]
    assert len(mail.outbox) == 1
