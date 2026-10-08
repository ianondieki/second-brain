"""REQ-UX-05 (P25-B, D-67): ``GET /api/me/activity`` against the database, as each person of the scene
(``tests.integration.me.scene``).

- Each person's counts are their own rows only: Amina's registered version, publication, message, quiz attempt and
  team message, never Brian's or Alpha's member's; Alpha's member's opened proposal, the engagement they opened, their
  message and their three Briefs; staff (the developer's kinds) nothing. Every table the kinds read shows a person
  their own rows under RLS, so no kind is left out.
- Days are Africa/Nairobi's on the platform clock: a message at 20:59:59 UTC counts on that day, one at 21:00 UTC on
  the next; one a second before the range's first midnight is outside it, one at that midnight inside.
- ``weeks`` sets the range (26 by default); the answer says ``Cache-Control: private, max-age=60`` and has the
  OpenAPI document's shape.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from bridge.me.activity import NAIROBI, bounds, nairobi_day, window
from tests.integration import world as w
from tests.integration.engagements import tracker as t
from tests.integration.me.conftest import SignedIn
from tests.integration.me.scene import Scene, person
from tests.unit.public.openapi_shape import conforms

PATH = "/api/me/activity"


async def calendar(client: httpx.AsyncClient, **params: int) -> dict[str, Any]:
    response = await client.get(PATH, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, max-age=60"
    body: dict[str, Any] = response.json()
    document = client.app.openapi()  # type: ignore[attr-defined]
    schema = document["paths"][PATH]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    conforms(body, schema, document["components"]["schemas"])
    return body


def kinds(body: dict[str, Any]) -> dict[str, int]:
    return {entry["kind"]: entry["count"] for entry in body["kinds"]}


async def platform_today(engine: AsyncEngine) -> date:
    async with engine.connect() as conn:
        now: datetime = (await conn.execute(text("SELECT app_clock_now()"))).scalar_one()
    return nairobi_day(now)


async def test_a_developer_counts_only_their_own_actions(
    scene: Scene, signed_in: SignedIn, owner_engine: AsyncEngine
) -> None:
    today = await platform_today(owner_engine)
    async with signed_in(scene.amina) as client:
        body = await calendar(client)
    assert kinds(body) == {
        "version_registered": 1,
        "proposal_published": 1,
        "engagement_step": 0,  # Alpha's member opened her engagement
        "message_sent": 1,
        "quiz_answered": 1,
        "team_message": 1,
    }
    assert body["total"] == 5
    first, last = window(today, 26)
    assert (body["from"], body["to"], body["timezone"]) == (first.isoformat(), last.isoformat(), "Africa/Nairobi")
    assert len(body["days"]) == 182
    assert [day["date"] for day in body["days"]] == [(first + timedelta(days=n)).isoformat() for n in range(182)]
    assert sum(day["count"] for day in body["days"]) == 5


async def test_another_developer_counts_their_own(scene: Scene, signed_in: SignedIn) -> None:
    async with signed_in(scene.brian) as client:
        body = await calendar(client, weeks=4)
    assert kinds(body) == {
        "version_registered": 2,  # the published idea and the held one
        "proposal_published": 2,
        "engagement_step": 1,  # he opened his engagement with Beta
        "message_sent": 0,
        "quiz_answered": 0,
        "team_message": 1,
    }
    assert (body["total"], len(body["days"])) == (6, 28)


async def test_an_organisation_member_counts_their_own_opens_steps_messages_and_briefs(
    scene: Scene, signed_in: SignedIn
) -> None:
    async with signed_in(scene.member_a) as client:
        body = await calendar(client)
    assert kinds(body) == {"proposal_opened": 1, "engagement_step": 1, "message_sent": 1, "brief_posted": 3}
    assert body["total"] == 6
    async with signed_in(scene.member_b) as client:
        other = await calendar(client)
    assert kinds(other) == {"proposal_opened": 0, "engagement_step": 0, "message_sent": 0, "brief_posted": 1}


async def test_staff_count_the_developer_kinds_and_have_none_here(scene: Scene, signed_in: SignedIn) -> None:
    async with signed_in(scene.staff) as client:
        body = await calendar(client, weeks=1)
    assert list(kinds(body)) == [
        "version_registered",
        "proposal_published",
        "engagement_step",
        "message_sent",
        "quiz_answered",
        "team_message",
    ]
    assert (body["total"], len(body["days"])) == (0, 7)


async def test_days_are_nairobi_s_and_the_range_starts_at_its_first_midnight(
    scene: Scene, signed_in: SignedIn, owner_engine: AsyncEngine
) -> None:
    """Given a team thread of two new developers, When one of them sends messages at 21:00 UTC boundaries, Then each
    counts on its Nairobi day, and only those within the week ending today count."""
    today = await platform_today(owner_engine)
    first, last = window(today, 1)
    start, _ = bounds(first, last)
    late = datetime.combine(today - timedelta(days=2), datetime.max.time().replace(microsecond=0), NAIROBI)
    moments = [
        start - timedelta(seconds=1),  # the evening before the range
        start,  # its first midnight
        late,  # 23:59:59 two days ago (20:59:59 UTC)
        late + timedelta(seconds=1),  # midnight: yesterday (21:00 UTC)
    ]
    async with owner_engine.begin() as conn:
        zawadi = await person(conn, "zawadi", developer=True)
        juma = await person(conn, "juma", developer=True)
        await w.add_team_rows(conn, zawadi, juma, scene.problems["public"], (), f"{scene.word}-days")
        thread = await t.run(conn, "SELECT id FROM team_threads WHERE :u IN (a_user_id, b_user_id)", u=zawadi)
        for moment in moments:
            await t.run(
                conn,
                "INSERT INTO team_messages (id, thread_id, sender_user_id, body, created_at)"
                " VALUES (:id, :thread, :sender, 'Hello', :at)",
                id=uuid7(),
                thread=thread,
                sender=zawadi,
                at=moment,
            )
    async with signed_in(zawadi) as client:
        body = await calendar(client, weeks=1)
    per_day = {day["date"]: day["count"] for day in body["days"]}
    assert per_day == {
        first.isoformat(): 1,
        (first + timedelta(days=1)).isoformat(): 0,
        (first + timedelta(days=2)).isoformat(): 0,
        (first + timedelta(days=3)).isoformat(): 0,
        (today - timedelta(days=2)).isoformat(): 1,
        (today - timedelta(days=1)).isoformat(): 1,
        today.isoformat(): 1,  # the thread's own first message, now
    }
    assert kinds(body)["team_message"] == 4
    assert body["total"] == 4


async def test_signed_out_is_401_and_weeks_out_of_range_is_422(scene: Scene, signed_in: SignedIn) -> None:
    async with signed_in(scene.amina) as client:
        for weeks in (0, 53):
            assert (await client.get(PATH, params={"weeks": weeks})).status_code == 422
        await client.post("/api/auth/logout")
        assert (await client.get(PATH)).status_code == 401
