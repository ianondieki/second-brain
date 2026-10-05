"""AC-TRACK-9 (REQ-ENG-11, R37; P21-A1 and A8): the engagement thread before and after ``INTEREST_CONFIRMED``.

Given an engagement before ``INTEREST_CONFIRMED``, When the organisation tries to message and to read the developer's
contact details, Then each is 403 (the thread's GET and POST, an upload, the read marker and the contact reveal),
while the developer reads an empty thread that says it opens at ``INTEREST_CONFIRMED`` and cannot post either (409).
Then the signatory approves to proceed naming a contact, the named contact messages, and the message reaches the
developer in-app and by email (N18: who wrote and a link, never the text) and appears on both History tabs.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.engagements import message_notify
from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import db_today
from tests.integration.engagements.thread_world import (
    Thread,
    code,
    email_of,
    in_app,
    post,
    posted,
    read,
    run_message_jobs,
    thread_at,
    thread_path,
    upload,
)

TEXT = "Could we meet on Tuesday at 10 to plan the pilot for the three depots?"


async def _org_refused(thread: Thread, client: httpx.AsyncClient) -> None:
    """Every thread endpoint answers 403 thread_not_open, and the contact details 403, to an organisation member."""
    e = thread.engagement
    assert code(await client.get(thread_path(e))) == (403, "thread_not_open")
    assert code(await post(client, e, "Hello there.")) == (403, "thread_not_open")
    assert code(await upload(client, e)) == (403, "thread_not_open")
    assert code(await client.post(thread_path(e, "/read"), json={})) == (403, "thread_not_open")
    contact = await client.get(f"/api/engagements/{e}/contact")
    assert contact.status_code == 403, contact.text


async def _developer_waits(thread: Thread) -> None:
    dev, e = thread.seats.dev, thread.engagement
    body = await read(dev, e)
    assert body["status"] == "not_open"
    assert body["opens_at_stage"] == "INTEREST_CONFIRMED"
    assert body["items"] == []
    assert body["next_cursor"] is None
    assert body["can_post"] is False
    assert body["unread"] == 0
    assert code(await post(dev, e, "Hello there.")) == (409, "thread_not_open")
    assert code(await upload(dev, e)) == (409, "thread_not_open")


async def test_before_interest_confirmed_the_organisation_gets_403_and_the_developer_an_empty_thread(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given SUBMITTED and then UNDER_REVIEW, When every organisation seat (the viewer included) tries the thread and
    the contact details, Then 403 each time; the developer reads an empty, not-yet-open thread and cannot post."""
    async with thread_at(owner_engine, app_engine, "SUBMITTED") as thread:
        s = thread.seats
        for stage in ("SUBMITTED", "UNDER_REVIEW"):
            if stage == "UNDER_REVIEW":
                await thread.tracker.ok(s.reviewer, "start-review")
            assert (await thread.tracker.detail(s.dev))["state"] == stage
            for client in (s.owner, s.signatory, s.reviewer, s.finance, thread.viewer):
                await _org_refused(thread, client)
            await _developer_waits(thread)


async def test_after_approval_the_named_contact_messages_and_the_developer_is_told_in_app_and_by_email(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given UNDER_REVIEW, When the signatory approves naming the owner as contact and the owner messages, Then the
    developer gets one in-app N18 linking to the Messages tab and one status email without the text, both parties
    read the message (the developer as unread), and the History tabs of both list it, identically."""
    async with thread_at(owner_engine, app_engine, "UNDER_REVIEW") as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        await _org_refused(thread, s.owner)
        today = await db_today(owner_engine)
        contact = {"contact_user_id": str(world.owner), "contact_channel": "phone", "contact_by": str(today)}
        await thread.tracker.ok(s.signatory, "approve", contact)
        assert (await s.owner.get(f"/api/engagements/{e}/contact")).status_code == 200

        sent = await posted(s.owner, e, TEXT)
        assert sent["sender_party"] == "org"
        assert sent["mine"] is True
        assert sent["body"] == TEXT
        provider = FakeEmailProvider()
        assert await run_message_jobs(owner_engine, app_engine, e, provider) == 1

        [notice] = await in_app(owner_engine, world.developer)
        assert notice["link"] == f"/dev/engagements/{e}?tab=messages"
        assert world.org_name in notice["title"]
        assert TEXT not in str(notice["body"])
        [email] = provider.outbox
        assert email.to == await email_of(owner_engine, world.developer)
        assert "New message" in email.subject
        assert TEXT not in email.text
        assert TEXT not in (email.html or "")
        assert "Tuesday" not in email.text
        assert f"/dev/engagements/{e}?tab=messages" in email.text
        assert email.tag == message_notify.KIND

        mine = await read(s.dev, e)
        assert mine["status"] == "open"
        assert mine["can_post"] is True
        assert mine["unread"] == 1
        [message] = mine["items"]
        assert message["body"] == TEXT
        assert message["sender_party"] == "org"
        assert message["mine"] is False
        theirs = await read(s.owner, e)
        assert theirs["items"][0]["mine"] is True
        assert theirs["unread"] == 0

        histories: list[dict[str, Any]] = []
        for client in (s.dev, s.owner):
            response = await client.get(f"/api/engagements/{e}/history")
            assert response.status_code == 200, response.text
            histories.append(response.json())
        dev_history, org_history = histories
        [entry] = dev_history["messages"]
        assert entry["id"] == sent["id"]
        assert entry["sender_party"] == "org"
        assert entry["sender_name"] == message["sender_name"]
        assert "body" not in entry
        assert dev_history["messages"] == org_history["messages"]
        assert TEXT not in str(dev_history)


async def test_the_viewer_reads_the_open_thread_but_cannot_post(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given an open thread, When the organisation's viewer reads and tries to post, Then the read is 200 (can_post
    false) and the post and the upload are 403 cannot_post."""
    async with thread_at(owner_engine, app_engine) as thread:
        e = thread.engagement
        await posted(thread.seats.dev, e, "The pilot plan is ready.")
        body = await read(thread.viewer, e)
        assert body["can_post"] is False
        assert len(body["items"]) == 1
        assert code(await post(thread.viewer, e, "Hello.")) == (403, "cannot_post")
        assert code(await upload(thread.viewer, e)) == (403, "cannot_post")


async def test_the_history_tab_lists_both_sides_messages_without_their_text(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """P21-A8: Given a message from each side, Then both History tabs list the two entries (who, which side, when),
    oldest first, identically, and never the text."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        first = await posted(s.dev, e, "Here is our pilot plan.")
        second = await posted(s.reviewer, e, "Thanks, reading it now.")
        histories = [(await client.get(f"/api/engagements/{e}/history")).json() for client in (s.dev, s.owner)]
        assert histories[0]["messages"] == histories[1]["messages"]
        entries = histories[0]["messages"]
        assert [(m["id"], m["sender_party"]) for m in entries] == [
            (first["id"], "developer"),
            (second["id"], "org"),
        ]
        names = {m["sender_party"]: m["sender_name"] for m in entries}
        assert names == {"developer": first["sender_name"], "org": second["sender_name"]}
        assert world.org_name not in names.values()
        assert "pilot plan" not in str(histories[0])
