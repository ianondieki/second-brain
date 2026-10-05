"""REQ-ENG-11 (D-57 (4)), REQ-MOD-01: staff work message reports in the moderation queue.

Given a party's report of a message, When a moderator lists the queue, Then the case reads "Reported message" with its
reason codes, never the text, and offers dismiss or uphold; When they open the case, Then it carries that one message
(engagement, sender side, text, time) read through ``app_reported_message``, and every read writes an audit event with
ids only; When they decide it, Then the case closes (dismiss: approved; uphold: rejected) with the staff note in the
decision's audit details and the message unchanged in the thread; the reporter never decides their own report, a
message report takes neither approve nor reject, and a proposal case takes neither dismiss nor uphold.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.engagements.thread_world import posted, read, thread_at, thread_path
from tests.integration.proposals.helpers import Staff, user_of

TEXT = "Pay the deposit to my own M-Pesa line, not the company's."
CASES = "/api/admin/moderation/cases"


async def _listed(staff: httpx.AsyncClient, case_id: str, *, decided: bool = False) -> dict[str, Any]:
    response = await staff.get(CASES, params={"decided": str(decided).lower()})
    assert response.status_code == 200, response.text
    [case] = [c for c in response.json()["items"] if c["id"] == case_id]
    return dict(case)


async def _audits(owner_engine: AsyncEngine, action: str, case_id: str) -> list[tuple[dict[str, Any], Any]]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT a.payload, d.details FROM audit_events a LEFT JOIN event_details d ON d.event_id = a.id"
                " WHERE a.action = :a AND a.subject_id = :c ORDER BY a.occurred_at, a.id"
            ),
            {"a": action, "c": case_id},
        )
        return [(dict(payload), details) for payload, details in rows.all()]


async def test_a_moderator_reads_and_decides_a_message_report(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, moderators: Staff
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        sent = await posted(s.owner, e, TEXT)
        reported = await s.dev.post(thread_path(e, f"/{sent['id']}/report"), json={"reasons": ["abuse", "other"]})
        case_id = reported.json()["case_id"]
        moderator, admin = await moderators(), await moderators("admin")

        listed = await _listed(moderator, case_id)
        assert listed["subject_type"] == "message"
        assert listed["preview"] == {"title": "Reported message", "text": None}
        assert sorted(listed["reasons"]) == ["abuse", "other"]
        assert (listed["actions"], listed["blocked"], listed["message"]) == (["dismiss", "uphold"], None, None)
        assert listed["fields"] == []
        assert TEXT not in str(listed)

        for staff in (moderator, admin):
            opened = await staff.get(f"{CASES}/{case_id}")
            assert opened.status_code == 200, opened.text
            message = opened.json()["message"]
            assert message["message_id"] == sent["id"]
            assert message["engagement_id"] == str(e)
            assert (message["sender_party"], message["body"]) == ("org", TEXT)
        reads = await _audits(owner_engine, "moderation.reported_message_read", case_id)
        assert [payload for payload, _ in reads] == [{"message_id": sent["id"], "engagement_id": str(e)}] * 2
        assert all(details is None for _, details in reads)

        for wrong in ("approve", "reject"):
            refused = await moderator.post(
                f"{CASES}/{case_id}/decision", json={"decision": wrong, "subject_version_id": None}
            )
            assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "invalid_decision")
        decided = await moderator.post(
            f"{CASES}/{case_id}/decision",
            json={"decision": "uphold", "subject_version_id": None, "note": "Payment outside the platform."},
        )
        assert decided.status_code == 200, decided.text
        assert decided.json() == {"id": case_id, "status": "rejected", "subject_state": None}
        again = await admin.post(
            f"{CASES}/{case_id}/decision", json={"decision": "dismiss", "subject_version_id": None}
        )
        assert (again.status_code, again.json()["detail"]["code"]) == (409, "already_decided")
        closed = await _listed(admin, case_id, decided=True)
        assert (closed["status"], closed["actions"], closed["blocked"]) == ("rejected", [], "already_decided")
        assert closed["decided_by"]["id"] == str(user_of(moderator))
        [(payload, details)] = await _audits(owner_engine, "moderation.case_decided", case_id)
        assert payload == {"subject_type": "message", "subject_id": sent["id"], "decision": "uphold"}
        assert details == {"note": "Payment outside the platform."}
        for client in (s.dev, s.owner):
            assert [m["body"] for m in (await read(client, e))["items"]] == [TEXT]


async def test_a_report_is_dismissed_and_its_reporter_never_decides_it(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, moderators: Staff
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        sent = await posted(s.dev, e, "The invoice is attached in the next message.")
        reported = await s.owner.post(thread_path(e, f"/{sent['id']}/report"), json={"reasons": ["spam"]})
        case_id = reported.json()["case_id"]
        moderator = await moderators()
        async with owner_engine.begin() as conn:  # the same case, as if the moderator had filed it
            await conn.execute(
                text("UPDATE moderation_cases SET reporter_id = :u WHERE id = :c"),
                {"u": user_of(moderator), "c": case_id},
            )
        own = await _listed(moderator, case_id)
        assert (own["actions"], own["blocked"]) == ([], "own_content")
        refused = await moderator.post(
            f"{CASES}/{case_id}/decision", json={"decision": "dismiss", "subject_version_id": None}
        )
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "own_content")
        other = await moderators()
        dismissed = await other.post(
            f"{CASES}/{case_id}/decision", json={"decision": "dismiss", "subject_version_id": None}
        )
        assert dismissed.json()["status"] == "approved"
        [(_, details)] = await _audits(owner_engine, "moderation.case_decided", case_id)
        assert details is None


async def test_a_non_staff_party_cannot_read_the_case(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        sent = await posted(s.owner, e, TEXT)
        case_id = (await s.dev.post(thread_path(e, f"/{sent['id']}/report"), json={"reasons": ["abuse"]})).json()[
            "case_id"
        ]
        for client in (s.dev, s.owner):
            assert (await client.get(f"{CASES}/{case_id}")).status_code == 404
        assert await _audits(owner_engine, "moderation.reported_message_read", case_id) == []
        assert UUID(case_id)
