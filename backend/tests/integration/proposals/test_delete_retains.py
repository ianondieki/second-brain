"""AC-IP-6 (REQ-PROV-05), backend half: "deleting" a registered proposal hides it (no Tier-1 read returns it, and it
cannot change) but keeps its versions, Tier 2, manifest, provenance record, proofs, attestations and audit events;
the certificate and ``/verify`` keep working. A proposal that was never published is removed with its attachments.
The frontend states this before the owner confirms (``frontend/e2e/delete-notice.spec.ts``, with the screens)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.crypto.envelope import LocalKeyWrapper
from bridge.provenance.signing import LocalSigner
from bridge.provenance.tsa import TsaClient
from bridge.storage.objects import InMemoryObjectStore
from tests.integration.proposals.helpers import (
    Developers,
    ProposalWorld,
    create,
    draft_body,
    publish,
    published,
    rows,
    store_of,
    user_of,
)
from tests.integration.proposals.test_attachments import PDF, upload
from tests.integration.proposals.test_publish import run_pipeline

EVIDENCE = {
    "proposal_versions": "SELECT id, status, content_hash, cert_id FROM proposal_versions WHERE proposal_id = :p",
    "proposal_confidential": "SELECT version_id, manifest_ciphertext FROM proposal_confidential WHERE proposal_id = :p",
    "provenance_records": (
        "SELECT r.id, r.status, r.tsa_token FROM provenance_records r JOIN proposal_versions v ON v.id = r.version_id"
        " WHERE v.proposal_id = :p"
    ),
    "attestations": (
        "SELECT a.id FROM attestations a JOIN proposal_versions v ON v.id = a.version_id WHERE v.proposal_id = :p"
    ),
    "proposal_attachments": "SELECT id, sha256 FROM proposal_attachments WHERE proposal_id = :p",
}


async def evidence(owner_engine: AsyncEngine, proposal_id: str) -> dict[str, list[Any]]:
    return {name: [tuple(r) for r in await rows(owner_engine, sql, p=proposal_id)] for name, sql in EVIDENCE.items()}


async def test_deleting_a_registered_proposal_hides_it_and_keeps_the_evidence(
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
    await upload(owner, pid, PDF)
    out = (await publish(owner, pid)).json()
    await run_pipeline(UUID(out["version_id"]), user_of(owner), sessions, wrapper, store, signer, tsa)
    before = await evidence(owner_engine, pid)
    assert all(before.values())
    audit_sql = "SELECT id, event_hash FROM audit_events WHERE subject_id = :v ORDER BY id"
    audit_before = await rows(owner_engine, audit_sql, v=out["version_id"])

    removed = await owner.delete(f"/api/me/proposals/{pid}")
    assert removed.status_code == 200, removed.text
    assert removed.json()["status"] == "hidden"
    assert "/verify" in removed.json()["message"]

    assert await evidence(owner_engine, pid) == before
    assert await rows(owner_engine, audit_sql, v=out["version_id"]) == audit_before
    assert len(store_of(owner).objects) == 1  # the registered attachment's object stays
    [proposal] = await rows(owner_engine, "SELECT status, hidden_at FROM proposals WHERE id = :p", p=pid)
    assert proposal.status == "hidden"
    assert proposal.hidden_at is not None
    hidden_sql = "SELECT actor_user_id FROM audit_events WHERE action = 'proposal.hidden' AND subject_id = :p"
    [event] = await rows(owner_engine, hidden_sql, p=pid)
    assert event.actor_user_id == user_of(owner)

    reader = await developers(level="d0")
    assert (await reader.get(f"/api/proposals/{pid}")).status_code == 404
    verified = await reader.get(f"/api/verify/{out['cert_id']}")
    assert verified.status_code == 200
    assert verified.json()["status"] == "timestamped"
    assert (await owner.get(f"/api/provenance/certificates/{out['cert_id']}/certificate.pdf")).status_code == 200
    assert [i["status"] for i in (await owner.get("/api/me/proposals")).json()["items"]] == ["hidden"]

    for attempt in (
        owner.patch(f"/api/me/proposals/{pid}", json={"teaser": {"title": "back"}}),
        publish(owner, pid),
        upload(owner, pid, PDF),
    ):
        refused = await attempt
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "proposal_hidden"
    assert (await owner.delete(f"/api/me/proposals/{pid}")).json()["status"] == "hidden"  # idempotent
    other = await developers()
    assert (await other.delete(f"/api/me/proposals/{pid}")).status_code == 404


async def test_a_never_published_draft_is_removed(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    pid = (await create(owner, draft_body(proposal_world)))["id"]
    assert (await upload(owner, pid, PDF)).status_code == 201
    removed = await owner.delete(f"/api/me/proposals/{pid}")
    assert removed.json()["status"] == "deleted"
    assert await rows(owner_engine, "SELECT id FROM proposals WHERE id = :p", p=pid) == []
    assert all(not found for found in (await evidence(owner_engine, pid)).values())
    assert store_of(owner).objects == {}
    [event] = await rows(
        owner_engine, "SELECT id FROM audit_events WHERE action = 'proposal.draft_deleted' AND subject_id = :p", p=pid
    )
    assert event.id is not None
    assert (await owner.get(f"/api/me/proposals/{pid}")).status_code == 404


async def test_a_published_proposal_with_a_pending_draft_is_hidden_not_deleted(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    first = await published(owner, proposal_world)
    pid = first["proposal_id"]
    await owner.patch(f"/api/me/proposals/{pid}", json={"teaser": {"title": "v2 draft"}})
    assert (await owner.delete(f"/api/me/proposals/{pid}")).json()["status"] == "hidden"
    sql = "SELECT version_no, status FROM proposal_versions WHERE proposal_id = :p"
    versions = await rows(owner_engine, sql, p=pid)
    assert sorted(tuple(v) for v in versions) == [(1, "registered"), (2, "draft")]
