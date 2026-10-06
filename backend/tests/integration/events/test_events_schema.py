"""Revision 0010 (REQ-DEV-02; P22 track B, D-60, D-61): the events' and reminders' schema rules, each test in one
rolled-back transaction.

- B2 at the database: an editor (owner, admin, signatory, reviewer) of an organisation posts a draft for it as
  themselves, a staff admin a platform draft; finance and viewer members, other organisations' editors, staff
  moderators, developers and unbound sessions cannot; nobody names the status or the decision.
- B1 at the database: a developer reads published events only, never a draft; an organisation's members read its
  events in any status and never another organisation's drafts; staff read every event; nobody reads who decided.
- Decisions: ``app_decide_event`` by staff admin or moderator, drafts only; ``app_cancel_event`` by staff or the
  organisation's editors, drafts and published events only; no other status change, for any role; only the poster's
  draft is edited.
- Reminders: a developer's own, on a published event that has not ended; deleted by Decline, never updated; nobody
  else reads them; ``app_event_reminders_due`` lists them to the reminder job only.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration.engagements import tracker as t
from tests.integration.events.schema_world import (
    CANCEL,
    DECIDE,
    DENIED,
    DUE,
    POST,
    REMIND,
    RLS,
    clock,
    county,
    decide,
    event,
    people,
    post,
    published,
    status_of,
    visible,
)


async def test_an_event_is_online_or_somewhere_short_and_its_urls_are_https(owner_engine: AsyncEngine) -> None:
    """Given an organisation's editor posting, When the event is malformed, Then its CHECK refuses it: online with a
    join URL and neither venue nor county, or at a venue in a county without a join URL; it ends after it starts and at
    most three days later; https URLs on an ASCII host without user info or whitespace (400 characters at most); a
    title of 1 to 120 characters and a description of 1 to 1,000 (line breaks allowed, other control characters not);
    a venue of 1 to 160 in a known county."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        now, kisumu = await clock(conn), await county(conn)
        starts = now + timedelta(days=2)
        here = {"online": False, "venue": "iHub, Ngong Road", "county": kisumu, "join_url": None}
        cases: tuple[tuple[dict[str, Any], str], ...] = (
            ({"venue": "iHub"}, "place_valid"),
            ({"county": kisumu}, "place_valid"),
            ({"join_url": None}, "place_valid"),
            (here | {"venue": None}, "place_valid"),
            (here | {"county": None}, "place_valid"),
            (here | {"join_url": "https://meet.example.test/x"}, "place_valid"),
            ({"ends": starts}, "span_valid"),
            ({"ends": starts - timedelta(minutes=1)}, "span_valid"),
            ({"ends": starts + timedelta(days=3, seconds=1)}, "span_valid"),
            ({"join_url": "http://meet.example.test/x"}, "join_url_valid"),
            ({"join_url": "https://user@meet.example.test/x"}, "join_url_valid"),
            ({"join_url": "https://meet.example.test/a b"}, "join_url_valid"),
            ({"join_url": "https://mëet.example.test/x"}, "join_url_valid"),
            ({"join_url": "https://meet.example.test/" + "x" * 375}, "join_url_valid"),
            ({"join_url": "https://meet.example.test/\x07"}, "join_url_valid"),
            ({"link": "ftp://files.example.test/agenda"}, "link_valid"),
            ({"link": "https://files.example.test/a\tb"}, "link_valid"),
            ({"link": "javascript:alert(1)"}, "link_valid"),
            ({"title": "t" * 121}, "title_valid"),
            ({"title": "   "}, "title_valid"),
            ({"title": "Two\nlines"}, "title_valid"),
            ({"description": "d" * 1001}, "description_valid"),
            ({"description": " \n "}, "description_valid"),
            ({"description": "A bell\x07"}, "description_valid"),
            (here | {"venue": "v" * 161}, "venue_valid"),
            (here | {"county": "XX-0000"}, "fk_events_county_code_regions"),
        )
        for overrides, constraint in cases:
            await t.expect(conn, POST, constraint, **event(p.org, p.reviewer, now, **overrides))
        await t.act(conn, p.reviewer, p.org)
        accepted = (
            here | {"ends": starts + timedelta(days=3), "link": "https://events.example.test:8443/agenda?day=1#top"},
            {"description": "Line one.\r\n\tLine two.", "title": "t" * 120, "join_url": "https://m.example.test"},
        )
        for overrides in accepted:
            await t.run(conn, POST, **event(p.org, p.reviewer, now, **overrides))


