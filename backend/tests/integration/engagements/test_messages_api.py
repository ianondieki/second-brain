"""REQ-ENG-11 through the API (P21-A2, A3, A5): who reads and writes the thread, when it is read-only, what a message
may hold, the rate limit, paging and the unread counts.

- A2: a non-party (another developer, another organisation's member, staff admin) gets 404 on every thread endpoint,
  exactly as for an engagement that does not exist; a developer who is also a member of the organisation gets 403.
- A3: after each terminal state nobody posts or uploads (409 ``thread_read_only``) and both parties still read.
- A5: a message is append-only for the app role (no UPDATE, no DELETE), whatever the API does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.engagements import messages
from bridge.ids import uuid7
from tests.integration.engagements.api_world import clients, db_today, run, walk_to
from tests.integration.engagements.thread_world import (
    code,
    end,
    post,
    posted,
    read,
    thread_at,
    thread_path,
    upload,
    uploaded,
)
from tests.integration.world import add_user

TERMINAL = ("DECLINED", "WITHDRAWN", "EXPIRED", "TERMINATED")


async def _other_org_member(owner_engine: AsyncEngine) -> UUID:
    async with owner_engine.begin() as conn:
        member = await add_user(conn, f"other-{uuid7().hex[:8]}@other.example.test", "Other Member")
        org = uuid7()
        await run(
            conn,
            "INSERT INTO organizations (id, kind, legal_name, slug, source, verification)"
            " VALUES (:id, 'company', 'Other Ltd', :slug, 'seed', 'e2')",
            id=org,
            slug=f"other-{org.hex}",
        )
        await run(
            conn,
            "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, '{finance}')",
            id=uuid7(),
            org=org,
            u=member,
        )
    return member


async def test_a_non_party_gets_404_on_every_thread_endpoint(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given an open thread with a message and a sent file, When another developer, another organisation's member and
    staff admin try the thread, Then each endpoint answers 404 not_found, as for an unknown engagement."""
    async with thread_at(owner_engine, app_engine) as thread:
        e = thread.engagement
        file_id = await uploaded(thread.seats.dev, e)
        sent = await posted(thread.seats.dev, e, "The pilot plan, attached.", attachments=[file_id])
        link = (await thread.seats.owner.get(thread_path(e, f"/{sent['id']}/attachments/{file_id}"))).json()["url"]
        outsiders = (thread.world.outsider, await _other_org_member(owner_engine), thread.world.staff)
        async with clients(app_engine, thread.settings, *outsiders) as signed_in:
            for client in signed_in:
                for target in (e, uuid7()):
                    calls = (
                        client.get(thread_path(target)),
                        post(client, target, "Hello."),
                        upload(client, target),
                        client.post(thread_path(target, "/read"), json={}),
                        client.post(thread_path(target, f"/{sent['id']}/report"), json={"reasons": ["spam"]}),
                        client.get(thread_path(target, f"/{sent['id']}/attachments/{file_id}")),
                        client.delete(thread_path(target, f"/attachments/{file_id}")),
                    )
                    for call in calls:
                        assert code(await call) == (404, "not_found")
                assert code(await client.get(link)) == (404, "not_found")


