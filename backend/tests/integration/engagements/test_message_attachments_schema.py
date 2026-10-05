"""Revision 0008 (REQ-ENG-11): the thread's attachments and read markers.

- An upload is staged by a party who may post (never a viewer, another party's member or staff), while the thread is
  open; its uploader alone reads, scans and deletes it while staged; it joins only its uploader's own message, only
  clean, at most 5 per message; once sent every party reads it and it never changes or goes (but by the owner, the
  room left for D-54's erasure). Its file is 1 byte to 20 MB with a SHA-256, a file name without a path or control
  character, and its own object key, ``messages/<engagement>/<id>`` (never another object of the bucket).
- A read marker is a party's own: inserted, upserted and read by its user only, on an engagement they are a party of,
  at any stage.

The rule that an upload joins only a message of its own transaction commits, so it is in ``test_messages_race.py``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration.engagements import tracker as t
from tests.integration.engagements.test_messages_schema import HIDDEN, OPENS, READ_ONLY, RLS, opened, post

UPLOAD = (
    "INSERT INTO engagement_message_attachments (id, engagement_id, uploader_user_id, file_name, content_type,"
    " size_bytes, sha256, object_key) VALUES (:id, :e, :by, :name, 'application/pdf', :size, :sha, :key)"
)
TABLE = "engagement_message_attachments"
VERDICT = "UPDATE engagement_message_attachments SET av_status = CAST(:s AS av_status) WHERE id = :id"
SEND = "UPDATE engagement_message_attachments SET message_id = :m WHERE id = ANY(:ids) AND message_id IS NULL"
SEEN = "SELECT count(*) FROM engagement_message_attachments WHERE engagement_id = :e"
MAX_BYTES = 20 * 1024 * 1024


def upload_params(engagement: UUID, by: UUID, **overrides: Any) -> dict[str, Any]:
    upload_id = uuid7()
    params: dict[str, Any] = {
        "id": upload_id,
        "e": engagement,
        "by": by,
        "name": "pilot-plan.pdf",
        "size": 1024,
        "sha": bytes(range(32)),
        "key": f"messages/{engagement}/{upload_id}",
    }
    return params | overrides


async def upload(conn: AsyncConnection, engagement: UUID, by: UUID, verdict: str | None = "clean") -> UUID:
    """Stage an upload as ``by`` (the connection already acts for them; it is inserted ``pending_scan``) and, unless
    ``verdict`` is None, give it that scan verdict as the scan does (an UPDATE); returns its id."""
    params = upload_params(engagement, by)
    await t.run(conn, UPLOAD, **params)
    if verdict is not None:
        assert await t.rowcount(conn, VERDICT, s=verdict, id=params["id"]) == 1
    return UUID(str(params["id"]))


async def test_an_upload_is_staged_by_its_uploader_then_sent_with_their_message(owner_engine: AsyncEngine) -> None:
    """Given an open thread, When the developer stages uploads, Then only they read, scan and delete them; a staged
    upload joins only their own message and only clean; once sent both parties read it, the app can no longer change
    or delete it, and for the owner too it never changes (only the owner may delete it: D-54's room)."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await opened(conn)
        await t.act(conn, p.developer)
        plan = await upload(conn, engagement, p.developer, None)
        infected = await upload(conn, engagement, p.developer, None)
        pending = await upload(conn, engagement, p.developer, None)
        status = "SELECT array_agg(DISTINCT CAST(av_status AS text)) FROM engagement_message_attachments"
        assert await t.run(conn, status + " WHERE engagement_id = :e", e=engagement) == ["pending_scan"]
        for reader, org, seen in ((p.developer, None, 3), (p.owner, p.org, 0), (p.staff, None, 0)):
            await t.act(conn, reader, org)
            assert await t.run(conn, SEEN, e=engagement) == seen, reader
        await t.act(conn, p.developer)
        verdict = VERDICT
        assert await t.rowcount(conn, verdict, s="clean", id=plan) == 1
        assert await t.rowcount(conn, verdict, s="infected", id=infected) == 1
        await t.expect(conn, verdict, "a scan verdict \\(infected\\) is final", s="clean", id=infected)
        await t.expect(conn, verdict, "a scan verdict \\(clean\\) is final", s="infected", id=plan)
        await t.expect(
            conn,
            "UPDATE engagement_message_attachments SET file_name = 'x.pdf' WHERE id = :id",
            "permission denied",
            id=plan,
        )
        theirs = await post(conn, engagement, p.owner, "org", p.org)
        assert await t.rowcount(conn, SEND, m=theirs, ids=[plan]) == 0  # not the member's upload to send
        await t.act(conn, p.developer)
        await t.expect(conn, SEND, "its uploader's own message", m=theirs, ids=[plan])  # nor their message to join
        mine = await post(conn, engagement, p.developer, "developer", body="The plan is attached.")
        for unclean in (infected, pending):
            await t.expect(
                conn, SEND, "ck_engagement_message_attachments_attached_only_when_clean", m=mine, ids=[unclean]
            )
        assert await t.rowcount(conn, SEND, m=mine, ids=[plan]) == 1
        for reader, org, seen in (
            (p.developer, None, 3),
            (p.owner, p.org, 1),
            (p.viewer, p.org, 1),
            (p.staff, None, 0),
            (p.outsider, None, 0),
            (p.other_member, p.other_org, 0),
        ):
            await t.act(conn, reader, org)
            assert await t.run(conn, SEEN, e=engagement) == seen, reader
        await t.act(conn, p.developer)
        assert await t.rowcount(conn, verdict, s="infected", id=plan) == 0  # sent: nothing changes
        assert await t.rowcount(conn, "DELETE FROM engagement_message_attachments WHERE id = :id", id=plan) == 0
        assert await t.rowcount(conn, "DELETE FROM engagement_message_attachments WHERE id = :id", id=pending) == 1
        await t.act(conn, p.owner, p.org)  # a staged upload is its uploader's to delete
        assert await t.rowcount(conn, "DELETE FROM engagement_message_attachments WHERE id = :id", id=infected) == 0
        await t.as_owner(conn)
        for sql in (
            "UPDATE engagement_message_attachments SET av_status = 'infected' WHERE id = :id",
            "UPDATE engagement_message_attachments SET message_id = NULL WHERE id = :id",
        ):
            await t.expect(conn, sql, "a sent attachment never changes", id=plan)
        await t.expect(conn, "TRUNCATE engagement_message_attachments", "append-only")
        assert await t.rowcount(conn, "DELETE FROM engagement_message_attachments WHERE id = :id", id=plan) == 1


async def test_who_may_upload_and_what_an_upload_is(owner_engine: AsyncEngine) -> None:
    """Uploads come from a party who may post, as themselves, staged and pending (the app names neither a message nor
    a scan verdict on insert: a verdict is an UPDATE), while the thread is open; the file's size, digest, name and
    object key are checked (no path, no control character, no file name in the key)."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await opened(conn)
        for by, org, uploader, refusal in (
            (p.viewer, p.org, p.viewer, RLS),
            (p.staff, None, p.staff, RLS),
            (p.developer, None, p.owner, RLS),  # in someone else's name
            (p.outsider, None, p.outsider, HIDDEN),
            (p.other_member, p.other_org, p.other_member, HIDDEN),
            (p.owner, p.other_org, p.owner, HIDDEN),  # a forged organisation context
        ):
            await t.act(conn, by, org)
            await t.expect(conn, UPLOAD, refusal, **upload_params(engagement, uploader))
        await t.act(conn, p.developer)
        sent_upload = UPLOAD.replace("uploader_user_id,", "uploader_user_id, message_id,").replace(
            ":by,", ":by, uuid7(),"
        )
        await t.expect(conn, sent_upload, "permission denied", **upload_params(engagement, p.developer))
        claimed_clean = UPLOAD.replace("object_key)", "object_key, av_status)").replace(":key)", ":key, 'clean')")
        await t.expect(conn, claimed_clean, "permission denied", **upload_params(engagement, p.developer))
        for overrides, constraint in (
            ({"size": 0}, "size_limit"),
            ({"size": MAX_BYTES + 1}, "size_limit"),
            ({"sha": bytes(31)}, "sha256_length"),
            ({"name": "  "}, "file_name_valid"),
            ({"name": "../etc/passwd"}, "file_name_valid"),
            ({"name": "plan\\v2.pdf"}, "file_name_valid"),
            ({"name": "plan\x07.pdf"}, "file_name_valid"),
            ({"name": "x" * 256}, "file_name_valid"),
            ({"key": f"messages/{engagement}/Pilot Plan.pdf"}, "object_key_is_its_own"),
            ({"key": "/messages/x"}, "object_key_is_its_own"),
            ({"key": "m" * 201}, "object_key_is_its_own"),
        ):
            params = upload_params(engagement, p.developer) | overrides
            await t.expect(conn, UPLOAD, f"ck_engagement_message_attachments_{constraint}", **params)
        largest = upload_params(engagement, p.developer, size=MAX_BYTES, name="Pilot plan (final) v2.pdf")
        await t.run(conn, UPLOAD, **largest)
        again = upload_params(engagement, p.developer) | {"key": largest["key"]}  # another upload's object
        await t.expect(conn, UPLOAD, "ck_engagement_message_attachments_object_key_is_its_own", **again)
        await t.append(conn, engagement, p.developer, "developer", "withdraw", "INTEREST_CONFIRMED", "WITHDRAWN")
        await t.expect(conn, UPLOAD, READ_ONLY, **upload_params(engagement, p.developer))
        await t.as_owner(conn)
        q = await t.parties(conn)  # a thread that has not opened yet
        await t.act(conn, q.developer)
        early = await t.engage(conn, q)
        await t.expect(conn, UPLOAD, OPENS, **upload_params(early, q.developer))


async def test_an_upload_names_only_its_own_object(owner_engine: AsyncEngine) -> None:
    """The object key is the row's own, ``messages/<engagement>/<id>`` in the uuid text form, so an upload never names
    another object of the bucket: a proposal's file (``attachments/<proposal>/<attachment>``, Tier-2 included),
    another engagement's or another upload's, a deeper path, or the same ids spelt otherwise; for the owner neither."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await opened(conn)
        params = upload_params(engagement, p.developer)
        upload_id = params["id"]
        foreign = (
            f"attachments/{p.proposal}/{uuid7()}",  # bridge.proposals.editor.object_key: a proposal's file
            f"messages/{uuid7()}/{upload_id}",  # another engagement's
            f"messages/{engagement}/{uuid7()}",  # another upload's
            f"messages/{engagement}/{upload_id}/x",
            f"messages/{engagement.hex}/{upload_id.hex}",
            f"messages/{str(engagement).upper()}/{str(upload_id).upper()}",
        )
        for role in ("app", "owner"):
            if role == "app":
                await t.act(conn, p.developer)
            else:
                await t.as_owner(conn)
            for key in foreign:
                await t.expect(conn, UPLOAD, f"ck_{TABLE}_object_key_is_its_own", **(params | {"key": key}))
        await t.act(conn, p.developer)
        await t.run(conn, UPLOAD, **params)
        own = "SELECT object_key FROM engagement_message_attachments WHERE id = :id"
        assert await t.run(conn, own, id=upload_id) == f"messages/{engagement}/{upload_id}"


async def test_at_most_five_attachments_per_message(owner_engine: AsyncEngine) -> None:
    """Six clean uploads: sending all six with one message is refused (check_violation, constraint
    engagement_message_attachments_at_most_5), five go, and a sixth later is refused too."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await opened(conn)
        await t.act(conn, p.developer)
        uploads = [await upload(conn, engagement, p.developer) for _ in range(6)]
        message = await post(conn, engagement, p.developer, "developer", body="Six files.")
        savepoint = await conn.begin_nested()
        with pytest.raises(DBAPIError, match="at most 5 attachments per message") as refused:
            await conn.execute(sa.text(SEND), {"m": message, "ids": uploads})
        await savepoint.rollback()
        assert isinstance(refused.value.orig, psycopg.Error)
        assert refused.value.orig.diag.constraint_name == "engagement_message_attachments_at_most_5"
        assert await t.rowcount(conn, SEND, m=message, ids=uploads[:5]) == 5
        await t.expect(conn, SEND, "at most 5 attachments per message", m=message, ids=uploads[5:])
        sent = "SELECT count(*) FROM engagement_message_attachments WHERE message_id = :m"
        assert await t.run(conn, sent, m=message) == 5


READ = (
    "INSERT INTO engagement_message_reads (engagement_id, user_id, last_read_at) VALUES (:e, :u, now())"
    " ON CONFLICT (engagement_id, user_id) DO UPDATE SET last_read_at = EXCLUDED.last_read_at"
)
MARKERS = "SELECT count(*) FROM engagement_message_reads WHERE engagement_id = :e"


async def test_a_party_keeps_only_their_own_read_marker(owner_engine: AsyncEngine) -> None:
    """Each party upserts and reads their own marker (before stage 3 too: reading is never gated); nobody writes,
    reads or moves another user's, a non-party gets the tracker's one refusal, staff the policy's, and the app never
    deletes a marker or changes its keys."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        await t.act(conn, p.developer)
        engagement = await t.engage(conn, p)  # SUBMITTED
        for reader, org in ((p.developer, None), (p.developer, None), (p.owner, p.org), (p.viewer, p.org)):
            await t.act(conn, reader, org)
            assert await t.rowcount(conn, READ, e=engagement, u=reader) == 1
            assert await t.run(conn, MARKERS, e=engagement) == 1  # their own only
        await t.act(conn, p.developer)
        await t.expect(conn, READ, RLS, e=engagement, u=p.owner)
        moved = "UPDATE engagement_message_reads SET last_read_at = now() WHERE user_id = :u"
        assert await t.rowcount(conn, moved, u=p.owner) == 0
        for by, org, refusal in (
            (p.outsider, None, HIDDEN),
            (p.other_member, p.other_org, HIDDEN),
            (p.owner, p.other_org, HIDDEN),
            (p.staff, None, RLS),
        ):
            await t.act(conn, by, org)
            await t.expect(conn, READ, refusal, e=engagement, u=by)
        await t.act(conn, p.developer)
        for sql in (
            "DELETE FROM engagement_message_reads WHERE engagement_id = :e",
            "UPDATE engagement_message_reads SET user_id = user_id WHERE engagement_id = :e",
            "UPDATE engagement_message_reads SET engagement_id = engagement_id WHERE engagement_id = :e",
        ):
            await t.expect(conn, sql, "permission denied", e=engagement)
        await t.as_owner(conn)
        assert await t.run(conn, MARKERS, e=engagement) == 3


PURGE = "SELECT object_key FROM app_purge_stale_message_uploads(:now)"
OWNER_UPLOAD = UPLOAD.replace("object_key)", "object_key, message_id, av_status, created_at)").replace(
    ":key)", ":key, :m, CAST(:status AS av_status), :at)"
)


async def _owner_upload(
    conn: AsyncConnection, engagement: UUID, by: UUID, at: datetime, message: UUID | None = None
) -> str:
    """As the owner: an upload of ``by`` dated ``at`` (staged, or sent with ``message``); returns its object key."""
    await t.as_owner(conn)
    params = upload_params(engagement, by) | {"m": message, "status": "clean", "at": at}
    await t.run(conn, OWNER_UPLOAD, **params)
    return str(params["key"])


async def test_the_purge_job_deletes_staged_uploads_that_can_never_be_sent(owner_engine: AsyncEngine) -> None:
    """Given staged uploads on an open thread (fresh, exactly 24 hours old, older) and on an ended one, and sent
    attachments on both (an old one too), When the purge job runs with no user bound, Then it deletes exactly the
    staged uploads older than 24 hours or of an ended engagement and returns their object keys (the job then deletes
    the objects); fresh staged uploads and every sent attachment stay, and a re-run deletes nothing more. An upload
    older than 24 hours can no longer join a message, so nothing the job deletes could have been sent. A signed-in
    session and a missing time are refused."""
    async with t.as_app(owner_engine) as conn:
        now: datetime = await t.run(conn, "SELECT app_clock_now()")
        day = timedelta(hours=24)
        p, engagement = await opened(conn)
        await t.as_owner(conn)
        q, ended = await opened(conn)
        await t.act(conn, p.developer)
        fresh = await upload(conn, engagement, p.developer, None)
        sent = await post(conn, engagement, p.developer, "developer", body="The plan.")
        old_sent = await _owner_upload(conn, engagement, p.developer, now - 2 * day, sent)
        boundary = await _owner_upload(conn, engagement, p.developer, now - day)
        stale = await _owner_upload(conn, engagement, p.owner, now - day - timedelta(seconds=1))
        stale_mine = await _owner_upload(conn, engagement, p.developer, now - 2 * day)
        await t.act(conn, p.developer)
        late = await post(conn, engagement, p.developer, "developer", body="Two days on.")
        stale_id = await t.run(
            conn, "SELECT id FROM engagement_message_attachments WHERE object_key = :k", k=stale_mine
        )
        await t.expect(conn, SEND, "within 24 hours of its upload", m=late, ids=[stale_id])
        await t.act(conn, q.developer)
        ended_staged = await upload(conn, ended, q.developer)
        ended_message = await post(conn, ended, q.developer, "developer", body="Before I withdraw.")
        ended_sent = await upload(conn, ended, q.developer)
        assert await t.rowcount(conn, SEND, m=ended_message, ids=[ended_sent]) == 1
        await t.append(conn, ended, q.developer, "developer", "withdraw", "INTEREST_CONFIRMED", "WITHDRAWN")
        for by in (p.developer, q.developer):
            await t.act(conn, by)
            await t.expect(conn, PURGE, "the stale-upload purge job only, with no user bound", now=now)
        await t.act(conn, None)
        await t.expect(conn, PURGE, "name the time", now=None)

        def ours(keys: Iterable[str]) -> set[str]:
            return {key for key in keys if key.split("/")[1] in {str(engagement), str(ended)}}

        purged = ours(row.object_key for row in await conn.execute(sa.text(PURGE), {"now": now}))
        assert purged == {stale, stale_mine, f"messages/{ended}/{ended_staged}"}
        assert ours(row.object_key for row in await conn.execute(sa.text(PURGE), {"now": now})) == set()
        await t.as_owner(conn)
        left = "SELECT object_key FROM engagement_message_attachments WHERE engagement_id = ANY(:e)"
        assert ours((await conn.execute(sa.text(left), {"e": [engagement, ended]})).scalars()) == {
            f"messages/{engagement}/{fresh}",
            old_sent,
            boundary,
            f"messages/{ended}/{ended_sent}",
        }
