"""Revision 0008 (REQ-ENG-11; AC-TRACK-9's database half; D-57 (1), (3), (4)): the engagement thread's messages.

- The stage gate (``engagement_thread_open()``): nobody posts before the chain has entered ``INTEREST_CONFIRMED`` or
  a later main-path stage (a side state or ``PROCUREMENT_ROUTE`` before stage 3 keeps it closed; on a public entity's
  procurement route that skips stage 3 it opens at ``CONTACT_MADE``); from then on both sides post, through the deal
  states and the side states entered after it; after ``DECLINED``, ``WITHDRAWN``, ``EXPIRED``,
  ``TERMINATED`` and ``CLOSED`` the thread is read-only for every role, and still readable by the parties.
- Who: a party posts as themselves on their own side (the developer as ``developer``; an owner, admin, reviewer,
  signatory or finance member as ``org``; never a viewer); the parties read every message (viewers included) and
  nobody else does: not staff admin, who reads the engagement and its notes, not another developer or organisation,
  not a forged organisation context.
- Append-only (D-54's redaction aside), the body 1 to 4,000 characters and not blank, ``created_at`` the database's.
- The report: ``app_report_message(message, reasons)`` files one case per reporter and message, for parties only, at
  most 10 per reporter in 24 hours (fixed: the caller names no limit), with reason codes from a fixed list only;
  bridge_app cannot insert a message report itself; ``app_reported_message`` shows staff that one message.

Every test runs in one rolled-back transaction (``tracker.as_app``). The race with an append in flight and the
"same transaction" rule of attachments commit, so they are in ``test_messages_race.py``.
"""

from __future__ import annotations

from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.engagements.models import MESSAGE_REPORT_REASONS, MESSAGE_REPORTS_PER_DAY
from bridge.ids import uuid7
from tests.integration.engagements import tracker as t

MESSAGE = (
    "INSERT INTO engagement_messages (id, engagement_id, sender_user_id, sender_party, body)"
    " VALUES (:id, :e, :by, CAST(:party AS engagement_party), :body)"
)
COUNT = "SELECT count(*) FROM engagement_messages WHERE engagement_id = :e"
OPENS = "the thread opens at INTEREST_CONFIRMED"
READ_ONLY = "its thread is read-only"
HIDDEN = "no engagement of the caller's with that id"
RLS = "row-level security"
DENIED = "permission denied"
TERMINAL = ("DECLINED", "WITHDRAWN", "EXPIRED", "TERMINATED", "CLOSED")


def message(engagement: UUID, by: UUID, party: str, body: str = "When can we meet?") -> dict[str, object]:
    return {"id": uuid7(), "e": engagement, "by": by, "party": party, "body": body}


async def post(
    conn: AsyncConnection, engagement: UUID, by: UUID, party: str, org: UUID | None = None, body: str = "Hello."
) -> UUID:
    """Post a message as ``by`` (acting for ``org`` when given); returns its id."""
    await t.act(conn, by, org)
    params = message(engagement, by, party, body)
    await t.run(conn, MESSAGE, **params)
    return UUID(str(params["id"]))


async def refused(
    conn: AsyncConnection, engagement: UUID, by: UUID, party: str, refusal: str, org: UUID | None = None
) -> None:
    await t.act(conn, by, org)
    await t.expect(conn, MESSAGE, refusal, **message(engagement, by, party))


async def opened(conn: AsyncConnection) -> tuple[t.Parties, UUID]:
    """Parties and their engagement at INTEREST_CONFIRMED (the developer's tag; the walk's evidence)."""
    p = await t.parties(conn)
    await t.act(conn, p.developer)
    engagement = await t.engage(conn, p)
    await t.walk(conn, p, engagement, "INTEREST_CONFIRMED")
    return p, engagement


async def _closed_for_both(conn: AsyncConnection, p: t.Parties, engagement: UUID, state: str) -> None:
    await t.act(conn, p.developer)
    assert await t.state_of(conn, engagement) == state
    await refused(conn, engagement, p.developer, "developer", OPENS)
    await refused(conn, engagement, p.owner, "org", OPENS, p.org)
    await t.act(conn, p.developer)


