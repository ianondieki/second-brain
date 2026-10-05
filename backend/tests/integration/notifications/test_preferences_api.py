"""REQ-NOT-03 "email per preference" (docs/spec/06 6.10; the catalogue in ``notifications.catalogue``), with N18 as
its first entry (REQ-ENG-11, D-57 (2)): a person reads and changes their own notification choices, and the senders
read them through ``preferences.channel_enabled``.

Given a signed-in person, When they read their choices, Then every catalogue entry with its default (N18 email: on);
When they turn N18 emails off, Then the choice is theirs alone, survives a repeat, and the N18 job sends them no email
while the in-app notice still comes; a (kind, channel) the catalogue does not offer is 422 and saves nothing; signed
out is 401.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.engagements import message_notify
from bridge.models.enums import NotificationChannel
from bridge.notifications.catalogue import default_for
from bridge.notifications.email import FakeEmailProvider
from bridge.notifications.preferences import channel_enabled
from tests.integration.api import make_client
from tests.integration.engagements.thread_world import in_app, posted, run_message_jobs, thread_at

URL = "/api/me/notification-preferences"
N18 = {"kind": "engagement.n18", "channel": "email"}


async def test_a_person_turns_n18_emails_off_and_on_for_themselves_only(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        listed = await s.dev.get(URL)
        assert listed.status_code == 200, listed.text
        assert listed.json()["items"] == [N18 | {"enabled": True, "default": True, "audience": "both"}]

        off = await s.dev.put(URL, json={"items": [N18 | {"enabled": False}]})
        assert off.status_code == 200, off.text
        assert off.json()["items"][0]["enabled"] is False
        again = await s.dev.put(URL, json={"items": [N18 | {"enabled": False}]})
        assert again.json() == off.json()
        assert (await s.owner.get(URL)).json()["items"][0]["enabled"] is True

        provider = FakeEmailProvider()
        await posted(s.owner, e, "Are you free on Tuesday?")
        await run_message_jobs(owner_engine, app_engine, e, provider)
        assert len(await in_app(owner_engine, world.developer)) == 1
        assert provider.outbox == []

        on = await s.dev.put(URL, json={"items": [N18 | {"enabled": True}]})
        assert on.json()["items"][0]["enabled"] is True
        factory = create_session_factory(app_engine)
        async with factory() as db:
            await bind_tenant(db, user_id=world.developer)
            assert await channel_enabled(db, world.developer, message_notify.KIND, NotificationChannel.EMAIL)


async def test_an_unknown_choice_is_422_and_saves_nothing(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        dev = thread.seats.dev
        for items in (
            [N18 | {"enabled": False}, {"kind": "engagement.n04", "channel": "email", "enabled": False}],
            [{"kind": "engagement.n18", "channel": "in_app", "enabled": False}],
        ):
            refused = await dev.put(URL, json={"items": items})
            assert refused.status_code == 422
            assert refused.json()["detail"]["code"] == "unknown_preference"
        assert (await dev.put(URL, json={"items": []})).status_code == 422
        async with owner_engine.connect() as conn:
            count = await conn.execute(
                text("SELECT count(*) FROM notification_preferences WHERE user_id = :u"), {"u": thread.world.developer}
            )
            assert count.scalar() == 0


async def test_signed_out_is_401(app_engine: AsyncEngine) -> None:
    async with make_client(app_engine) as client:
        assert (await client.get(URL)).status_code == 401
        assert (await client.put(URL, json={"items": [N18 | {"enabled": False}]})).status_code == 401


def test_a_kind_the_catalogue_does_not_list_stays_on_by_default() -> None:
    assert default_for("engagement.n18", NotificationChannel.EMAIL) is True
    assert default_for("engagement.n03", NotificationChannel.EMAIL) is True
