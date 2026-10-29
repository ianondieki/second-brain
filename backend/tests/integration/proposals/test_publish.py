"""REQ-PROP-01 / REQ-PROV-01 / REQ-PROV-05 publishing through the API: the draft version is registered (database time,
the owner's handle, a certificate id), the three ownership attestations are recorded, the T2.4 pipeline is queued and,
run, makes the certificate and ``/verify`` work; a ``signal_events`` row and the audit event are written. Publishing
validates the draft first (AC-REPO-4/a) and the niche label renders on the teaser card. Editing a published proposal
starts version 2, registered with the previous version's hash."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.crypto.envelope import LocalKeyWrapper, Purpose, Sealed, open_data_key, open_sealed
from bridge.proposals import attestations
from bridge.provenance import service as provenance
from bridge.provenance.signing import LocalSigner
from bridge.provenance.tsa import TsaClient
from bridge.storage.objects import InMemoryObjectStore
from tests.integration import world as w
from tests.integration.proposals.helpers import (
    SECRET_APPROACH,
    Developers,
    ProposalWorld,
    create,
    draft_body,
    publish,
    published,
    rows,
    user_of,
)

Sessions = async_sessionmaker[AsyncSession]


async def run_pipeline(
    version_id: UUID,
    owner_id: UUID,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
) -> None:
    """What the worker does with the queued jobs (bridge.jobs.provenance)."""
    async with sessions() as s:
        assert await provenance.hash_manifest(s, version_id, owner_id, wrapper=wrapper, store=store)
    async with sessions() as s:
        assert await provenance.sign_manifest(s, version_id, owner_id, signer=signer)
    async with sessions() as s:
        assert await provenance.timestamp_manifest(s, version_id, owner_id, tsa=tsa)


async def manifest_of(owner_engine: AsyncEngine, wrapper: LocalKeyWrapper, version_id: str) -> bytes:
    """The registered manifest, decrypted from the version's Tier-2 row."""
    [row] = await rows(owner_engine, "SELECT * FROM proposal_confidential WHERE version_id = :v", v=version_id)
    key = await open_data_key(
        wrapper, wrapped=bytes(row.wrapped_dek), key_id=row.kms_key_id, proposal_id=row.proposal_id
    )
    sealed = Sealed(bytes(row.manifest_nonce), bytes(row.manifest_ciphertext))
    return open_sealed(key, sealed, proposal_id=row.proposal_id, version_id=row.version_id, purpose=Purpose.MANIFEST)