async def test_the_thread_opens_at_interest_confirmed_for_both_sides(owner_engine: AsyncEngine) -> None:
    """Given an engagement on its way to stage 3, When either side posts before INTEREST_CONFIRMED (in SUBMITTED,
    UNDER_REVIEW, a hold entered there, or PROCUREMENT_ROUTE ahead of stage 3), Then the gate refuses; once
    INTEREST_CONFIRMED is reached both sides post, and a hold entered after stage 3 keeps the thread open."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        await t.act(conn, p.developer)
        engagement = await t.engage(conn, p)
        await _closed_for_both(conn, p, engagement, "SUBMITTED")
        await t.walk(conn, p, engagement, "UNDER_REVIEW")
        await _closed_for_both(conn, p, engagement, "UNDER_REVIEW")
        await t.append(conn, engagement, p.developer, "developer", "pause", "UNDER_REVIEW", "ON_HOLD")
        await _closed_for_both(conn, p, engagement, "ON_HOLD")  # a hold before stage 3
        await t.append(conn, engagement, p.developer, "developer", "resume", "ON_HOLD", "UNDER_REVIEW")
        await t.act(conn, p.signatory, p.org)  # 3b ahead of stage 3 (a public entity)
        await t.append(conn, engagement, p.signatory, "signatory", "procure", "UNDER_REVIEW", "PROCUREMENT_ROUTE")
        await _closed_for_both(conn, p, engagement, "PROCUREMENT_ROUTE")
        await t.act(conn, p.signatory, p.org)
        await t.append(conn, engagement, p.signatory, "signatory", "approve", "PROCUREMENT_ROUTE", "INTEREST_CONFIRMED")
        await post(conn, engagement, p.developer, "developer")
        for member in (p.owner, p.signatory, p.reviewer, p.finance):
            await post(conn, engagement, member, "org", p.org)
        await t.walk(conn, p, engagement, "CONTACT_MADE")
        await t.append(conn, engagement, p.developer, "developer", "pause", "CONTACT_MADE", "ON_HOLD")
        await post(conn, engagement, p.developer, "developer", body="Back in two weeks.")  # a hold after stage 3
        await post(conn, engagement, p.owner, "org", p.org, body="Noted.")
        await t.act(conn, p.developer)
        assert await t.run(conn, COUNT, e=engagement) == 7


async def test_the_public_entity_path_opens_the_thread_at_contact_made(owner_engine: AsyncEngine) -> None:
    """Given a public entity's engagement on revision 0003's 3b path that never enters INTEREST_CONFIRMED
    (UNDER_REVIEW -> PROCUREMENT_ROUTE -> CONTACT_MADE), Then the thread is closed at PROCUREMENT_ROUTE, opens for both
    sides at CONTACT_MADE and stays open on the way to NDA_SIGNED; and a chain whose genesis is later on the main path
    (the owner's insert at NDA_SIGNED, as revision 0003's backfill wrote) is open too."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        await t.act(conn, p.developer)
        engagement = await t.engage(conn, p)
        await t.walk(conn, p, engagement, "UNDER_REVIEW")
        await t.act(conn, p.owner, p.org)
        await t.append(conn, engagement, p.owner, "owner", "procure", "UNDER_REVIEW", "PROCUREMENT_ROUTE")
        await _closed_for_both(conn, p, engagement, "PROCUREMENT_ROUTE")
        await t.act(conn, p.owner, p.org)
        await t.append(conn, engagement, p.owner, "owner", "mark_contacted", "PROCUREMENT_ROUTE", "CONTACT_MADE")
        await post(conn, engagement, p.developer, "developer")
        await post(conn, engagement, p.owner, "org", p.org)
        await t.walk(conn, p, engagement, "NDA_SIGNED")
        await post(conn, engagement, p.signatory, "org", p.org, body="Signed.")
        await t.act(conn, p.developer)
        assert await t.run(conn, COUNT, e=engagement) == 3
        confirmed = "SELECT count(*) FROM engagement_events WHERE engagement_id = :e AND to_state = :s"
        assert await t.run(conn, confirmed, e=engagement, s="INTEREST_CONFIRMED") == 0
        await t.as_owner(conn)
        q = await t.parties(conn)
        later = await t.engage(conn, q, state="NDA_SIGNED")  # the owner's insert: a genesis at NDA_SIGNED
        await post(conn, later, q.developer, "developer")
        await post(conn, later, q.signatory, "org", q.org)


