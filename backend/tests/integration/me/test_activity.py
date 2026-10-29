"""REQ-UX-05 (P25-B, D-67): ``GET /api/me/activity`` against the database, as each person of the scene
(``tests.integration.me.scene``).

- Each person's counts are their own rows only: Amina's publication, message, quiz attempt and team message, never
  Brian's or Alpha's member's; Alpha's member's opened proposal, the engagement they opened, their message and their
  three Briefs; staff (the developer's kinds) nothing. Every table the kinds read shows a person their own rows under
  RLS, so no kind is left out.
- A first publication is one action (``proposal_published``); only a later version counts as ``version_registered``.
  A problem a member wrote that is not a Brief is not ``brief_posted``.
- Days are Africa/Nairobi's on the platform clock, and moving the dev/test clock moves ``to``: a message at 20:59:59
  UTC counts on that day, one at 21:00 UTC on the next; one a second before the range's first midnight is outside it,
  one at that midnight inside. Expectations come from the answer's own ``to``, so a run across 21:00 UTC holds.
- ``weeks`` sets the range (26 by default); the answer says ``Cache-Control: private, no-store`` and has the OpenAPI
  document's shape.
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
from tests.integration.engagements.api_world import moved_clock
from tests.integration.me.conftest import SignedIn
from tests.integration.me.scene import Scene, brief, idea, niche, person, problem
from tests.unit.public.openapi_shape import conforms

PATH = "/api/me/activity"


async def calendar(client: httpx.AsyncClient, **params: int) -> dict[str, Any]:
    response = await client.get(PATH, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
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


def last_day(body: dict[str, Any]) -> date:
    return date.fromisoformat(body["to"])


async def read_today(client: httpx.AsyncClient, engine: AsyncEngine, **params: int) -> dict[str, Any]:
    """One read whose ``to`` is the platform clock's Nairobi day, read just before or just after it."""
    before = await platform_today(engine)
    body = await calendar(client, **params)
    after = await platform_today(engine)
    assert last_day(body) in {before, after}
    return body


async def test_a_developer_counts_only_their_own_actions(
    scene: Scene, signed_in: SignedIn, owner_engine: AsyncEngine
) -> None:
    async with signed_in(scene.amina) as client:
        body = await read_today(client, owner_engine)
    assert kinds(body) == {
        "version_registered": 0,  # her one version is her publication
        "proposal_published": 1,
        "engagement_step": 0,  # Alpha's member opened her engagement
        "message_sent": 1,
        "quiz_answered": 1,
        "team_message": 1,
    }
    assert body["total"] == 4
    first, _ = window(last_day(body), 26)
    assert (body["from"], body["timezone"]) == (first.isoformat(), "Africa/Nairobi")
    assert len(body["days"]) == 182
    assert [day["date"] for day in body["days"]] == [(first + timedelta(days=n)).isoformat() for n in range(182)]
    assert sum(day["count"] for day in body["days"]) == 4


async def test_another_developer_counts_their_own(scene: Scene, signed_in: SignedIn) -> None:
    async with signed_in(scene.brian) as client:
        body = await calendar(client, weeks=4)
    assert kinds(body) == {
        "version_registered": 0,
        "proposal_published": 2,  # the published idea and the held one
        "engagement_step": 1,  # he opened his engagement with Beta
        "message_sent": 0,
        "quiz_answered": 0,
        "team_message": 1,
    }
    assert (body["total"], len(body["days"])) == (4, 28)


