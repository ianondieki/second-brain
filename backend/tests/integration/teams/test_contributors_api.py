"""REQ-DEV-03 (D-62 (a); P22 card C, C5): contributors. The owner credits the other developer of one of their team
threads (never anyone else); a contributor may remove their own credit; the idea page and the organisation's proposal
view list handles; the certificate's data and PDF text carry "Contributors: <handles>" after the Owner row; the
manifest and its content hash are untouched (``manifest_version`` stays "1") and the verify page shows the same; the
registrant stays the owner."""

from __future__ import annotations

import hashlib
import json
import os
from uuid import UUID

from bridge.crypto.envelope import LocalKeyWrapper, Purpose, Sealed, open_data_key, open_sealed
from bridge.db import bind_tenant, create_session_factory
from bridge.provenance.certificate import load_certificate
from bridge.provenance.service import hash_manifest
from bridge.storage.objects import InMemoryObjectStore
from tests.integration.provenance.builders import Built, registered_version
from tests.integration.teams.api_world import (
    Clients,
    TeamsDb,
    audits,
    code,
    developer,
    handle_of,
    niche,
    org_only,
    owner_rows,
    owner_run,
    problem,
    team,
)
from tests.unit.provenance.test_certificate import pdf_text


async def registered(teams: TeamsDb, wrapper: LocalKeyWrapper, shared: UUID) -> Built:
    """A published, registered and hashed version of a new proposal whose owner turned Peers on and likes ``shared``."""
    tier2 = {"approach": "LoRa sensors report every five minutes.", "pricing": "KES 25,000 setup"}
    built = await registered_version(teams.owner, wrapper, tier2=tier2, attachments=0)
    await owner_run(teams, "UPDATE developer_profiles SET peers_visible = true WHERE user_id = :u", u=built.owner_id)
    await owner_run(
        teams,
        "INSERT INTO developer_niches (user_id, niche_id, kind) VALUES (:u, :n, 'liked')",
        u=built.owner_id,
        n=shared,
    )
    async with create_session_factory(teams.app)() as session:
        assert await hash_manifest(
            session, built.version_id, built.owner_id, wrapper=wrapper, store=InMemoryObjectStore()
        )
    return built


async def manifest(teams: TeamsDb, wrapper: LocalKeyWrapper, version_id: UUID) -> bytes:
    [row] = await owner_rows(teams, "SELECT * FROM proposal_confidential WHERE version_id = :v", v=version_id)
    key = await open_data_key(
        wrapper, wrapped=bytes(row.wrapped_dek), key_id=row.kms_key_id, proposal_id=row.proposal_id
    )
    sealed = Sealed(bytes(row.manifest_nonce), bytes(row.manifest_ciphertext))
    return open_sealed(key, sealed, proposal_id=row.proposal_id, version_id=row.version_id, purpose=Purpose.MANIFEST)


async def content_hash(teams: TeamsDb, version_id: UUID) -> bytes:
    [row] = await owner_rows(teams, "SELECT content_hash FROM provenance_records WHERE version_id = :v", v=version_id)
    return bytes(row.content_hash)