async def test_only_a_party_posts_as_themselves_on_their_own_side(owner_engine: AsyncEngine) -> None:
    """Given an open thread, When someone posts as another person, on the other side, as a viewer, from another
    organisation, as staff or with a forged organisation context, Then the tracker's one refusal (an engagement the
    caller cannot see) or the policy refuses it."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await opened(conn)
        for by, party, org, refusal, params_by in (
            (p.viewer, "org", p.org, RLS, None),  # viewers read, never post
            (p.developer, "org", None, RLS, None),  # the developer is not the organisation
            (p.owner, "developer", p.org, RLS, None),  # nor a member the developer
            (p.owner, "org", p.org, RLS, p.signatory),  # in someone else's name
            (p.staff, "org", None, RLS, None),  # staff read the engagement, never the thread
            (p.staff, "developer", None, RLS, None),
            (p.outsider, "developer", None, HIDDEN, None),
            (p.other_member, "org", p.other_org, HIDDEN, None),
            (p.owner, "org", p.other_org, HIDDEN, None),  # a forged organisation context
            (None, "developer", None, HIDDEN, p.developer),  # no user bound
        ):
            await t.act(conn, by, org)
            await t.expect(conn, MESSAGE, refusal, **message(engagement, params_by or by or p.developer, party))
        await t.act(conn, p.developer)
        assert await t.run(conn, COUNT, e=engagement) == 0


async def test_a_developer_who_is_also_a_member_never_posts_as_the_organisation(owner_engine: AsyncEngine) -> None:
    """Given an open thread whose developer is also an owner and signatory of the counterpart organisation, When they
    post as 'org' on their own engagement (with or without that organisation's context), Then the policy refuses it:
    one person never speaks for both sides; they still post as 'developer', and a member of the organisation who is
    not its developer still posts as 'org'."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await opened(conn)
        await t.as_owner(conn)
        await t.member(conn, p.org, p.developer, "{owner,signatory}")
        for org in (p.org, None):
            await refused(conn, engagement, p.developer, "org", RLS, org)
        await post(conn, engagement, p.developer, "developer", p.org)
        await post(conn, engagement, p.owner, "org", p.org)
        await t.act(conn, p.developer)
        parties = "SELECT array_agg(CAST(sender_party AS text) ORDER BY created_at, id) FROM engagement_messages"
        assert await t.run(conn, parties + " WHERE engagement_id = :e", e=engagement) == ["developer", "org"]


@pytest.mark.parametrize("end", TERMINAL)
async def test_the_thread_is_read_only_after_each_end(owner_engine: AsyncEngine, end: str) -> None:
    """Given an open thread with a message, When the engagement ends (each terminal state), Then nobody posts any more
    (the owner neither) and both parties, the viewer included, still read the message."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await opened(conn)
        await post(conn, engagement, p.developer, "developer", body="Here is the pilot plan.")
        if end == "CLOSED":
            await t.walk(conn, p, engagement, "CLOSED")
        else:
            actor, role, org, reason = {
                "DECLINED": (p.signatory, "signatory", p.org, "NOT_PRIORITY"),
                "WITHDRAWN": (p.developer, "developer", None, None),
                "EXPIRED": (None, "system", None, "CONTACT_NOT_MADE"),
                "TERMINATED": (p.owner, "owner", p.org, None),
            }[end]
            await t.act(conn, actor or p.developer, org)  # the expiry job is bound to the developer
            await t.append(conn, engagement, actor, role, end.lower(), "INTEREST_CONFIRMED", end, reason=reason)
        await t.act(conn, p.developer)
        assert await t.state_of(conn, engagement) == end
        await refused(conn, engagement, p.developer, "developer", READ_ONLY)
        await refused(conn, engagement, p.owner, "org", READ_ONLY, p.org)
        await t.as_owner(conn)
        await t.expect(conn, MESSAGE, READ_ONLY, **message(engagement, p.developer, "developer"))
        for reader, org in ((p.developer, None), (p.owner, p.org), (p.viewer, p.org)):
            await t.act(conn, reader, org)
            assert await t.run(conn, COUNT, e=engagement) == 1, reader


async def test_the_parties_read_the_thread_and_nobody_else_does(owner_engine: AsyncEngine) -> None:
    """Given messages from both sides, Then the developer and every member of the organisation (viewer included, with
    or without an organisation context) read both; staff admin, who reads the engagement and its notes, reads none
    (D-57 (4)); another developer, another organisation, a forged context and an unbound session read none."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await opened(conn)
        await post(conn, engagement, p.developer, "developer")
        await post(conn, engagement, p.signatory, "org", p.org)
        for reader, org, seen in (
            (p.developer, None, 2),
            (p.owner, p.org, 2),
            (p.owner, None, 2),
            (p.viewer, p.org, 2),
            (p.finance, p.org, 2),
            (p.staff, None, 0),
            (p.outsider, None, 0),
            (p.other_member, p.other_org, 0),
            (p.owner, p.other_org, 0),
            (None, None, 0),
        ):
            await t.act(conn, reader, org)
            assert await t.run(conn, COUNT, e=engagement) == seen, (reader, org)
        await t.act(conn, p.staff)
        assert await t.run(conn, "SELECT count(*) FROM engagements WHERE id = :e", e=engagement) == 1
        await t.as_owner(conn)
        await t.run(conn, "UPDATE memberships SET status = 'removed' WHERE user_id = :u", u=p.viewer)
        await t.act(conn, p.viewer, p.org)  # a member who left reads nothing
        assert await t.run(conn, COUNT, e=engagement) == 0


REDACT = "UPDATE engagement_messages SET body = '[redacted]', redacted_at = now(), redacted_by = :by"


async def test_messages_are_append_only_and_their_body_is_checked(owner_engine: AsyncEngine) -> None:
    """A message is 1 to 4,000 characters, not blank, never pre-redacted and never dated by its sender; the app holds
    no UPDATE, DELETE or TRUNCATE; for the owner too DELETE and TRUNCATE are refused and an UPDATE is only the one
    redaction of the body (D-54), once."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await opened(conn)
        await t.act(conn, p.developer)
        for body, constraint in (
            ("", "ck_engagement_messages_body_length"),
            ("  \n\t ", "ck_engagement_messages_body_length"),
            ("x" * 4001, "ck_engagement_messages_body_length"),
            ("[redacted]", "ck_engagement_messages_redaction_complete"),
        ):
            await t.expect(conn, MESSAGE, constraint, **message(engagement, p.developer, "developer", body))
        await t.expect(
            conn,
            "INSERT INTO engagement_messages (id, engagement_id, sender_user_id, sender_party, body, created_at)"
            " VALUES (uuid7(), :e, :by, 'developer', 'Backdated', now() - interval '1 day')",
            DENIED,
            e=engagement,
            by=p.developer,
        )
        await post(conn, engagement, p.developer, "developer", body="x" * 4000)
        await post(conn, engagement, p.developer, "developer", body="Call me on +254 700 000 000")
        where = " WHERE engagement_id = :e"
        for sql in (
            "UPDATE engagement_messages SET body = 'Edited'" + where,
            REDACT + where,  # D-54: the app cannot redact
            "DELETE FROM engagement_messages" + where,
            "TRUNCATE engagement_messages",
        ):
            await t.expect(conn, sql, DENIED, e=engagement, by=p.staff)
        await t.as_owner(conn)  # the triggers hold for every role
        guard = "only by its redaction"
        for sql, refusal in (
            ("UPDATE engagement_messages SET body = 'Edited'" + where, guard),
            ("UPDATE engagement_messages SET body = '[redacted]'" + where, guard),  # without who and when
            (REDACT + ", sender_party = 'org'" + where, guard),  # and something else
            ("DELETE FROM engagement_messages" + where, "append-only"),
            ("TRUNCATE engagement_messages CASCADE", "append-only"),  # the attachments' key refuses it uncascaded
        ):
            await t.expect(conn, sql, refusal, e=engagement, by=p.staff)
        one = (
            " WHERE id = (SELECT id FROM engagement_messages WHERE engagement_id = :e ORDER BY created_at DESC, id DESC"
        )
        one += " LIMIT 1)"
        assert await t.rowcount(conn, REDACT + one, e=engagement, by=p.staff) == 1
        await t.expect(conn, REDACT + one, guard, e=engagement, by=p.staff)  # once, for good
        await t.act(conn, p.developer)
        bodies = "SELECT array_agg(body ORDER BY created_at, id) FROM engagement_messages WHERE engagement_id = :e"
        assert await t.run(conn, bodies, e=engagement) == ["x" * 4000, "[redacted]"]


REPORT = "SELECT case_id, created FROM app_report_message(:m, CAST(:reasons AS text[]))"
READ_REPORTED = "SELECT message_id, engagement_id, CAST(sender_party AS text), body FROM app_reported_message(:c)"
LIMITED = f"at most {MESSAGE_REPORTS_PER_DAY} message reports a day"


async def _report(conn: AsyncConnection, message_id: UUID, reasons: list[str] | None = None) -> tuple[UUID, bool]:
    row = (await conn.execute(sa.text(REPORT), {"m": message_id, "reasons": reasons or ["abuse"]})).one()
    return row.case_id, row.created


async def test_a_report_files_one_case_and_shares_that_message_with_staff(owner_engine: AsyncEngine) -> None:
    """Given two messages of the developer, When a member reports them (D-57 (4)), Then each report files one case
    (a repeat returns it, created false), a non-party, staff and an unbound session cannot report, the app cannot
    insert a message report itself, and staff (admin or moderator) read that one message through
    app_reported_message, nobody else does, and no other case yields a message."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await opened(conn)
        first = await post(conn, engagement, p.developer, "developer", body="Pay me outside the platform.")
        second = await post(conn, engagement, p.developer, "developer", body="Second.")
        await t.act(conn, p.owner, p.org)
        case, created = await _report(conn, first)
        assert created is True
        assert await _report(conn, first) == (case, False)  # once per reporter and message
        await t.act(conn, p.developer)  # the sender's side may report too (another reporter, another case)
        assert (await _report(conn, first))[0] != case
        for by, org in ((p.outsider, None), (p.other_member, p.other_org), (p.staff, None), (None, None)):
            await t.act(conn, by, org)
            await t.expect(conn, REPORT, "no message of the caller's", m=first, reasons=["spam"])
        await t.act(conn, p.owner, p.org)
        direct = (
            "INSERT INTO moderation_cases (id, subject_type, subject_id, reasons, source, reporter_id)"
            " VALUES (uuid7(), :type, :subject, ARRAY['spam'], 'report', :by)"
        )
        await t.expect(conn, direct, RLS, type="message", subject=second, by=p.owner)
        await t.run(conn, direct, type="proposal", subject=p.proposal, by=p.owner)  # other reports are unchanged
        for reader in (p.owner, p.developer, p.outsider):
            await t.act(conn, reader)
            await t.expect(conn, READ_REPORTED, "staff admin or moderator only", c=case)
        await t.act(conn, p.staff)
        shared = (await conn.execute(sa.text(READ_REPORTED), {"c": case})).one()
        assert tuple(shared) == (first, engagement, "developer", "Pay me outside the platform.")
        others = "SELECT count(*) FROM app_reported_message((SELECT id FROM moderation_cases WHERE subject_id = :s))"
        assert await t.run(conn, others, s=p.proposal) == 0
        assert await t.run(conn, COUNT, e=engagement) == 0  # still never the thread
        await t.as_owner(conn)
        duplicate = direct.replace("uuid7()", ":id")
        await t.expect(
            conn, duplicate, "uq_moderation_cases_message_report", id=uuid7(), type="message", subject=first, by=p.owner
        )


async def test_a_reporter_files_at_most_ten_message_reports_a_day(owner_engine: AsyncEngine) -> None:
    """Given twelve messages, When a member reports them, Then ten go and the eleventh is refused (54000) whatever the
    caller asks: the function takes no limit, so a call that names one does not exist; a repeat is never limited;
    another reporter has their own ten; the window is the last 24 hours (a report older than that frees one place)."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await opened(conn)
        messages = [await post(conn, engagement, p.developer, "developer", body=f"Message {n}.") for n in range(12)]
        await t.act(conn, p.owner, p.org)
        assert MESSAGE_REPORTS_PER_DAY == 10
        cases = [(await _report(conn, message))[0] for message in messages[:10]]
        savepoint = await conn.begin_nested()
        with pytest.raises(DBAPIError, match=LIMITED) as refused:
            await conn.execute(sa.text(REPORT), {"m": messages[10], "reasons": ["spam"]})
        await savepoint.rollback()
        assert isinstance(refused.value.orig, psycopg.Error)
        assert refused.value.orig.diag.sqlstate == "54000"  # program_limit_exceeded
        raised = "SELECT * FROM app_report_message(:m, ARRAY['spam'], 100)"
        await t.expect(conn, raised, r"function app_report_message\(.*\) does not exist", m=messages[10])
        assert await _report(conn, messages[0]) == (cases[0], False)  # a repeat is never limited
        await t.act(conn, p.signatory, p.org)  # another reporter
        assert (await _report(conn, messages[10]))[1] is True
        await t.as_owner(conn)
        aged = "UPDATE moderation_cases SET created_at = now() - interval '24 hours 1 second' WHERE id = :c"
        await t.run(conn, aged, c=cases[0])
        await t.act(conn, p.owner, p.org)
        assert (await _report(conn, messages[10]))[1] is True  # 24 hours on, one place is free again
        await t.expect(conn, REPORT, LIMITED, m=messages[11], reasons=["spam"])


async def test_a_report_gives_only_listed_reason_codes(owner_engine: AsyncEngine) -> None:
    """A report's reasons are one or more of the fixed codes (MESSAGE_REPORT_REASONS: spam, abuse, contact_details,
    confidential, other), each kept once; free text, an unknown or differently spelt code, an empty or NULL list, a
    NULL code or a nested array are refused (22023) and file nothing."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await opened(conn)
        message = await post(conn, engagement, p.developer, "developer", body="Call me on +254 700 000 000.")
        await t.act(conn, p.owner, p.org)
        for reasons in (
            ["Pay me outside the platform"],
            ["harassment"],
            ["SPAM"],
            ["spam", "He shared his number"],
            [],
            None,
            ["spam", None],
        ):
            savepoint = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="reasons are one or more of") as refused:
                await conn.execute(sa.text(REPORT), {"m": message, "reasons": reasons})
            await savepoint.rollback()
            assert isinstance(refused.value.orig, psycopg.Error)
            assert refused.value.orig.diag.sqlstate == "22023", reasons  # invalid_parameter_value
        nested = "SELECT * FROM app_report_message(:m, ARRAY[ARRAY['spam'], ARRAY['abuse']])"
        await t.expect(conn, nested, "reasons are one or more of", m=message)
        assert (await _report(conn, message, [*MESSAGE_REPORT_REASONS, "spam"]))[1] is True
        await t.as_owner(conn)
        filed = "SELECT reasons FROM moderation_cases WHERE subject_id = :m"
        assert sorted(await t.run(conn, filed, m=message)) == sorted(MESSAGE_REPORT_REASONS)  # one case, each once
