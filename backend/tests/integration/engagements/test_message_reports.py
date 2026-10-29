"""REQ-ENG-11 (P21-A6; D-57 (4)): a party reports one message to the moderators. The report files one moderation
case (``subject_type = 'message'``) that shares that message's text and sender side with staff
(``app_reported_message``, the only way staff read a message); a second report by the same person is the same case;
the message stays visible to the parties; 10 message reports a day per person.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration.engagements.api_world import run
from tests.integration.engagements.thread_world import code, posted, read, thread_at, thread_path

TEXT = "Send the deposit to my personal M-Pesa today or the deal is off."


async def _reported(owner_engine: AsyncEngine, staff: UUID, case: UUID) -> list[tuple[str, str]]:
    """What staff read of a case through app_reported_message (as staff admin, bound like the app)."""
    async with owner_engine.begin() as conn:
        await conn.execute(text("SET LOCAL ROLE bridge_app"))
        await conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(staff)})
        rows = await conn.execute(text("SELECT sender_party::text, body FROM app_reported_message(:c)"), {"c": case})
        return [(str(party), str(body)) for party, body in rows.all()]


async def _cases(owner_engine: AsyncEngine, message: str) -> list[tuple[UUID, list[str], UUID]]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, reasons, reporter_id FROM moderation_cases WHERE subject_type = 'message'"
                " AND subject_id = :m ORDER BY created_at"
            ),
            {"m": message},
        )
        return [(UUID(str(i)), list(r), UUID(str(u))) for i, r, u in rows.all()]


async def test_a_report_files_one_case_that_shares_the_message_with_staff(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given the organisation's message, When the developer reports it twice, Then one case exists with the reasons,
    staff read its text and side through app_reported_message, the second report answers the same case, the message
    is still in the thread for both, and the report is audited (ids and codes only)."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        sent = await posted(s.owner, e, TEXT)
        path = thread_path(e, f"/{sent['id']}/report")
        first = await s.dev.post(path, json={"reasons": ["abuse", "other", "abuse"]})
        assert first.status_code == 200, first.text
        assert first.json()["created"] is True
        again = await s.dev.post(path, json={"reasons": ["spam"]})
        assert again.json() == {"case_id": first.json()["case_id"], "created": False}
        [(case, reasons, reporter)] = await _cases(owner_engine, sent["id"])
        assert str(case) == first.json()["case_id"]
        assert sorted(reasons) == ["abuse", "other"]
        assert reporter == world.developer
        assert await _reported(owner_engine, world.staff, case) == [("org", TEXT)]
        for client in (s.dev, s.owner):
            assert [m["body"] for m in (await read(client, e))["items"]] == [TEXT]
        async with owner_engine.connect() as conn:
            payload = await run(
                conn,
                "SELECT payload FROM audit_events WHERE action = 'engagement.message_reported' AND subject_id = :e",
                e=e,
            )
        assert payload["message_id"] == sent["id"]
        assert TEXT not in str(payload)


async def test_a_report_is_refused_for_ones_own_message_an_unknown_one_or_a_bad_reason(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        sent = await posted(s.owner, e, "A plain question.")
        path = thread_path(e, f"/{sent['id']}/report")
        assert code(await s.owner.post(path, json={"reasons": ["spam"]})) == (409, "own_message")
        unknown = thread_path(e, f"/{uuid7()}/report")
        assert code(await s.dev.post(unknown, json={"reasons": ["spam"]})) == (404, "not_found")
        bodies: list[dict[str, object]] = [
            {"reasons": []},
            {"reasons": ["rude words"]},
            {"reasons": ["spam"], "note": "x"},
        ]
        for body in bodies:
            assert (await s.dev.post(path, json=body)).status_code == 422
        # a colleague's message can be reported by another member (the viewer included: every member reads)
        assert (await thread.viewer.post(path, json={"reasons": ["confidential"]})).json()["created"] is True


async def test_ten_message_reports_a_day_then_429(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        ids = [uuid7() for _ in range(11)]
        async with owner_engine.begin() as conn:
            await conn.execute(text("SET LOCAL ROLE bridge_app"))
            await conn.execute(
                text("SELECT set_config('app.user_id', :u, true), set_config('app.org_id', :o, true)"),
                {"u": str(world.owner), "o": str(world.org)},
            )
            for message in ids:
                await run(
                    conn,
                    "INSERT INTO engagement_messages (id, engagement_id, sender_user_id, sender_party, body)"
                    " VALUES (:id, :e, :u, 'org', 'Buy now.')",
                    id=message,
                    e=e,
                    u=world.owner,
                )
        for message in ids[:10]:
            reported = await s.dev.post(thread_path(e, f"/{message}/report"), json={"reasons": ["spam"]})
            assert reported.status_code == 200, reported.text
        last = await s.dev.post(thread_path(e, f"/{ids[10]}/report"), json={"reasons": ["spam"]})
        assert code(last) == (429, "too_many_reports")
        repeat = await s.dev.post(thread_path(e, f"/{ids[0]}/report"), json={"reasons": ["spam"]})
        assert repeat.json()["created"] is False  # a repeat is the same case, not a new report