async def test_publishing_registers_the_version_end_to_end(
    developers: Developers,
    proposal_world: ProposalWorld,
    owner_engine: AsyncEngine,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
) -> None:
    owner = await developers(wrapper=wrapper)
    owner_id = user_of(owner)
    created = await create(owner, draft_body(proposal_world))
    pid, version_id = created["id"], created["draft"]["id"]

    response = await publish(owner, pid)
    assert response.status_code == 200, response.text
    body = response.json()
    cert_id = body["cert_id"]
    assert body == {
        "proposal_id": pid,
        "version_id": version_id,
        "version_no": 1,
        "cert_id": cert_id,
        "status": "published",
        "moderation": {"state": "clear", "message": None},
        "provenance": {
            "status": "timestamp_pending",
            "label": "Timestamp pending",
            "verify_path": f"/verify/{cert_id}",
        },
        "new_problem_id": None,
    }

    [version] = await rows(owner_engine, "SELECT * FROM proposal_versions WHERE id = :v", v=version_id)
    assert (version.status, version.cert_id, version.version_no) == ("registered", cert_id, 1)
    assert version.registered_at is not None
    [handle] = await rows(owner_engine, "SELECT handle FROM developer_profiles WHERE user_id = :u", u=owner_id)
    assert version.owner_handle == handle.handle
    [proposal] = await rows(owner_engine, "SELECT * FROM proposals WHERE id = :p", p=pid)
    assert (proposal.status, str(proposal.current_version_id), proposal.draft_version_id) == (
        "published",
        version_id,
        None,
    )
    assert (proposal.title, proposal.summary) == ("Cold-chain alerts", "An SMS goes out when a cooler warms up.")
    assert proposal.published_at is not None

    [attestation] = await rows(owner_engine, "SELECT * FROM attestations WHERE version_id = :v", v=version_id)
    assert (attestation.user_id, attestation.text_version) == (owner_id, attestations.VERSION)
    assert (attestation.created_it, attestation.not_owned_by_employer_or_client) == (True, True)
    assert attestation.no_third_party_confidential is True
    assert bytes(attestation.text_sha256) == attestations.text_digest()

    jobs = await rows(
        owner_engine, "SELECT task_name FROM procrastinate_jobs WHERE args->>'version_id' = :v", v=version_id
    )
    assert [j.task_name for j in jobs] == [provenance.TASK_HASH]
    [signal] = await rows(owner_engine, "SELECT * FROM signal_events WHERE item_id = :p", p=pid)
    assert signal.kind == "proposal_published"
    assert len(bytes(signal.actor_hash)) == 32
    [event] = await rows(
        owner_engine, "SELECT * FROM audit_events WHERE action = 'proposal.published' AND subject_id = :v", v=version_id
    )
    assert event.actor_user_id == owner_id
    assert event.payload == {
        "proposal_id": pid,
        "version_no": 1,
        "cert_id": cert_id,
        "moderation_state": "clear",
        "new_problem_id": None,
    }

    # Another signed-in user sees the teaser: Tier 1, the handle, the certificate id and the niche label (AC-REPO-4/a).
    reader = await developers(level="d0")
    card = (await reader.get(f"/api/proposals/{pid}")).json()
    assert card["owner_handle"] == handle.handle
    assert card["cert_id"] == cert_id
    assert card["teaser"]["niche"]["label"] == proposal_world.niche_label
    assert [p["id"] for p in card["problems"]] == [str(proposal_world.problem_id)]
    assert card["provenance"]["status"] == "timestamp_pending"

    # The worker registers the version; the certificate and /verify then work for it.
    await run_pipeline(UUID(version_id), owner_id, sessions, wrapper, store, signer, tsa)
    checked = (await reader.get(f"/api/verify/{cert_id}")).json()
    assert checked["status"] == "timestamped"
    [record] = await rows(
        owner_engine, "SELECT content_hash FROM provenance_records WHERE version_id = :v", v=version_id
    )
    assert checked["content_hash"] == bytes(record.content_hash).hex()
    pdf = await owner.get(f"/api/provenance/certificates/{cert_id}/certificate.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert (await reader.get(f"/api/proposals/{pid}")).json()["provenance"]["status"] == "timestamped"

    canonical = await manifest_of(owner_engine, wrapper, version_id)
    assert hashlib.sha256(canonical).digest() == bytes(record.content_hash)
    manifest = json.loads(canonical)
    assert [a["id"] for a in manifest["attestations"]] == [str(attestation.id)]
    assert manifest["tier2"]["approach"] == SECRET_APPROACH
    assert "draft" not in manifest["tier2"]
    assert manifest["tier1"]["problem_ids"] == [str(proposal_world.problem_id)]


async def test_publishing_validates_the_draft_first(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    """AC-REPO-4/a: without a linked Problem or a niche (or any required Tier-1 field) publishing fails."""
    owner = await developers()
    created = await create(owner, draft_body(proposal_world, link=False, niche_id=None, summary=None))
    refused = await publish(owner, created["id"])
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["code"] == "cannot_publish"
    assert {(e["field"], e["code"]) for e in detail["errors"]} == {
        ("niche_id", "required"),
        ("summary", "required"),
        ("problems", "problem_required"),
    }
    [draft] = await rows(
        owner_engine, "SELECT status, cert_id FROM proposal_versions WHERE proposal_id = :p", p=created["id"]
    )
    assert (draft.status, draft.cert_id) == ("draft", None)
    assert await rows(owner_engine, "SELECT id FROM attestations WHERE user_id = :u", u=user_of(owner)) == []


async def test_all_three_attestations_are_required(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    created = await create(owner, draft_body(proposal_world))
    refused = await publish(owner, created["id"], not_owned_by_employer_or_client=False)
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "attestations_required"
    assert refused.json()["detail"]["missing"] == ["not_owned_by_employer_or_client"]
    outdated = await owner.post(
        f"/api/me/proposals/{created['id']}/publish",
        json={
            "attestations": {
                "created_it": True,
                "not_owned_by_employer_or_client": True,
                "no_third_party_confidential": True,
            },
            "attestation_text_version": "2020-01-01.1",
        },
    )
    assert outdated.status_code == 409
    assert outdated.json()["detail"]["code"] == "attestation_text_outdated"
    assert await rows(owner_engine, "SELECT id FROM attestations WHERE user_id = :u", u=user_of(owner)) == []
    text_out = (await owner.get("/api/proposals/attestations")).json()
    assert text_out["version"] == attestations.VERSION
    assert [s["key"] for s in text_out["statements"]] == [
        "created_it",
        "not_owned_by_employer_or_client",
        "no_third_party_confidential",
    ]
    assert text_out["sha256"] == attestations.text_digest().hex()


async def test_editing_a_published_proposal_starts_the_next_version(
    developers: Developers,
    proposal_world: ProposalWorld,
    owner_engine: AsyncEngine,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
) -> None:
    owner = await developers(wrapper=wrapper)
    first = await published(owner, proposal_world)
    pid = first["proposal_id"]
    assert (await publish(owner, pid)).json()["detail"]["code"] == "nothing_to_publish"

    edited = await owner.patch(
        f"/api/me/proposals/{pid}", json={"teaser": {"title": "Cold-chain alerts v2"}, "confidential": {"notes": "v2"}}
    )
    assert edited.status_code == 200, edited.text
    mine = edited.json()
    assert mine["current"]["version_no"] == 1
    assert mine["current"]["teaser"]["title"] == "Cold-chain alerts"
    assert mine["draft"]["version_no"] == 2
    assert mine["draft"]["teaser"]["title"] == "Cold-chain alerts v2"
    assert mine["draft"]["confidential"]["approach"] == SECRET_APPROACH  # copied from version 1
    assert mine["draft"]["confidential"]["notes"] == "v2"
    assert [p["id"] for p in mine["draft"]["problems"]] == [str(proposal_world.problem_id)]

    reader = await developers(level="d0")
    assert (await reader.get(f"/api/proposals/{pid}")).json()["teaser"]["title"] == "Cold-chain alerts"

    second = (await publish(owner, pid)).json()
    assert (second["version_no"], second["status"]) == (2, "published")
    signals = await rows(owner_engine, "SELECT kind FROM signal_events WHERE item_id = :p ORDER BY ts, id", p=pid)
    assert [s.kind for s in signals] == ["proposal_published", "proposal_version_published"]
    assert second["cert_id"] != first["cert_id"]
    card = (await reader.get(f"/api/proposals/{pid}")).json()
    assert (card["teaser"]["title"], card["version_no"]) == ("Cold-chain alerts v2", 2)

    for version in (first, second):
        await run_pipeline(UUID(version["version_id"]), user_of(owner), sessions, wrapper, store, signer, tsa)
    hashes = {
        r.version_no: (r.content_hash, r.prev_version_hash)
        for r in await rows(
            owner_engine,
            "SELECT version_no, content_hash, prev_version_hash FROM proposal_versions WHERE proposal_id = :p",
            p=pid,
        )
    }
    assert hashes[2][1] == hashes[1][0]
    assert (await reader.get(f"/api/verify/{first['cert_id']}")).status_code == 200


async def test_only_a_linkable_problem_counts_at_publishing(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    """A linked problem rejected (or held) after it was linked no longer satisfies "at least one Problem"."""
    async with owner_engine.begin() as conn:
        author = await w.add_user(conn, f"gone-{uuid4().hex[:8]}@example.test", "Gone")
        problem_id = await w.add_problem(conn, author, proposal_world.niche_id)
    owner = await developers()
    body = draft_body(proposal_world, link=False)
    body["problem_ids"] = [str(problem_id)]
    created = await create(owner, body)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE problems SET status = 'rejected', moderation_state = 'rejected' WHERE id = :id"),
            {"id": problem_id},
        )
    refused = await publish(owner, created["id"])
    assert refused.status_code == 422
    assert [(e["field"], e["code"]) for e in refused.json()["detail"]["errors"]] == [("problems", "problem_required")]