async def test_c5_the_owner_credits_a_counterpart_on_the_idea_and_the_certificate(
    teams: TeamsDb, as_user: Clients
) -> None:
    wrapper = LocalKeyWrapper(os.urandom(32))
    shared, _ = await niche(teams, "credit")
    built = await registered(teams, wrapper, shared)
    brian = await developer(teams, "brian", liked=(shared,))
    carol = await developer(teams, "carol", liked=(shared,))  # a peer, no thread yet
    owner, b = await as_user(built.owner_id), await as_user(brian)
    owner.app.state.key_wrapper = wrapper  # type: ignore[attr-defined]
    reader = await as_user((await org_only(teams)).reviewer)
    path = f"/api/me/ideas/{built.proposal_id}/contributors"
    hash_before = await content_hash(teams, built.version_id)
    verify_before = (await reader.get(f"/api/verify/{built.cert_id}")).json()

    assert code(await owner.post(path, json={"user_id": str(brian)})) == (404, "not_a_counterpart")
    await team(owner, b, await problem(teams))
    assert code(await owner.post(path, json={"user_id": str(carol)})) == (404, "not_a_counterpart")
    assert code(await owner.post(path, json={"user_id": str(built.owner_id)})) == (404, "not_a_counterpart")
    assert code(await b.post(path, json={"user_id": str(built.owner_id)})) == (404, "not_found")  # not the owner
    added = await owner.post(path, json={"user_id": str(brian)})
    assert added.status_code == 201, added.text
    handle = await handle_of(teams, brian)
    assert added.json()["contributors"] == [handle]
    assert [(i["user_id"], i["handle"]) for i in added.json()["items"]] == [(str(brian), handle)]
    assert code(await owner.post(path, json={"user_id": str(brian)})) == (409, "already_contributor")
    [event] = await audits(teams, "proposal.contributor_added", built.owner_id)
    assert event.payload["user_id"] == str(brian)

    mine = (await owner.get(f"/api/me/proposals/{built.proposal_id}")).json()
    assert mine["contributors"] == [handle]
    card = (await reader.get(f"/api/proposals/{built.proposal_id}")).json()
    assert card["contributors"] == [handle]
    assert card["owner_handle"] == await handle_of(teams, built.owner_id)  # the registrant stays the owner
    assert [UUID(i["proposal_id"]) for i in (await b.get("/api/me/contributions")).json()["items"]] == [
        built.proposal_id
    ]

    pdf = await owner.get(f"/api/provenance/certificates/{built.cert_id}/certificate.pdf")
    assert pdf.status_code == 200
    text = pdf_text(pdf.content)
    assert "Contributors" in text
    assert handle in text
    assert text.index("Owner") < text.index("Contributors")
    async with create_session_factory(teams.app)() as session:
        await bind_tenant(session, user_id=built.owner_id)
        data = await load_certificate(
            session, cert_id=built.cert_id, user_id=built.owner_id, public_base_url="https://bridge.test"
        )
    assert data is not None
    assert data.contributors == (handle,)

    # the manifest and its hash are untouched; the verify page shows the same
    assert await content_hash(teams, built.version_id) == hash_before
    stored = await manifest(teams, wrapper, built.version_id)
    assert hashlib.sha256(stored).digest() == hash_before
    assert json.loads(stored)["manifest_version"] == "1"
    assert handle.encode() not in stored
    assert b"contributor" not in stored.lower()
    assert (await reader.get(f"/api/verify/{built.cert_id}")).json() == verify_before

    # the contributor leaves (for good); the certificate no longer lists them
    assert (await b.delete(f"/api/me/contributions/{built.proposal_id}")).status_code == 204
    assert code(await b.delete(f"/api/me/contributions/{built.proposal_id}")) == (404, "not_found")
    assert (await owner.get(f"/api/me/proposals/{built.proposal_id}")).json()["contributors"] == []
    pdf = await owner.get(f"/api/provenance/certificates/{built.cert_id}/certificate.pdf")
    assert "Contributors" not in pdf_text(pdf.content)
    assert code(await owner.post(path, json={"user_id": str(brian)})) == (409, "already_contributor")
    assert await content_hash(teams, built.version_id) == hash_before


async def test_c5_the_owner_removes_a_credit(teams: TeamsDb, as_user: Clients) -> None:
    wrapper = LocalKeyWrapper(os.urandom(32))
    shared, _ = await niche(teams, "remove")
    built = await registered(teams, wrapper, shared)
    first = await developer(teams, "first", liked=(shared,))
    second = await developer(teams, "second", liked=(shared,))
    owner = await as_user(built.owner_id)
    path = f"/api/me/ideas/{built.proposal_id}/contributors"
    for user in (first, second):
        await team(owner, await as_user(user), await problem(teams))
        assert (await owner.post(path, json={"user_id": str(user)})).status_code == 201
    listed = (await owner.get(path)).json()
    assert listed["contributors"] == [await handle_of(teams, first), await handle_of(teams, second)]
    assert (await owner.delete(f"{path}/{first}")).status_code == 204
    assert code(await owner.delete(f"{path}/{first}")) == (404, "not_found")
    assert (await owner.get(path)).json()["contributors"] == [await handle_of(teams, second)]
    other = await as_user(second)
    assert code(await other.get(path)) == (404, "not_found")  # only the owner manages the credit
    assert code(await other.delete(f"{path}/{second}")) == (404, "not_found")
    removed = await audits(teams, "proposal.contributor_removed", built.owner_id)
    assert removed[0].payload == {"user_id": str(first), "by_contributor": False}


async def test_c5_a_block_never_hides_a_contributors_handle_from_the_owner(teams: TeamsDb, as_user: Clients) -> None:
    """The owner's list takes each handle from the credit itself (app_contributor_handles), so a block between the two
    (here the contributor blocks the owner) never shows as a missing handle; the credit stays (D-62)."""
    wrapper = LocalKeyWrapper(os.urandom(32))
    shared, _ = await niche(teams, "blocked")
    built = await registered(teams, wrapper, shared)
    first = await developer(teams, "kept", liked=(shared,))
    second = await developer(teams, "blocks", liked=(shared,))
    owner = await as_user(built.owner_id)
    path = f"/api/me/ideas/{built.proposal_id}/contributors"
    blocker = await as_user(second)
    for client in (await as_user(first), blocker):
        await team(owner, client, await problem(teams))
        assert (await owner.post(path, json={"user_id": str(client.user_id)})).status_code == 201  # type: ignore[attr-defined]
    assert (await blocker.post("/api/me/blocks", json={"user_id": str(built.owner_id)})).status_code == 204
    [block] = await owner_rows(
        teams, "SELECT blocked_user_id FROM developer_blocks WHERE blocker_user_id = :u", u=second
    )
    assert block.blocked_user_id == built.owner_id
    listed = (await owner.get(path)).json()
    handles = [await handle_of(teams, first), await handle_of(teams, second)]
    assert listed["contributors"] == handles
    assert [(i["user_id"], i["handle"]) for i in listed["items"]] == [
        (str(first), handles[0]),
        (str(second), handles[1]),
    ]