async def test_editors_and_staff_admins_post_drafts_and_nobody_else_does(owner_engine: AsyncEngine) -> None:
    """B2: each editor role of the organisation posts a draft for it as themselves (status, decision and times are the
    database's); a staff admin posts a platform draft; finance and viewer members, another organisation's editor, an
    editor for another organisation or in another's name or context, a staff moderator, a staff admin for an
    organisation, developers and an unbound session are refused by the policy; nobody names the status, the decision
    or the times."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        now = await clock(conn)
        for editor in (p.owner, p.signatory, p.reviewer):
            event_id = await post(conn, p.org, editor, now)
            returned = await conn.execute(
                sa.text("SELECT status, created_by FROM events WHERE id = :id"), {"id": event_id}
            )
            assert tuple(returned.one()) == ("draft", editor)
        await t.act(conn, p.reviewer)  # no organisation context: the membership alone decides
        await t.run(conn, POST, **event(p.org, p.reviewer, now))
        platform = await post(conn, None, p.admin, now)
        assert (await status_of(conn, platform)).status == "draft"
        refused: tuple[tuple[UUID | None, UUID | None, dict[str, Any]], ...] = (
            (p.finance, p.org, event(p.org, p.finance, now)),
            (p.viewer, p.org, event(p.org, p.viewer, now)),
            (p.other_editor, p.other_org, event(p.org, p.other_editor, now)),
            (p.reviewer, p.org, event(p.other_org, p.reviewer, now)),
            (p.reviewer, p.org, event(p.org, p.owner, now)),  # in another member's name
            (p.reviewer, p.other_org, event(p.org, p.reviewer, now)),  # another organisation's context
            (p.reviewer, p.org, event(None, p.reviewer, now)),  # an editor posts for the platform
            (p.moderator, None, event(None, p.moderator, now)),
            (p.admin, None, event(p.org, p.admin, now)),
            (p.developer, None, event(None, p.developer, now)),
            (p.developer, None, event(p.org, p.developer, now)),
            (None, None, event(None, p.admin, now)),
        )
        for user, org, params in refused:
            await t.act(conn, user, org)
            await t.expect(conn, POST, RLS, **params)
        await t.act(conn, p.reviewer, p.org)
        for column, value in (
            ("status", "'published'"),
            ("decided_by", ":by"),
            ("decided_at", "now()"),
            ("cancelled_at", "now()"),
            ("created_at", "now()"),
            ("updated_at", "now()"),
        ):
            named = POST.replace(", link)", f", link, {column})").replace(", :link)", f", :link, {value})")
            await t.expect(conn, named, DENIED, **event(p.org, p.reviewer, now))


async def test_developers_read_published_events_and_members_their_organisations(owner_engine: AsyncEngine) -> None:
    """B1: a developer reads the published events (organisations' and the platform's) and no draft, rejected or
    cancelled one; an organisation's member (a viewer included) reads its events in any status and none of another
    organisation's, nor the platform's; a forged organisation context shows nothing more; staff admin and moderator
    read every event; an unbound session reads none; nobody reads who decided."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        now = await clock(conn)
        ours_draft = await post(conn, p.org, p.reviewer, now)
        ours_published = await published(conn, p, now)
        ours_rejected = await post(conn, p.org, p.owner, now)
        await decide(conn, p.admin, ours_rejected, "reject")
        ours_cancelled = await published(conn, p, now)
        await t.act(conn, p.owner, p.org)
        await t.run(conn, CANCEL, event=ours_cancelled)
        theirs_draft = await post(conn, p.other_org, p.other_editor, now)
        theirs_published = await post(conn, p.other_org, p.other_editor, now)
        await decide(conn, p.moderator, theirs_published)
        platform_draft = await post(conn, None, p.admin, now)
        platform_published = await post(conn, None, p.admin, now)
        await decide(conn, p.admin, platform_published)
        ours = {ours_draft, ours_published, ours_rejected, ours_cancelled}
        every = [*ours, theirs_draft, theirs_published, platform_draft, platform_published]
        public = {ours_published, theirs_published, platform_published}
        for reader in (p.developer, p.other):
            assert await visible(conn, reader, every) == public
        for reader in (p.viewer, p.finance, p.reviewer):
            assert await visible(conn, reader, every, p.org) == ours
            assert await visible(conn, reader, every) == ours
            assert await visible(conn, reader, every, p.other_org) == set()  # forged: not a member there
        assert await visible(conn, p.other_editor, every, p.other_org) == {theirs_draft, theirs_published}
        for staff in (p.admin, p.moderator):
            assert await visible(conn, staff, every) == set(every)
        assert await visible(conn, None, every) == set()
        for user in (p.developer, p.viewer, p.admin):
            await t.act(conn, user)
            await t.expect(conn, "SELECT decided_by FROM events WHERE id = :id", DENIED, id=ours_published)
            await t.expect(conn, "SELECT * FROM events WHERE id = :id", DENIED, id=ours_published)
        await t.act(conn, p.developer)
        readable = "SELECT status, decided_at, cancelled_at, created_by FROM events WHERE id = :id"
        row = (await conn.execute(sa.text(readable), {"id": ours_published})).one()
        assert (row.status, row.decided_at is not None, row.cancelled_at, row.created_by) == (
            "published",
            True,
            None,
            p.reviewer,
        )