async def test_a_first_publication_counts_once_and_a_later_version_as_registered(
    scene: Scene, signed_in: SignedIn, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        author = await person(conn, "author", developer=True)
        topic = await niche(conn, f"{scene.word} Versions")
        proposal, _ = await idea(conn, author, "Version one", niche_id=topic, problem_id=scene.problems["public"])
        version = uuid7()
        await t.run(
            conn,
            "INSERT INTO proposal_versions (id, proposal_id, version_no, title, niche_id, maturity, ask,"
            " problem_statement, summary) VALUES (:id, :p, 2, 'Version two', :n, 'idea', 'pilot', 'A problem',"
            " 'What it does')",
            id=version,
            p=proposal,
            n=topic,
        )
        await t.run(
            conn,
            "INSERT INTO proposal_problems (proposal_version_id, problem_id) VALUES (:v, :p)",
            v=version,
            p=scene.problems["public"],
        )
        await t.run(
            conn,
            "UPDATE proposal_versions SET status = 'registered', cert_id = :c WHERE id = :v",
            v=version,
            c=uuid7().hex[:16],
        )
        await t.run(conn, "UPDATE proposals SET current_version_id = :v WHERE id = :p", v=version, p=proposal)
    async with signed_in(author) as client:
        body = await calendar(client, weeks=1)
    assert (kinds(body)["proposal_published"], kinds(body)["version_registered"], body["total"]) == (1, 1, 2)


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


async def test_a_problem_a_member_wrote_that_is_not_a_brief_is_not_a_brief_posted(
    scene: Scene, signed_in: SignedIn, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        poster = await person(conn, "poster", developer=False)
        await t.member(conn, scene.alpha, poster, "{finance}")
        topic = await niche(conn, f"{scene.word} Posted")
        posted = await problem(conn, "A Brief", by=poster, niche_id=topic, org=scene.alpha)
        await brief(conn, posted, scene.alpha, visibility="public", status="published")
        await problem(conn, "A developer problem", by=poster, niche_id=topic)
    async with signed_in(poster) as client:
        body = await calendar(client, weeks=1)
    assert kinds(body) == {"proposal_opened": 0, "engagement_step": 0, "message_sent": 0, "brief_posted": 1}


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


async def test_today_follows_the_platform_clock(scene: Scene, signed_in: SignedIn, owner_engine: AsyncEngine) -> None:
    """Given the dev/test clock moved three days ahead, When the calendar is read, Then it ends on the moved day."""
    async with signed_in(scene.staff) as client:
        before = last_day(await read_today(client, owner_engine, weeks=1))
        async with moved_clock(owner_engine) as advance:
            await advance(3)
            moved = await read_today(client, owner_engine, weeks=1)
        after = last_day(await read_today(client, owner_engine, weeks=1))
    to = last_day(moved)
    assert (to - before).days in (3, 4)  # 4 only when Nairobi's midnight passed between the reads
    assert moved["from"] == (to - timedelta(days=6)).isoformat()
    assert (after - before).days in (0, 1)  # put back with the clock


async def test_days_are_nairobi_s_and_the_range_starts_at_its_first_midnight(
    scene: Scene, signed_in: SignedIn, owner_engine: AsyncEngine
) -> None:
    """Given a team thread of two new developers, When one of them sends messages at 21:00 UTC boundaries, Then each
    counts on its Nairobi day, and only those within the week ending on the answer's ``to`` count."""
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
    assert [nairobi_day(m) for m in moments] == [
        first - timedelta(days=1),
        first,
        today - timedelta(2),
        today - timedelta(1),
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
        sent = (
            (await conn.execute(text("SELECT created_at FROM team_messages WHERE sender_user_id = :u"), {"u": zawadi}))
            .scalars()
            .all()
        )
    async with signed_in(zawadi) as client:
        body = await calendar(client, weeks=1)
    end = last_day(body)  # the answer's own today: the expectation holds even if Nairobi's midnight passed meanwhile
    begin = end - timedelta(days=6)
    counted = [nairobi_day(moment) for moment in sent if begin <= nairobi_day(moment) <= end]
    assert {day["date"]: day["count"] for day in body["days"]} == {
        (begin + timedelta(days=n)).isoformat(): counted.count(begin + timedelta(days=n)) for n in range(7)
    }
    assert kinds(body)["team_message"] == body["total"] == len(counted)
    if end == today:  # the usual case, spelled out: the first midnight in, the second before it out
        assert len(counted) == 4
        assert [day["count"] for day in body["days"]] == [1, 0, 0, 0, 1, 1, 1]


async def test_signed_out_is_401_and_weeks_out_of_range_is_422(scene: Scene, signed_in: SignedIn) -> None:
    async with signed_in(scene.amina) as client:
        for weeks in (0, 53):
            assert (await client.get(PATH, params={"weeks": weeks})).status_code == 422
        await client.post("/api/auth/logout")
        assert (await client.get(PATH)).status_code == 401
