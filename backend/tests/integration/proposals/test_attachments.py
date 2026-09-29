"""REQ-PROP-01 attachments (docs/spec/06 6.1; D-36): a PDF, PNG, JPG, Markdown or text file up to 20 MB is scanned by
the demo fake scanner, stored in the object store under an id-only key, and named only inside the sealed Tier-2
document; the EICAR test file is refused and not kept. A registered version's attachments are in its manifest and
are copied (not re-uploaded) into the next version."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.crypto.envelope import LocalKeyWrapper
from bridge.proposals.models import MAX_ATTACHMENT_BYTES
from bridge.provenance.signing import LocalSigner
from bridge.provenance.tsa import TsaClient
from bridge.storage.objects import InMemoryObjectStore
from bridge.storage.scanner import EICAR
from tests.integration.proposals.helpers import (
    Developers,
    ProposalWorld,
    create,
    draft_body,
    publish,
    rows,
    store_of,
    user_of,
)
from tests.integration.proposals.test_publish import manifest_of, run_pipeline

PDF = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"
FILE_NAME = "Pitch deck — v1.pdf"


async def upload(
    client: httpx.AsyncClient,
    proposal_id: str,
    data: bytes,
    *,
    content_type: str = "application/pdf",
    name: str = FILE_NAME,
) -> httpx.Response:
    return await client.post(
        f"/api/me/proposals/{proposal_id}/attachments",
        content=data,
        headers={"Content-Type": content_type, "X-File-Name": quote(name)},
    )


async def test_a_clean_file_is_stored_under_an_id_and_named_only_in_tier2(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    created = await create(owner, draft_body(proposal_world))
    pid = created["id"]
    response = await upload(owner, pid, PDF)
    assert response.status_code == 201, response.text
    attachment = response.json()
    assert attachment == {
        "id": attachment["id"],
        "file_name": FILE_NAME,
        "content_type": "application/pdf",
        "size_bytes": len(PDF),
        "sha256": hashlib.sha256(PDF).hexdigest(),
        "av_status": "clean",
    }
    key = f"attachments/{pid}/{attachment['id']}"
    assert store_of(owner).objects == {("uploads", key): (PDF, "application/pdf")}

    [row] = await rows(owner_engine, "SELECT * FROM proposal_attachments WHERE id = :a", a=attachment["id"])
    assert (row.av_status, row.size_bytes, bytes(row.sha256)) == ("clean", len(PDF), hashlib.sha256(PDF).digest())
    assert str(row.version_id) == created["draft"]["id"]
    assert "Pitch" not in json.dumps(row._asdict(), default=str)
    sql = "SELECT ciphertext FROM proposal_confidential WHERE version_id = :v"
    [tier2] = await rows(owner_engine, sql, v=row.version_id)
    assert b"Pitch" not in bytes(tier2.ciphertext)

    mine = (await owner.get(f"/api/me/proposals/{pid}")).json()
    assert mine["draft"]["confidential"]["attachments"] == [attachment]

    other = await developers()
    assert (await upload(other, pid, PDF)).status_code == 404


async def test_the_eicar_test_file_is_refused_and_not_kept(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    created = await create(owner, draft_body(proposal_world))
    refused = await upload(owner, created["id"], EICAR, content_type="text/plain", name="notes.txt")
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "attachment_infected"
    assert store_of(owner).objects == {}
    assert await rows(owner_engine, "SELECT id FROM proposal_attachments WHERE proposal_id = :p", p=created["id"]) == []
    [event] = await rows(
        owner_engine,
        "SELECT payload FROM audit_events WHERE action = 'proposal.attachment_rejected' AND subject_id = :p",
        p=created["id"],
    )
    assert event.payload == {"scanner": "fake-demo", "verdict": "infected", "signature": "Eicar-Test-Signature"}


async def test_types_sizes_and_names_are_checked(developers: Developers, proposal_world: ProposalWorld) -> None:
    owner = await developers()
    pid = (await create(owner, draft_body(proposal_world)))["id"]
    wrong_magic = await upload(owner, pid, PDF, content_type="image/png", name="x.png")
    assert (wrong_magic.status_code, wrong_magic.json()["detail"]["code"]) == (422, "unsupported_file")
    unsupported = await upload(owner, pid, b"PK\x03\x04", content_type="application/zip", name="x.zip")
    assert (unsupported.status_code, unsupported.json()["detail"]["code"]) == (422, "unsupported_file")
    not_utf8 = await upload(owner, pid, b"\xff\xfe\x00", content_type="text/plain", name="x.txt")
    assert not_utf8.json()["detail"]["code"] == "unsupported_file"
    empty = await upload(owner, pid, b"", name="x.pdf")
    assert (empty.status_code, empty.json()["detail"]["code"]) == (422, "empty_file")
    too_large = await upload(owner, pid, b"%PDF-" + bytes(MAX_ATTACHMENT_BYTES), name="big.pdf")
    assert (too_large.status_code, too_large.json()["detail"]["code"]) == (413, "too_large")
    bad_name = await owner.post(
        f"/api/me/proposals/{pid}/attachments",
        content=PDF,
        headers={"Content-Type": "application/pdf", "X-File-Name": "%FF%FE"},
    )
    assert bad_name.json()["detail"]["code"] == "invalid_file_name"
    pathy = await upload(owner, pid, b"# Notes\n", content_type="text/markdown; charset=utf-8", name="../../etc/a.md")
    assert pathy.status_code == 201
    assert pathy.json()["file_name"] == "a.md"
    assert store_of(owner).objects.keys() == {("uploads", f"attachments/{pid}/{pathy.json()['id']}")}


async def test_removing_a_draft_attachment_deletes_its_object(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    pid = (await create(owner, draft_body(proposal_world)))["id"]
    attachment = (await upload(owner, pid, PDF)).json()
    removed = await owner.delete(f"/api/me/proposals/{pid}/attachments/{attachment['id']}")
    assert removed.status_code == 204
    assert store_of(owner).objects == {}
    assert await rows(owner_engine, "SELECT id FROM proposal_attachments WHERE proposal_id = :p", p=pid) == []
    mine = (await owner.get(f"/api/me/proposals/{pid}")).json()
    assert mine["draft"]["confidential"]["attachments"] == []
    again = await owner.delete(f"/api/me/proposals/{pid}/attachments/{attachment['id']}")
    assert again.status_code == 404


async def test_registered_attachments_are_in_the_manifest_and_carried_to_the_next_version(
    developers: Developers,
    proposal_world: ProposalWorld,
    owner_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
) -> None:
    owner = await developers(wrapper=wrapper)
    pid = (await create(owner, draft_body(proposal_world)))["id"]
    attachment = (await upload(owner, pid, PDF)).json()
    first = (await publish(owner, pid)).json()
    await run_pipeline(UUID(first["version_id"]), user_of(owner), sessions, wrapper, store, signer, tsa)
    manifest = json.loads(await manifest_of(owner_engine, wrapper, first["version_id"]))
    assert [(a["id"], a["sha256"]) for a in manifest["attachments"]] == [(attachment["id"], attachment["sha256"])]
    assert manifest["tier2"]["attachments"] == [
        {"id": attachment["id"], "file_name": FILE_NAME, "object_key": f"attachments/{pid}/{attachment['id']}"}
    ]

    edited = (await owner.patch(f"/api/me/proposals/{pid}", json={"teaser": {"title": "v2"}})).json()
    [copied] = edited["draft"]["confidential"]["attachments"]
    assert copied["id"] != attachment["id"]
    assert (copied["file_name"], copied["sha256"], copied["av_status"]) == (FILE_NAME, attachment["sha256"], "clean")
    # Removing the copy from the draft keeps the registered version's object.
    assert (await owner.delete(f"/api/me/proposals/{pid}/attachments/{copied['id']}")).status_code == 204
    assert ("uploads", f"attachments/{pid}/{attachment['id']}") in store_of(owner).objects
    registered = (await owner.delete(f"/api/me/proposals/{pid}/attachments/{attachment['id']}")).status_code
    assert registered == 404  # a registered version's attachment is not the draft's to remove
