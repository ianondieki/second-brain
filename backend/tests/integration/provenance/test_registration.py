"""REQ-PROV-01 / AC-IP-1: publishing queues the registration; the three steps produce a manifest whose recomputed
SHA-256 equals ``content_hash``, an Ed25519 signature, an RFC 3161 token that ``openssl ts -verify`` accepts, and one
``proposal.version_registered`` audit event. Steps are idempotent; "Timestamp pending" holds until the token is stored.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.crypto.envelope import LocalKeyWrapper, Purpose, Sealed, open_sealed
from bridge.db import bind_tenant
from bridge.models.enums import ProvenanceStatus
from bridge.provenance import service
from bridge.provenance.service import (
    RegistrationError,
    RegistrationPendingError,
    enqueue_registration,
    hash_manifest,
    sign_manifest,
    status_label,
    timestamp_manifest,
)
from bridge.provenance.signing import LocalSigner, manifest_message, verify_signature
from bridge.provenance.tsa import TsaClient, TsaUnavailableError
from bridge.storage.objects import InMemoryObjectStore
from tests.integration.provenance.builders import TIER2, Built, registered_version
from tests.openssl_tsa import LocalTsa

Sessions = async_sessionmaker[AsyncSession]


async def fetch(engine: AsyncEngine, sql: str, **params: object) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).one_or_none()


async def jobs_for(engine: AsyncEngine, version_id: UUID) -> list[tuple[str, dict[str, str], str | None, str]]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT task_name, args, lock, queue_name FROM procrastinate_jobs"
                    " WHERE args->>'version_id' = :v ORDER BY id"
                ),
                {"v": str(version_id)},
            )
        ).all()
    return [(r.task_name, r.args, r.lock, r.queue_name) for r in rows]


async def register(
    built: Built,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
) -> None:
    async with sessions() as s:
        assert await hash_manifest(s, built.version_id, built.owner_id, wrapper=wrapper, store=store)
    async with sessions() as s:
        assert await sign_manifest(s, built.version_id, built.owner_id, signer=signer)
    async with sessions() as s:
        assert await timestamp_manifest(s, built.version_id, built.owner_id, tsa=tsa)


def stored_manifest(built: Built, ciphertext: bytes, nonce: bytes) -> bytes:
    return open_sealed(
        built.key,
        Sealed(nonce, ciphertext),
        proposal_id=built.proposal_id,
        version_id=built.version_id,
        purpose=Purpose.MANIFEST,
    )


async def test_publishing_registers_the_version_end_to_end(
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
    local_tsa: LocalTsa,
    tmp_path: Path,
) -> None:
    built = await registered_version(owner_engine, wrapper, attachments=2)

    # The publish flow's one call, in its own (owner-bound) transaction.
    async with sessions() as s:
        await bind_tenant(s, user_id=built.owner_id)
        job_id = await enqueue_registration(s, built.version_id)
        await s.commit()
    assert job_id > 0
    lock = f"provenance:{built.version_id}"
    args = {"version_id": str(built.version_id), "owner_id": str(built.owner_id)}
    assert await jobs_for(owner_engine, built.version_id) == [(service.TASK_HASH, args, lock, "provenance")]

    await register(built, sessions, wrapper, store, signer, tsa)
    assert [j[0] for j in await jobs_for(owner_engine, built.version_id)] == [
        service.TASK_HASH,
        service.TASK_SIGN,
        service.TASK_TIMESTAMP,
    ]

    record = await fetch(owner_engine, "SELECT * FROM provenance_records WHERE version_id = :v", v=built.version_id)
    version = await fetch(owner_engine, "SELECT * FROM proposal_versions WHERE id = :v", v=built.version_id)
    tier2 = await fetch(owner_engine, "SELECT * FROM proposal_confidential WHERE version_id = :v", v=built.version_id)
    content_hash = bytes(record.content_hash)
    assert record.status == ProvenanceStatus.TIMESTAMPED
    assert status_label(record.status) == "Timestamped"
    assert record.cert_id == built.cert_id
    assert bytes(version.content_hash) == content_hash
    assert version.manifest_version == "1"
    assert version.prev_version_hash is None

    # AC-IP-1: the stored manifest (Tier-2 row and evidence object) hashes to content_hash.
    manifest = stored_manifest(built, bytes(tier2.manifest_ciphertext), bytes(tier2.manifest_nonce))
    assert hashlib.sha256(manifest).digest() == content_hash
    evidence = json.loads(await store.get("evidence", record.evidence_s3_key))
    assert evidence["format"] == "bridge-sealed-manifest-v1"
    assert evidence["content_hash"] == content_hash.hex()
    assert evidence["kms_key_id"] == built.key.key_id
    from_evidence = stored_manifest(
        built, base64.b64decode(evidence["ciphertext"]), base64.b64decode(evidence["nonce"])
    )
    assert from_evidence == manifest
    assert str(built.owner_id) not in record.evidence_s3_key
    assert TIER2["how"].encode() not in await store.get("evidence", record.evidence_s3_key)

    # What the manifest holds: Tier 1, Tier 2, attachment hashes, a salted owner ref, attestations; no names.
    document = json.loads(manifest)
    salt = (await fetch(owner_engine, "SELECT subject_salt FROM users WHERE id = :u", u=built.owner_id)).subject_salt
    assert document["owners"] == [
        {"ref": hashlib.sha256(bytes(salt) + built.owner_id.bytes).hexdigest(), "split_bps": 10000}
    ]
    assert document["tier2"] == TIER2
    assert sorted(a["sha256"] for a in document["attachments"]) == sorted(h.hex() for h in built.attachment_hashes)
    assert document["tier1"]["problem_ids"] == [str(built.problem_id)]
    assert len(document["attestations"]) == 1
    assert document["cert_id"] == built.cert_id
    assert "dev-handle" not in manifest.decode()

    # The signature verifies with the published key; the .tsr verifies with openssl.
    assert record.key_id == signer.key_id
    assert verify_signature(signer.public_key, manifest_message(content_hash), bytes(record.signature))
    assert local_tsa.verify(bytes(record.tsa_token), digest=content_hash).returncode == 0
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_bytes(manifest)
    tsr_file = tmp_path / "token.tsr"
    tsr_file.write_bytes(bytes(record.tsa_token))
    by_data = local_tsa.run(
        "ts", "-verify", "-data", str(manifest_file), "-in", str(tsr_file), "-CAfile", str(local_tsa.ca_pem)
    )
    assert by_data.returncode == 0, by_data.stderr.decode(errors="replace")
    assert record.tsa_serial.startswith("0x")
    assert record.tsa_url == "http://tsa.test/tsr"

    # One audit event, ids and digests only.
    events = await _events(owner_engine, built.version_id)
    assert len(events) == 1
    assert events[0].chain_id == "global"
    assert events[0].payload["content_hash"] == content_hash.hex()
    assert events[0].payload["cert_id"] == built.cert_id
    assert TIER2["how"] not in json.dumps(events[0].payload)


async def _events(engine: AsyncEngine, version_id: UUID) -> list[Any]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    text(
                        "SELECT chain_id, actor_kind, payload FROM audit_events"
                        " WHERE action = 'proposal.version_registered' AND subject_id = :v"
                    ),
                    {"v": version_id},
                )
            ).all()
        )


async def test_every_step_is_idempotent(
    owner_engine: AsyncEngine,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
) -> None:
    built = await registered_version(owner_engine, wrapper)
    await register(built, sessions, wrapper, store, signer, tsa)
    before = await fetch(owner_engine, "SELECT * FROM provenance_records WHERE version_id = :v", v=built.version_id)
    async with sessions() as s:
        assert not await hash_manifest(s, built.version_id, built.owner_id, wrapper=wrapper, store=store)
    async with sessions() as s:
        assert not await sign_manifest(s, built.version_id, built.owner_id, signer=signer)
    async with sessions() as s:
        assert not await timestamp_manifest(s, built.version_id, built.owner_id, tsa=tsa)
    after = await fetch(owner_engine, "SELECT * FROM provenance_records WHERE version_id = :v", v=built.version_id)
    assert after == before
    assert len(await _events(owner_engine, built.version_id)) == 1
    assert len(await jobs_for(owner_engine, built.version_id)) == 2  # sign and timestamp queued once each


async def test_the_next_version_links_the_previous_hash(
    owner_engine: AsyncEngine,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
) -> None:
    first = await registered_version(owner_engine, wrapper)
    second = await registered_version(owner_engine, wrapper, previous=first, tier2={"how": "v2"})
    async with sessions() as s:
        with pytest.raises(RegistrationPendingError, match="previous version"):
            await hash_manifest(s, second.version_id, second.owner_id, wrapper=wrapper, store=store)
    await register(first, sessions, wrapper, store, signer, tsa)
    await register(second, sessions, wrapper, store, signer, tsa)
    v1 = await fetch(owner_engine, "SELECT content_hash FROM proposal_versions WHERE id = :v", v=first.version_id)
    v2 = await fetch(owner_engine, "SELECT prev_version_hash FROM proposal_versions WHERE id = :v", v=second.version_id)
    assert bytes(v2.prev_version_hash) == bytes(v1.content_hash)
    tier2 = await fetch(owner_engine, "SELECT * FROM proposal_confidential WHERE version_id = :v", v=second.version_id)
    document = json.loads(stored_manifest(second, bytes(tier2.manifest_ciphertext), bytes(tier2.manifest_nonce)))
    assert document["prev_version_hash"] == bytes(v1.content_hash).hex()
    assert document["version_no"] == 2


async def test_drafts_and_other_owners_are_refused(
    owner_engine: AsyncEngine, sessions: Sessions, wrapper: LocalKeyWrapper, store: InMemoryObjectStore
) -> None:
    draft = await registered_version(owner_engine, wrapper, register=False)
    other = await registered_version(owner_engine, wrapper)
    async with sessions() as s:
        await bind_tenant(s, user_id=draft.owner_id)
        with pytest.raises(RegistrationError, match="drafts are not evidence"):
            await enqueue_registration(s, draft.version_id)
    async with sessions() as s:
        await bind_tenant(s, user_id=draft.owner_id)
        with pytest.raises(RegistrationError, match="not visible"):
            await enqueue_registration(s, uuid_not_there())
    async with sessions() as s:
        with pytest.raises(RegistrationError, match="drafts are not evidence"):
            await hash_manifest(s, draft.version_id, draft.owner_id, wrapper=wrapper, store=store)
    async with sessions() as s:
        with pytest.raises(RegistrationError, match="not visible to its owner"):
            await hash_manifest(s, other.version_id, draft.owner_id, wrapper=wrapper, store=store)
    assert store.objects == {}


def uuid_not_there() -> UUID:
    return UUID(int=1)


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"attachment_status": "pending_scan"}, RegistrationPendingError, "not uploaded and scanned yet"),
        ({"attachment_status": "pending_upload"}, RegistrationPendingError, "not uploaded and scanned yet"),
        ({"attachment_status": "infected"}, RegistrationError, "failed its scan"),
        ({"tier2_plaintext": b"\xff not utf-8"}, RegistrationError, "not UTF-8 JSON"),
        ({"tier2_plaintext": b"[1, 2]"}, RegistrationError, "must be a JSON object"),
        ({"tier2": {"too_big": 2**60}}, RegistrationError, "cannot be canonicalised"),
        ({"tier2_row": False}, RegistrationError, "needs its Tier-2 row"),
    ],
)
async def test_versions_that_cannot_be_registered_yet_or_at_all(
    owner_engine: AsyncEngine,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    kwargs: dict[str, Any],
    error: type[Exception],
    message: str,
) -> None:
    built = await registered_version(owner_engine, wrapper, **kwargs)
    async with sessions() as s:
        with pytest.raises(error, match=message):
            await hash_manifest(s, built.version_id, built.owner_id, wrapper=wrapper, store=store)
    assert (
        await fetch(owner_engine, "SELECT 1 FROM provenance_records WHERE version_id = :v", v=built.version_id) is None
    )
    assert store.objects == {}


async def test_signing_waits_for_a_published_key(
    owner_engine: AsyncEngine, sessions: Sessions, wrapper: LocalKeyWrapper, store: InMemoryObjectStore
) -> None:
    built = await registered_version(owner_engine, wrapper)
    async with sessions() as s:
        await hash_manifest(s, built.version_id, built.owner_id, wrapper=wrapper, store=store)
    unpublished = LocalSigner(bytes(range(1, 33)))
    async with sessions() as s:
        with pytest.raises(RegistrationPendingError, match="register-key"):
            await sign_manifest(s, built.version_id, built.owner_id, signer=unpublished)


async def test_steps_out_of_order_and_missing_records(
    owner_engine: AsyncEngine,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
) -> None:
    built = await registered_version(owner_engine, wrapper)
    async with sessions() as s:
        with pytest.raises(RegistrationError, match="no provenance record"):
            await sign_manifest(s, built.version_id, built.owner_id, signer=signer)
    async with sessions() as s:
        with pytest.raises(RegistrationError, match="no provenance record"):
            await timestamp_manifest(s, built.version_id, built.owner_id, tsa=tsa)
    async with sessions() as s:
        await hash_manifest(s, built.version_id, built.owner_id, wrapper=wrapper, store=store)
    async with sessions() as s:
        with pytest.raises(RegistrationPendingError, match="not signed yet"):
            await timestamp_manifest(s, built.version_id, built.owner_id, tsa=tsa)


async def test_a_tsa_outage_leaves_timestamp_pending_until_a_retry_succeeds(
    owner_engine: AsyncEngine,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
) -> None:
    built = await registered_version(owner_engine, wrapper)
    async with sessions() as s:
        await hash_manifest(s, built.version_id, built.owner_id, wrapper=wrapper, store=store)
    async with sessions() as s:
        await sign_manifest(s, built.version_id, built.owner_id, signer=signer)
    down = TsaClient(["http://tsa.test/tsr"], transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    async with sessions() as s:
        with pytest.raises(TsaUnavailableError):
            await timestamp_manifest(s, built.version_id, built.owner_id, tsa=down)
    record = await fetch(
        owner_engine, "SELECT status, tsa_token FROM provenance_records WHERE version_id = :v", v=built.version_id
    )
    assert record.status == ProvenanceStatus.SIGNED
    assert record.tsa_token is None
    assert status_label(record.status) == "Timestamp pending"
    assert await _events(owner_engine, built.version_id) == []
    async with sessions() as s:
        assert await timestamp_manifest(s, built.version_id, built.owner_id, tsa=tsa)
    assert len(await _events(owner_engine, built.version_id)) == 1
