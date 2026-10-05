"""REQ-ENG-11 (P21-A4): the thread's files. An infected upload is refused and never stored; a file still pending its
scan is neither sent nor downloadable; a sent, clean file is downloaded by both parties (and the organisation's
viewer) through a link signed for each, short-lived and theirs only; a staged file is its uploader's alone.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge import clock
from bridge.engagements import message_files
from bridge.engagements.models import MAX_MESSAGE_ATTACHMENT_BYTES
from bridge.ids import uuid7
from bridge.storage.scanner import EICAR
from tests.integration.engagements.api_world import moved_clock
from tests.integration.engagements.thread_world import (
    PDF,
    code,
    post,
    posted,
    read,
    thread_at,
    thread_path,
    upload,
    uploaded,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def _row(owner_engine: AsyncEngine, attachment: UUID) -> dict[str, object] | None:
    async with owner_engine.connect() as conn:
        found = await conn.execute(
            text(
                "SELECT av_status::text AS av_status, message_id, object_key, file_name, size_bytes, sha256"
                " FROM engagement_message_attachments WHERE id = :id"
            ),
            {"id": attachment},
        )
        row = found.first()
        return None if row is None else dict(row._mapping)


async def _audits(owner_engine: AsyncEngine, action: str, engagement: UUID) -> list[dict[str, object]]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT payload FROM audit_events WHERE action = :a AND subject_id = :e ORDER BY seq"),
            {"a": action, "e": engagement},
        )
        return [dict(payload) for (payload,) in rows.all()]


async def test_a_clean_file_is_staged_sent_and_downloaded_by_the_parties_only(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given an open thread, When the developer stages a PDF and sends it, Then it is stored under ids only, listed on
    the message, and each party (the viewer included) downloads exactly its bytes through their own signed link."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        staged = await upload(s.dev, e, name="../Pilot plan v2.pdf")
        assert staged.status_code == 201, staged.text
        body = staged.json()
        file_id = UUID(body["id"])
        assert body["file_name"] == "Pilot plan v2.pdf"
        assert body["av_status"] == "clean"
        assert body["size_bytes"] == len(PDF)
        assert body["sha256"] == hashlib.sha256(PDF).hexdigest()
        row = await _row(owner_engine, file_id)
        assert row is not None
        assert row["object_key"] == f"messages/{e}/{file_id}"
        assert thread.store.objects[("uploads", f"messages/{e}/{file_id}")][0] == PDF
        [audited] = await _audits(owner_engine, "engagement.message_attachment_staged", e)
        assert audited["attachment_id"] == str(file_id)

        sent = await posted(s.dev, e, "The pilot plan, attached.", attachments=[file_id])
        assert [a["id"] for a in sent["attachments"]] == [str(file_id)]
        listed = (await read(s.owner, e))["items"][0]["attachments"]
        assert listed == [
            {
                "id": str(file_id),
                "file_name": "Pilot plan v2.pdf",
                "content_type": "application/pdf",
                "size_bytes": len(PDF),
            }
        ]
        for client in (s.dev, s.owner, thread.viewer):
            link = await client.get(thread_path(e, f"/{sent['id']}/attachments/{file_id}"))
            assert link.status_code == 200, link.text
            served = await client.get(link.json()["url"])
            assert served.status_code == 200, served.text
            assert served.content == PDF
            assert served.headers["content-type"].startswith("application/pdf")
            assert served.headers["content-disposition"].startswith("attachment;")
            assert "filename*=UTF-8''Pilot%20plan%20v2.pdf" in served.headers["content-disposition"]
            assert served.headers["x-content-type-options"] == "nosniff"
            assert "no-store" in served.headers["cache-control"]
        # a link is the caller's own: another party's copy of it is refused
        mine = (await s.dev.get(thread_path(e, f"/{sent['id']}/attachments/{file_id}"))).json()["url"]
        assert code(await s.owner.get(mine)) == (403, "link_invalid")
        assert code(await s.dev.get(mine.replace("sig=", "sig=0")[:-1])) == (403, "link_invalid")
        # the file is no longer the uploader's to remove
        assert code(await s.dev.delete(thread_path(e, f"/attachments/{file_id}"))) == (404, "not_found")


async def test_an_expired_or_tampered_link_is_refused(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        file_id = await uploaded(s.dev, e)
        sent = await posted(s.dev, e, "Attached.", attachments=[file_id])
        url = (await s.owner.get(thread_path(e, f"/{sent['id']}/attachments/{file_id}"))).json()["url"]
        later = clock.utcnow() + message_files.LINK_TTL + timedelta(seconds=5)
        monkeypatch.setattr(clock, "utcnow", lambda: later)
        assert code(await s.owner.get(url)) == (403, "link_expired")
        monkeypatch.undo()
        stretched = url.replace("expires=", "expires=9")
        assert code(await s.owner.get(stretched)) == (403, "link_invalid")
        thread.store.objects[("uploads", f"messages/{e}/{file_id}")] = (b"%PDF-changed", "application/pdf")
        assert code(await s.owner.get(url)) == (409, "file_changed")
        del thread.store.objects[("uploads", f"messages/{e}/{file_id}")]
        assert code(await s.owner.get(url)) == (404, "not_found")


async def test_an_infected_file_is_refused_never_stored_and_never_sent(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given the EICAR test file, When a party uploads it, Then 422 attachment_infected naming the refused upload,
    nothing is stored, the staged row is marked infected (unsendable; its uploader removes it) and the rejection is
    audited."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        refused = await upload(s.owner, e, b"plain text " + EICAR, content_type="text/plain", name="notes.txt")
        assert code(refused) == (422, "attachment_infected")
        assert not [key for key in thread.store.objects if key[1].startswith(f"messages/{e}/")]
        [audited] = await _audits(owner_engine, "engagement.message_attachment_rejected", e)
        assert audited["verdict"] == "infected"
        infected = UUID(str(audited["attachment_id"]))
        row = await _row(owner_engine, infected)
        assert row is not None
        assert row["av_status"] == "infected"
        assert refused.json()["detail"]["attachment_id"] == str(infected)
        assert code(await post(s.owner, e, "See notes.", attachments=[infected])) == (422, "attachment_infected")
        assert (await s.owner.delete(thread_path(e, f"/attachments/{infected}"))).status_code == 204
        assert await _row(owner_engine, infected) is None


async def test_a_file_pending_its_scan_is_neither_sent_nor_downloadable(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given a staged upload still pending its scan, When its uploader sends it or anyone asks for it, Then 409
    attachment_pending, and no link exists for a file that was never sent."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        pending = uuid7()
        async with owner_engine.begin() as conn:  # as the app, for the developer (the scan never ran)
            await conn.execute(text("SET LOCAL ROLE bridge_app"))
            await conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(world.developer)})
            await conn.execute(
                text(
                    "INSERT INTO engagement_message_attachments (id, engagement_id, uploader_user_id, file_name,"
                    " content_type, size_bytes, sha256, object_key) VALUES (:id, :e, :u, 'scan.pdf',"
                    " 'application/pdf', 10, :sha, :key)"
                ),
                {"id": pending, "e": e, "u": world.developer, "sha": bytes(32), "key": f"messages/{e}/{pending}"},
            )
        assert code(await post(s.dev, e, "Scan attached.", attachments=[pending])) == (409, "attachment_pending")
        sent = await posted(s.dev, e, "No file this time.")
        for client in (s.dev, s.owner):
            assert code(await client.get(thread_path(e, f"/{sent['id']}/attachments/{pending}"))) == (404, "not_found")


async def test_a_staged_file_is_its_uploaders_alone(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Another party can neither send nor remove someone's staged file; its uploader removes it (and its object)."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        file_id = await uploaded(s.dev, e, PNG, content_type="image/png", name="diagram.png")
        assert code(await post(s.owner, e, "Taking it.", attachments=[file_id])) == (422, "unknown_attachment")
        assert code(await s.owner.delete(thread_path(e, f"/attachments/{file_id}"))) == (404, "not_found")
        assert code(await post(s.dev, e, "Two of one.", attachments=[file_id, uuid7()])) == (422, "unknown_attachment")
        removed = await s.dev.delete(thread_path(e, f"/attachments/{file_id}"))
        assert removed.status_code == 204, removed.text
        assert await _row(owner_engine, file_id) is None
        assert ("uploads", f"messages/{e}/{file_id}") not in thread.store.objects
        assert code(await s.dev.delete(thread_path(e, f"/attachments/{file_id}"))) == (404, "not_found")


async def test_uploads_are_checked_for_size_type_name_and_count(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        too_big = b"%PDF-" + b"0" * MAX_MESSAGE_ATTACHMENT_BYTES
        assert code(await upload(s.dev, e, too_big)) == (413, "too_large")
        assert code(await upload(s.dev, e, b"")) == (422, "empty_file")
        assert code(await upload(s.dev, e, b"MZ\x90\x00", content_type="application/x-msdownload")) == (
            422,
            "unsupported_file",
        )
        assert code(await upload(s.dev, e, b"not a pdf", content_type="application/pdf")) == (422, "unsupported_file")
        bad_name = await s.dev.post(
            thread_path(e, "/attachments"),
            content=PDF,
            headers={"Content-Type": "application/pdf", "X-File-Name": "%FF%FE"},
        )
        assert code(bad_name) == (422, "invalid_file_name")
        unnamed = await s.dev.post(
            thread_path(e, "/attachments"), content=PDF, headers={"Content-Type": "application/pdf"}
        )
        assert unnamed.json()["file_name"] == "attachment"
        staged = [UUID(unnamed.json()["id"])]
        staged += [await uploaded(s.dev, e) for _ in range(message_files.STAGED_PER_ENGAGEMENT - 1)]
        assert code(await upload(s.dev, e)) == (409, "too_many_staged")
        six = await post(s.dev, e, "Six files.", attachments=staged[:6])
        assert six.status_code == 422
        five = await posted(s.dev, e, "Five files.", attachments=staged[:5])
        assert len(five["attachments"]) == 5
        assert (await upload(s.dev, e)).status_code == 201  # five of the ten went out with the message


async def test_a_file_staged_more_than_a_day_ago_is_not_sent(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given a file staged two days ago (the shared clock moved), When its uploader sends it, Then 422
    attachment_expired and the message is not posted; a fresh upload is sent."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        old = await uploaded(s.dev, e)
        async with moved_clock(owner_engine) as advance:
            await advance(2)
            assert code(await post(s.dev, e, "The plan.", attachments=[old])) == (422, "attachment_expired")
            assert (await read(s.dev, e))["items"] == []
            fresh = await uploaded(s.dev, e)
            assert len((await posted(s.dev, e, "The plan.", attachments=[fresh]))["attachments"]) == 1