async def test_a_developer_who_is_also_a_member_of_the_organisation_is_refused(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given an open thread, When the developer becomes a member of the organisation, Then the thread is 403
    both_parties for them (one person never writes for both sides)."""
    async with thread_at(owner_engine, app_engine) as thread:
        async with owner_engine.begin() as conn:
            await run(
                conn,
                "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, '{viewer}')",
                id=uuid7(),
                org=thread.world.org,
                u=thread.world.developer,
            )
        e = thread.engagement
        assert code(await thread.seats.dev.get(thread_path(e))) == (403, "both_parties")
        assert code(await post(thread.seats.dev, e, "Hello.")) == (403, "both_parties")


@pytest.mark.parametrize("state", TERMINAL)
async def test_the_thread_is_read_only_after_each_end(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, state: str
) -> None:
    """Given an open thread with a message, When the engagement ends, Then posting and uploading are 409
    thread_read_only for both sides and the message is still read by both (the status read_only)."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        await posted(s.dev, e, "Here is the pilot plan.")
        staged = await uploaded(s.owner, e)
        await end(owner_engine, thread.world, e, state)
        for client in (s.dev, s.owner):
            assert code(await post(client, e, "Anyone there?")) == (409, "thread_read_only")
            assert code(await upload(client, e)) == (409, "thread_read_only")
            body = await read(client, e)
            assert body["status"] == "read_only"
            assert body["can_post"] is False
            assert [m["body"] for m in body["items"]] == ["Here is the pilot plan."]
        assert code(await post(s.owner, e, "Sending the plan.", attachments=[staged])) == (409, "thread_read_only")
        assert (await s.owner.delete(thread_path(e, f"/attachments/{staged}"))).status_code == 204


async def test_the_thread_is_read_only_once_closed(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Given an engagement walked to CLOSED with a message from stage 3, Then the thread is read-only for both."""
    async with thread_at(owner_engine, app_engine, "INTEREST_CONFIRMED", deals=True) as thread:
        s, e = thread.seats, thread.engagement
        await posted(s.owner, e, "Welcome aboard.")
        await walk_to(thread.tracker, s, thread.world, await db_today(owner_engine), "CLOSED")
        for client in (s.dev, s.owner, thread.viewer):
            assert code(await post(client, e, "Thanks!")) == (409, "thread_read_only")
            assert (await read(client, e))["status"] == "read_only"


async def test_messages_are_append_only_for_the_app_role(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Given a posted message, When its sender, as the app role, updates or deletes it, Then the database refuses."""
    async with thread_at(owner_engine, app_engine) as thread:
        sent = await posted(thread.seats.dev, thread.engagement, "Version one of the plan.")
        factory = create_session_factory(app_engine)
        for sql in (
            "UPDATE engagement_messages SET body = 'Version two' WHERE id = :id",
            "DELETE FROM engagement_messages WHERE id = :id",
        ):
            async with factory() as db:
                await bind_tenant(db, user_id=thread.world.developer)
                with pytest.raises(DBAPIError, match="permission denied"):
                    await db.execute(sa.text(sql), {"id": sent["id"]})
        assert (await read(thread.seats.dev, thread.engagement))["items"][0]["body"] == "Version one of the plan."


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("   \n\t ", 422),
        ("x" * 4001, 422),
        ("nul\x00byte", 422),
        ("escape\x1b[31m", 422),
    ],
)
async def test_an_empty_over_long_or_controlled_body_is_422(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, body: str, expected: int
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        response = await post(thread.seats.dev, thread.engagement, body)
        assert response.status_code == expected, response.text
        assert (await read(thread.seats.dev, thread.engagement))["items"] == []


async def test_a_message_keeps_its_text_as_typed(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """4,000 characters pass; line breaks and tabs stay (a CR before LF is dropped); markup is plain text."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        longest = "y" * 4000
        assert (await posted(s.dev, e, longest))["body"] == longest
        typed = "Line one\r\nLine two\twith a tab <b>not bold</b>"
        assert (await posted(s.owner, e, typed))["body"] == "Line one\nLine two\twith a tab <b>not bold</b>"
        extra = await s.dev.post(thread_path(e), json={"body": "Hi.", "attachment_ids": [], "sender": "org"})
        assert extra.status_code == 422


async def test_contact_details_wait_for_first_contact(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Given INTEREST_CONFIRMED (every member reads the thread; THREAT_MODEL I), When a party writes an email address
    or a link, in the text or in a file's name, Then 422 contains_contact, also while the engagement is on hold from
    that stage (the thread stays open for plain text); once first contact is made (CONTACT_MADE), the same text and
    file are posted."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        text = "Write to amina@example.com or see https://example.com/demo"
        assert code(await post(s.dev, e, text)) == (422, "contains_contact")
        assert code(await post(s.owner, e, text)) == (422, "contains_contact")
        resume_at = await db_today(owner_engine) + timedelta(days=7)
        await thread.tracker.ok(s.dev, "pause", {"reason": "Travelling this week.", "resume_at": str(resume_at)})
        assert code(await post(s.dev, e, text)) == (422, "contains_contact")
        await posted(s.dev, e, "Back next week; talk then.")
        await thread.tracker.ok(s.dev, "resume", {"reason": "Back early."})
        named = await uploaded(s.dev, e, name="call amina on 0712 345 678.pdf")
        plain = await uploaded(s.dev, e, name="pilot plan.pdf")
        refused = await post(s.dev, e, "The plan, attached.", attachments=[plain, named])
        assert code(refused) == (422, "contains_contact")
        assert len((await posted(s.dev, e, "The plan, attached.", attachments=[plain]))["attachments"]) == 1
        await thread.tracker.ok(s.owner, "mark-contacted")
        assert len((await posted(s.dev, e, "And the contact sheet.", attachments=[named]))["attachments"]) == 1
        assert (await posted(s.dev, e, text))["body"] == text


async def test_sixty_messages_an_hour_then_429_with_retry_after(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given 59 messages by the developer on this engagement within the hour, When they post the 60th, Then 201; When
    they post the 61st, Then 429 too_many_messages with a Retry-After of at most an hour; the organisation still
    posts."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        async with owner_engine.begin() as conn:
            await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
            await conn.execute(
                sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(thread.world.developer)}
            )
            for n in range(messages.POSTS_PER_HOUR - 1):
                await run(
                    conn,
                    "INSERT INTO engagement_messages (id, engagement_id, sender_user_id, sender_party, body)"
                    " VALUES (:id, :e, :u, 'developer', :body)",
                    id=uuid7(),
                    e=e,
                    u=thread.world.developer,
                    body=f"Message {n}",
                )
        await posted(s.dev, e, "The sixtieth.")
        refused = await post(s.dev, e, "One more.")
        assert code(refused) == (429, "too_many_messages")
        assert 1 <= int(refused.headers["Retry-After"]) <= 3600
        assert refused.json()["detail"]["retry_after_seconds"] == int(refused.headers["Retry-After"])
        assert len((await read(s.dev, e, limit=100))["items"]) == messages.POSTS_PER_HOUR
        await posted(s.owner, e, "Our side is not limited by yours.")


def test_retry_after_counts_to_the_oldest_message_leaving_the_hour() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    assert messages.retry_after(now - timedelta(minutes=59, seconds=30), now) == 30
    assert messages.retry_after(now - timedelta(hours=2), now) == 1


async def test_pages_run_from_the_newest_back_and_each_reads_oldest_first(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        sent = [(await posted(s.dev if n % 2 else s.owner, e, f"Message {n}"))["id"] for n in range(5)]
        first = await read(s.dev, e, limit=2)
        assert [m["id"] for m in first["items"]] == sent[3:5]
        second = await read(s.dev, e, limit=2, cursor=first["next_cursor"])
        assert [m["id"] for m in second["items"]] == sent[1:3]
        third = await read(s.dev, e, limit=2, cursor=second["next_cursor"])
        assert [m["id"] for m in third["items"]] == sent[0:1]
        assert third["next_cursor"] is None
        assert code(await s.dev.get(thread_path(e), params={"cursor": "not-a-cursor"})) == (400, "invalid_cursor")
        assert (await s.dev.get(thread_path(e), params={"limit": 0})).status_code == 422


async def test_unread_counts_follow_the_read_marker(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Given two messages by the developer, Then each organisation member has 2 unread (thread, detail and the
    organisation's list) and the developer none; marking read up to the first leaves 1, marking all leaves 0, and
    the marker never moves back."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        first = await posted(s.dev, e, "First.")
        await posted(s.dev, e, "Second.")
        assert (await read(s.owner, e))["unread"] == 2
        assert (await read(s.dev, e))["unread"] == 0
        assert (await thread.tracker.detail(s.owner))["unread_messages"] == 2
        listed = (await s.owner.get(f"/api/orgs/{world.org}/engagements")).json()["items"]
        assert [i["unread_messages"] for i in listed if i["id"] == str(e)] == [2]
        marked = await s.owner.post(thread_path(e, "/read"), json={"up_to": first["id"]})
        assert marked.status_code == 200, marked.text
        assert marked.json()["unread"] == 1
        everything = await s.owner.post(thread_path(e, "/read"), json={})
        assert everything.json()["unread"] == 0
        back = await s.owner.post(thread_path(e, "/read"), json={"up_to": first["id"]})
        assert back.json()["last_read_at"] == everything.json()["last_read_at"]
        assert (await read(s.reviewer, e))["unread"] == 2  # each member's own marker
        await posted(s.owner, e, "Thanks.")
        mine = (await s.dev.get("/api/me/engagements")).json()["items"]
        assert [i["unread_messages"] for i in mine if i["id"] == str(e)] == [1]
        unknown = await s.owner.post(thread_path(e, "/read"), json={"up_to": str(uuid7())})
        assert code(unknown) == (404, "not_found")
