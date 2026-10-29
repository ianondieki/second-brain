"""REQ-PROV-01 / AC-IP-2 (database half): once the pipeline has registered a version, editing one byte of its stored
manifest, hash, signature or token, or deleting any of it, is refused, by the worker role that wrote it and by the
table owner alike (triggers of revision 0002; grants stop the app role before that)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.crypto.envelope import LocalKeyWrapper
from bridge.db import as_role, bind_tenant
from bridge.provenance.service import hash_manifest, sign_manifest, timestamp_manifest
from bridge.provenance.signing import LocalSigner
from bridge.provenance.tsa import TsaClient
from bridge.storage.objects import InMemoryObjectStore
from tests.integration.provenance.builders import Built, registered_version

FLIP = "set_byte({col}, 0, get_byte({col}, 0) # 1)"
EDIT_MANIFEST = f"UPDATE proposal_confidential SET manifest_ciphertext = {FLIP.format(col='manifest_ciphertext')}"
OWNER_EDITS = [
    EDIT_MANIFEST + " WHERE version_id = :v",
    f"UPDATE proposal_confidential SET ciphertext = {FLIP.format(col='ciphertext')} WHERE version_id = :v",
    "DELETE FROM proposal_confidential WHERE version_id = :v",
    f"UPDATE provenance_records SET content_hash = {FLIP.format(col='content_hash')} WHERE version_id = :v",
    f"UPDATE provenance_records SET signature = {FLIP.format(col='signature')} WHERE version_id = :v",
    f"UPDATE provenance_records SET tsa_token = {FLIP.format(col='tsa_token')} WHERE version_id = :v",
    "UPDATE provenance_records SET status = 'hashed' WHERE version_id = :v",
    "DELETE FROM provenance_records WHERE version_id = :v",
    f"UPDATE proposal_versions SET content_hash = {FLIP.format(col='content_hash')} WHERE id = :v",
    "UPDATE proposal_versions SET summary = summary || '!' WHERE id = :v",
    "DELETE FROM proposal_versions WHERE id = :v",
    "UPDATE attestations SET created_it = false WHERE version_id = :v",
]
WORKER_EDITS = [
    EDIT_MANIFEST + " WHERE version_id = :v",
    f"UPDATE provenance_records SET content_hash = {FLIP.format(col='content_hash')} WHERE version_id = :v",
    f"UPDATE provenance_records SET tsa_token = {FLIP.format(col='tsa_token')} WHERE version_id = :v",
    f"UPDATE provenance_records SET signature = {FLIP.format(col='signature')} WHERE version_id = :v",
    "DELETE FROM provenance_records WHERE version_id = :v",
]


@pytest.fixture(scope="module")
async def evidence(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    wrapper: LocalKeyWrapper,
    signer: LocalSigner,
    local_tsa: Any,
) -> Built:
    from bridge.db import create_session_factory

    sessions: async_sessionmaker[AsyncSession] = create_session_factory(app_engine)
    tsa = TsaClient([local_tsa.endpoint("http://tsa.test/tsr")], transport=local_tsa.transport())
    built = await registered_version(owner_engine, wrapper)
    async with sessions() as s:
        await hash_manifest(s, built.version_id, built.owner_id, wrapper=wrapper, store=InMemoryObjectStore())
    async with sessions() as s:
        await sign_manifest(s, built.version_id, built.owner_id, signer=signer)
    async with sessions() as s:
        await timestamp_manifest(s, built.version_id, built.owner_id, tsa=tsa)
    return built


SNAPSHOT = (
    "SELECT * FROM proposal_confidential WHERE version_id = :v",
    "SELECT * FROM provenance_records WHERE version_id = :v",
    "SELECT * FROM proposal_versions WHERE id = :v",
    "SELECT * FROM attestations WHERE version_id = :v",
)


async def snapshot(engine: AsyncEngine, built: Built) -> list[Any]:
    rows: list[Any] = []
    async with engine.connect() as conn:
        for sql in SNAPSHOT:
            rows.append((await conn.execute(text(sql), {"v": built.version_id})).all())
    assert all(rows)
    return rows


@pytest.mark.parametrize("statement", OWNER_EDITS, ids=range(len(OWNER_EDITS)))
async def test_the_table_owner_cannot_edit_or_delete_registered_evidence(
    owner_engine: AsyncEngine, evidence: Built, statement: str
) -> None:
    before = await snapshot(owner_engine, evidence)
    async with owner_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text(statement), {"v": evidence.version_id})
    assert await snapshot(owner_engine, evidence) == before


@pytest.mark.parametrize("statement", WORKER_EDITS, ids=range(len(WORKER_EDITS)))
async def test_the_worker_cannot_rewrite_what_it_registered(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, evidence: Built, statement: str
) -> None:
    before = await snapshot(owner_engine, evidence)
    async with AsyncSession(app_engine) as session:
        await bind_tenant(session, user_id=evidence.owner_id)
        async with session.begin():
            with pytest.raises(DBAPIError):
                async with as_role(session, "provenance_worker"):
                    await session.execute(text(statement), {"v": evidence.version_id})
    assert await snapshot(owner_engine, evidence) == before


async def test_the_app_role_changes_nothing_on_a_registered_version(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, evidence: Built
) -> None:
    before = await snapshot(owner_engine, evidence)
    async with AsyncSession(app_engine) as session:
        await bind_tenant(session, user_id=evidence.owner_id)
        deleted = await session.execute(text("DELETE FROM proposal_versions WHERE id = :v"), {"v": evidence.version_id})
        assert deleted.rowcount == 0  # type: ignore[attr-defined]  # policy: only drafts are deletable
        await session.commit()
    async with AsyncSession(app_engine) as session:
        await bind_tenant(session, user_id=evidence.owner_id)
        with pytest.raises(DBAPIError):
            await session.execute(
                text("UPDATE proposal_versions SET title = 'x' WHERE id = :v"), {"v": evidence.version_id}
            )
    async with AsyncSession(app_engine) as session:
        with pytest.raises(DBAPIError):  # no privilege at all on Tier 2 or on writing records
            await session.execute(
                text("SELECT 1 FROM proposal_confidential WHERE version_id = :v"), {"v": evidence.version_id}
            )
    assert await snapshot(owner_engine, evidence) == before