async def test_staff_decide_a_draft_once(owner_engine: AsyncEngine) -> None:
    """A staff moderator publishes a draft and a staff admin rejects one, as themselves at the shared clock; a
    developer, an organisation's editor and an unbound session are refused; a published or rejected event is never
    decided again; an unknown event and an unknown decision are refused."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        now = await clock(conn)
        first = await post(conn, p.org, p.reviewer, now)
        for user, org in ((p.developer, None), (p.owner, p.org), (p.reviewer, p.org), (None, None)):
            await t.act(conn, user, org)
            await t.expect(conn, DECIDE, "staff admin or moderator only", event=first, decision="publish")
        await t.act(conn, p.moderator)
        await t.expect(conn, DECIDE, "the decision is publish or reject", event=first, decision="published")
        await t.expect(conn, DECIDE, "the decision is publish or reject", event=first, decision=None)
        await t.expect(conn, DECIDE, "no event with that id", event=uuid7(), decision="publish")
        await t.run(conn, DECIDE, event=first, decision="publish")
        decided = await status_of(conn, first)
        assert (decided.status, decided.decided_by, decided.cancelled_at) == ("published", p.moderator, None)
        assert abs(decided.decided_at - now) < timedelta(minutes=5)  # the shared clock
        await t.act(conn, p.admin)
        await t.expect(
            conn, DECIDE, r"only a draft event is decided \(this one is published\)", event=first, decision="reject"
        )
        second = await post(conn, p.org, p.owner, now)
        await t.act(conn, p.admin)
        await t.run(conn, DECIDE, event=second, decision="reject")
        assert ((await status_of(conn, second)).status, (await status_of(conn, second)).decided_by) == (
            "rejected",
            p.admin,
        )
        await t.act(conn, p.moderator)
        await t.expect(
            conn, DECIDE, r"only a draft event is decided \(this one is rejected\)", event=second, decision="publish"
        )


async def test_an_event_that_has_ended_is_never_published(owner_engine: AsyncEngine) -> None:
    """``app_decide_event`` refuses to publish a draft whose end is at or before the shared clock ("the event is over",
    the app's 409 ``event_over``; the draft stays as it was) and still rejects it; a draft that is running or still to
    come is published."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        now = await clock(conn)
        hour = timedelta(hours=1)
        ended = await post(conn, p.org, p.reviewer, now, starts=now - 3 * hour, ends=now - timedelta(seconds=1))
        for staff in (p.moderator, p.admin):
            await t.act(conn, staff)
            await t.expect(conn, DECIDE, "the event is over, so it is never published", event=ended, decision="publish")
        assert (await status_of(conn, ended)).status == "draft"
        await decide(conn, p.moderator, ended, "reject")
        assert ((await status_of(conn, ended)).status, (await status_of(conn, ended)).decided_by) == (
            "rejected",
            p.moderator,
        )
        for starts, ends in ((now - hour, now + hour), (now + 24 * hour, now + 26 * hour)):
            event_id = await post(conn, p.org, p.reviewer, now, starts=starts, ends=ends)
            await decide(conn, p.admin, event_id)
            assert (await status_of(conn, event_id)).status == "published"


async def test_staff_and_the_organisations_editors_cancel_drafts_and_published_events(
    owner_engine: AsyncEngine,
) -> None:
    """An editor of the organisation cancels its published event (the decision stays) and its draft; staff cancel any
    event; another organisation's editor, a finance or viewer member, a developer, an editor in another organisation's
    context and an unbound session get the same refusal as for an unknown event; a cancelled or rejected event is
    never cancelled."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        now = await clock(conn)
        live = await published(conn, p, now)
        for user, org in (
            (p.other_editor, p.other_org),
            (p.finance, p.org),
            (p.viewer, p.org),
            (p.developer, None),
            (p.signatory, p.other_org),
            (None, None),
        ):
            await t.act(conn, user, org)
            await t.expect(conn, CANCEL, "no event the caller may cancel with that id", event=live)
        await t.act(conn, p.signatory, p.org)  # an editor who did not post it
        await t.expect(conn, CANCEL, "no event the caller may cancel with that id", event=uuid7())
        await t.run(conn, CANCEL, event=live)
        cancelled = await status_of(conn, live)
        assert (cancelled.status, cancelled.decided_by, cancelled.cancelled_at is not None) == (
            "cancelled",
            p.moderator,
            True,
        )
        await t.act(conn, p.owner, p.org)
        await t.expect(
            conn, CANCEL, r"only a draft or published event is cancelled \(this one is cancelled\)", event=live
        )
        draft = await post(conn, p.org, p.reviewer, now)
        await t.act(conn, p.reviewer)
        await t.run(conn, CANCEL, event=draft)
        assert (await status_of(conn, draft)).decided_by is None
        rejected = await post(conn, p.org, p.reviewer, now)
        await decide(conn, p.moderator, rejected, "reject")
        await t.act(conn, p.moderator)
        await t.expect(conn, CANCEL, r"\(this one is rejected\)", event=rejected)
        for staff in (p.moderator, p.admin):
            theirs = await post(conn, p.other_org, p.other_editor, now)
            await t.act(conn, staff)
            await t.run(conn, CANCEL, event=theirs)
            assert (await status_of(conn, theirs)).status == "cancelled"
        platform = await post(conn, None, p.admin, now)
        await decide(conn, p.admin, platform)
        await t.act(conn, p.admin)
        await t.run(conn, CANCEL, event=platform)
        assert (await status_of(conn, platform)).status == "cancelled"


async def test_no_status_moves_but_the_definers_and_only_the_posters_draft_is_edited(owner_engine: AsyncEngine) -> None:
    """bridge_app names no status, decision or cancellation column and deletes no event; the poster edits their draft's
    content (another editor of the organisation does not), a published event's content matches no row; for every role
    (the owner too) an event's organisation, poster and creation time never change, its status moves only along
    draft -> published | rejected | cancelled and published -> cancelled, a decision changes nothing else, and only a
    draft's content changes."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        now = await clock(conn)
        draft = await post(conn, p.org, p.reviewer, now)
        live = await published(conn, p, now)
        await t.act(conn, p.reviewer, p.org)
        for assignment in ("status = 'published'", "decided_at = now()", "cancelled_at = now()", "org_id = NULL"):
            await t.expect(conn, f"UPDATE events SET {assignment} WHERE id = :id", DENIED, id=draft)
        await t.expect(conn, "DELETE FROM events WHERE id = :id", DENIED, id=draft)
        edit = "UPDATE events SET title = :title, updated_at = app_clock_now() WHERE id = :id"
        assert await t.rowcount(conn, edit, title="Edited title", id=draft) == 1
        assert await t.rowcount(conn, edit, title="Edited title", id=live) == 0  # published: the policy
        await t.expect(conn, "UPDATE events SET online = false WHERE id = :id", "place_valid", id=draft)
        await t.act(conn, p.owner, p.org)  # an editor of the organisation who did not post it
        assert await t.rowcount(conn, edit, title="Not mine", id=draft) == 0
        await t.act(conn, p.developer)
        assert await t.rowcount(conn, edit, title="Not mine", id=live) == 0
        assert (await status_of(conn, draft)).title == "Edited title"
        assert (await status_of(conn, live)).title == "Nairobi Python meetup"
        platform = await post(conn, None, p.admin, now)
        assert await t.rowcount(conn, edit, title="Platform edit", id=platform) == 1
        assert await t.rowcount(conn, edit, title="Platform edit", id=draft) == 0  # an organisation's draft
        await t.as_owner(conn)
        rejected = await post(conn, p.org, p.reviewer, now)
        await decide(conn, p.moderator, rejected, "reject")
        await t.as_owner(conn)
        guard: tuple[tuple[str, UUID, str], ...] = (
            ("org_id = NULL", draft, "organisation, poster and creation time never change"),
            (f"created_by = '{p.owner}'", draft, "organisation, poster and creation time never change"),
            ("created_at = created_at - interval '1 day'", draft, "never change"),
            ("status = 'draft'", live, "moves only from draft"),
            ("status = 'published', decided_at = now(), cancelled_at = NULL", rejected, "moves only from draft"),
            ("status = 'published', decided_by = created_by, decided_at = now(), title = 'X'", draft, "nothing else"),
            ("status = 'cancelled', cancelled_at = now(), decided_at = now()", live, "nothing else"),
            ("decided_at = now()", live, "change only with the status"),
            ("cancelled_at = now()", draft, "change only with the status"),
            ("title = 'Owner edit'", live, "only a draft event is edited"),
            ("starts_at = starts_at + interval '1 hour'", rejected, "only a draft event is edited"),
            ("status = 'published'", draft, "decision_complete"),
            ("status = 'cancelled'", draft, "decision_complete"),
        )
        for assignment, event_id, match in guard:
            await t.expect(conn, f"UPDATE events SET {assignment} WHERE id = :id", match, id=event_id)
        assert await t.rowcount(conn, "UPDATE events SET title = 'Owner edit' WHERE id = :id", id=draft) == 1


async def test_a_developer_reminds_themselves_of_published_events_only(owner_engine: AsyncEngine) -> None:
    """Remind me: a developer inserts their own row on a published event that has not ended, reads it and deletes it
    (Decline); a repeat is the primary key's; a draft, rejected, cancelled or ended event, another developer's name, an
    organisation-only account and staff are refused; nobody else (another developer, the organisation's members, staff,
    an unbound session) reads it; no role updates it."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        now = await clock(conn)
        live = await published(conn, p, now)
        draft = await post(conn, p.org, p.reviewer, now)
        rejected = await post(conn, p.org, p.reviewer, now)
        await decide(conn, p.moderator, rejected, "reject")
        cancelled = await published(conn, p, now)
        await t.act(conn, p.moderator)
        await t.run(conn, CANCEL, event=cancelled)
        ended = await post(
            conn, p.org, p.reviewer, now, starts=now - timedelta(hours=3), ends=now - timedelta(minutes=1)
        )
        await t.as_owner(conn)  # published before it ended (app_decide_event never publishes an ended event)
        publish = "UPDATE events SET status = 'published', decided_by = :m, decided_at = now() WHERE id = :id"
        await t.run(conn, publish, m=p.moderator, id=ended)
        running = await published(conn, p, now, starts=now - timedelta(hours=1), ends=now + timedelta(hours=1))
        await t.act(conn, p.developer)
        returned = await conn.execute(sa.text(REMIND + " RETURNING created_at"), {"user": p.developer, "event": live})
        assert abs(returned.scalar_one() - now) < timedelta(minutes=5)
        await t.run(conn, REMIND, user=p.developer, event=running)  # started, not ended
        await t.expect(conn, REMIND, "pk_event_reminders", user=p.developer, event=live)
        for event_id in (draft, rejected, cancelled, ended, uuid7()):
            await t.expect(conn, REMIND, RLS, user=p.developer, event=event_id)
        await t.as_owner(conn)  # a developer who is also the organisation's member reads its drafts: still refused
        await t.member(conn, p.org, p.developer, "{viewer}")
        await t.act(conn, p.developer, p.org)
        assert await t.run(conn, "SELECT count(*) FROM events WHERE id = ANY(:ids)", ids=[draft, rejected]) == 2
        for event_id in (draft, rejected, cancelled):
            await t.expect(conn, REMIND, RLS, user=p.developer, event=event_id)
        await t.act(conn, p.developer)
        await t.expect(conn, REMIND, RLS, user=p.other, event=live)  # in another developer's name
        await t.expect(conn, REMIND + " ON CONFLICT DO NOTHING", RLS, user=p.other, event=live)
        await t.expect(
            conn,
            "INSERT INTO event_reminders (user_id, event_id, created_at) VALUES (:u, :e, now())",
            DENIED,
            u=p.developer,
            e=live,
        )
        for user, org in ((p.viewer, p.org), (p.reviewer, p.org), (p.admin, None), (p.moderator, None)):
            await t.act(conn, user, org)
            await t.expect(conn, REMIND, RLS, user=user, event=live)
        mine = "SELECT event_id FROM event_reminders WHERE event_id = ANY(:ids)"
        await t.act(conn, p.developer)
        assert set((await conn.execute(sa.text(mine), {"ids": [live, running]})).scalars()) == {live, running}
        await t.expect(
            conn, "UPDATE event_reminders SET event_id = :e WHERE user_id = :u", DENIED, e=running, u=p.developer
        )
        for user, org in (
            (p.other, None),
            (p.viewer, p.org),
            (p.reviewer, p.org),
            (p.admin, None),
            (p.moderator, None),
            (None, None),
        ):
            await t.act(conn, user, org)
            assert (
                await t.run(
                    conn, "SELECT count(*) FROM event_reminders WHERE event_id = ANY(:ids)", ids=[live, running]
                )
                == 0
            )
            assert await t.rowcount(conn, "DELETE FROM event_reminders WHERE event_id = :e", e=live) == 0
        await t.act(conn, p.other)
        await t.run(conn, REMIND, user=p.other, event=live)
        await t.act(conn, p.developer)
        assert await t.rowcount(conn, "DELETE FROM event_reminders WHERE event_id = :e", e=live) == 1  # Decline
        assert set((await conn.execute(sa.text(mine), {"ids": [live, running]})).scalars()) == {running}
        await t.as_owner(conn)
        assert await t.run(conn, "SELECT count(*) FROM event_reminders WHERE event_id = :e", e=live) == 1  # the other's


async def test_the_reminder_job_lists_due_reminders_and_nothing_else(owner_engine: AsyncEngine) -> None:
    """``app_event_reminders_due(now)`` (no user bound): the reminders of active users on published events that start on
    ``now``'s Nairobi day or the next and have not ended at ``now``; not a later event's, an ended or cancelled one's,
    nor a suspended user's. A signed-in session (staff included) is refused; so is a NULL time."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        now = await clock(conn)
        today: Any = await t.run(conn, "SELECT app_nairobi_today()")
        midnight: datetime = await t.run(
            conn, "SELECT CAST(:d AS date)::timestamp AT TIME ZONE 'Africa/Nairobi'", d=today + timedelta(days=1)
        )
        at = midnight + timedelta(hours=7)  # 07:00 tomorrow, Nairobi: the job's "now"
        hours = timedelta(hours=1)
        same_day = await published(conn, p, now, starts=midnight + 10 * hours, ends=midnight + 12 * hours)
        next_day = await published(conn, p, now, starts=midnight + 34 * hours, ends=midnight + 36 * hours)
        later = await published(conn, p, now, starts=midnight + 58 * hours, ends=midnight + 60 * hours)
        over = await published(conn, p, now, starts=midnight + 5 * hours, ends=midnight + 6 * hours)
        dropped = await published(conn, p, now, starts=midnight + 10 * hours, ends=midnight + 11 * hours)
        events = [same_day, next_day, later, over, dropped]
        for user in (p.developer, p.other):
            await t.act(conn, user)
            for event_id in events:
                await t.run(conn, REMIND, user=user, event=event_id)
        await t.act(conn, p.admin)
        await t.run(conn, CANCEL, event=dropped)
        await t.as_owner(conn)
        await t.run(conn, "UPDATE users SET status = 'suspended' WHERE id = :u", u=p.other)
        await t.act(conn, None)
        due = {(row.user_id, row.event_id) for row in await conn.execute(sa.text(DUE), {"now": at})}
        assert {pair for pair in due if pair[1] in events} == {(p.developer, same_day), (p.developer, next_day)}
        assert list((await conn.execute(sa.text(DUE), {"now": at})).keys()) == ["user_id", "event_id"]
        await t.expect(conn, DUE, "name the time", now=None)
        for user in (p.developer, p.admin):
            await t.act(conn, user)
            await t.expect(conn, DUE, "the event reminder job only", now=at)
