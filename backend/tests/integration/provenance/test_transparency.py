"""REQ-AUD-01 (Phase 2) / AC-IP-2: hourly RFC 3161 anchors of the audit chain heads (only heads that moved; the
tokens verify with openssl over each head's hash), and the nightly verification that publishes a signed Merkle root
of the chain heads, or nothing when a chain is broken. Runs on its own database: the shared one holds chains that
other tests break on purpose."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from datetime import date
from typing import Any
from uuid import uuid4

import httpx
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import create_session_factory
from bridge.ids import uuid7
from bridge.jobs import audit as audit_jobs
from bridge.jobs import provenance as provenance_jobs
from bridge.provenance.signing import LocalSigner, register_public_key, root_message, verify_signature
from bridge.provenance.transparency import (
    ChainHead,
    ChainVerificationError,
    anchor_chain_heads,
    root_over,
    verify_and_publish_root,
)
from bridge.provenance.tsa import TsaClient, TsaError
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.integration.provenance.test_verify_api import client
from tests.openssl_tsa import LocalTsa


@pytest.fixture(scope="module")
def fresh_url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_anchor_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        run_alembic(url, lambda config: command.upgrade(config, "head"))
        yield url
    finally:
        drop_database(admin_url, name)


@pytest.fixture(scope="module")
async def engines(fresh_url: URL) -> AsyncIterator[dict[str, AsyncEngine]]:
    made = {role: role_engine(fresh_url, role) for role in ("bridge_app", "bridge_owner", "audit_reader")}
    yield made
    for engine in made.values():
        await engine.dispose()


@pytest.fixture(scope="module")
async def fresh_signer(engines: dict[str, AsyncEngine]) -> LocalSigner:
    signer = LocalSigner(os.urandom(32))
    async with engines["bridge_owner"].begin() as conn:
        await register_public_key(conn, signer)
    return signer


class CountingTsa:
    """The local openssl TSA behind an httpx transport that counts calls and can fail chosen digests."""

    def __init__(self, local_tsa: LocalTsa) -> None:
        self.local_tsa = local_tsa
        self.calls = 0
        self.fail_all = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail_all:
            return httpx.Response(503)
        return self.local_tsa.handler(request)

    def client(self) -> TsaClient:
        return TsaClient(["http://tsa.test/tsr"], transport=httpx.MockTransport(self.handler))


async def append(engine: AsyncEngine, chain_id: str, n: int = 1) -> None:
    for i in range(n):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO audit_events (id, chain_id, seq, actor_kind, action, payload, prev_hash, event_hash)"
                    " VALUES (:id, :chain, 0, 'system', 'test.event', CAST(:payload AS jsonb), ''::bytea, ''::bytea)"
                ),
                {"id": uuid7(), "chain": chain_id, "payload": json.dumps({"n": i})},
            )


async def heads(engine: AsyncEngine) -> list[ChainHead]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT DISTINCT ON (chain_id) chain_id, seq, event_hash FROM audit_events"
                    " ORDER BY chain_id, seq DESC"
                )
            )
        ).all()
    return [ChainHead(r.chain_id, r.seq, bytes(r.event_hash)) for r in rows]


async def anchors(engine: AsyncEngine) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text("SELECT * FROM chain_anchors ORDER BY chain_id, seq"))).all())


async def test_the_hourly_anchor_timestamps_each_moved_head_once(
    engines: dict[str, AsyncEngine], local_tsa: LocalTsa
) -> None:
    owner, app, reader = engines["bridge_owner"], engines["bridge_app"], engines["audit_reader"]
    sessions = create_session_factory(app)
    tsa = CountingTsa(local_tsa)
    await append(owner, "org:anchor-a", 3)
    await append(owner, "user:anchor-b", 2)

    async with sessions() as s:
        first = await anchor_chain_heads(s, tsa.client())
    assert {(h.chain_id, h.seq) for h in first.anchored} == {("org:anchor-a", 3), ("user:anchor-b", 2)}
    assert tsa.calls == 2
    stored = await anchors(reader)
    for row in stored:
        result = local_tsa.verify(bytes(row.tsa_token), digest=bytes(row.event_hash))
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert row.tsa_serial.startswith("0x")

    async with sessions() as s:
        again = await anchor_chain_heads(s, tsa.client())
    assert again.anchored == []
    assert tsa.calls == 2  # nothing moved: no TSA call at all
    assert len(await anchors(reader)) == 2

    await append(owner, "org:anchor-a")
    await append(owner, "global-anchor-c")
    await append(owner, "global-anchor-d")
    async with sessions() as s:
        limited = await anchor_chain_heads(s, tsa.client(), limit=2)
    assert len(limited.anchored) == 2
    async with sessions() as s:
        rest = await anchor_chain_heads(s, tsa.client())
    assert len(rest.anchored) == 1
    assert {(r.chain_id, r.seq) for r in await anchors(reader)} >= {("org:anchor-a", 3), ("org:anchor-a", 4)}


async def test_a_tsa_outage_anchors_nothing_and_fails_the_run(
    engines: dict[str, AsyncEngine], local_tsa: LocalTsa
) -> None:
    sessions = create_session_factory(engines["bridge_app"])
    tsa = CountingTsa(local_tsa)
    tsa.fail_all = True
    await append(engines["bridge_owner"], "org:anchor-outage")
    before = len(await anchors(engines["audit_reader"]))
    async with sessions() as s:
        with pytest.raises(TsaError, match="no chain head could be timestamped"):
            await anchor_chain_heads(s, tsa.client())
    assert len(await anchors(engines["audit_reader"])) == before
    tsa.fail_all = False
    async with sessions() as s:
        report = await anchor_chain_heads(s, tsa.client())
    assert ("org:anchor-outage", 1) in {(h.chain_id, h.seq) for h in report.anchored}


async def test_the_anchor_task_uses_the_job_runtime(engines: dict[str, AsyncEngine], local_tsa: LocalTsa) -> None:
    await append(engines["bridge_owner"], "org:anchor-task")
    tsa = CountingTsa(local_tsa)
    provenance_jobs.use_runtime(
        provenance_jobs.ProvenanceRuntime(
            session_factory=create_session_factory(engines["bridge_app"]), tsa=tsa.client()
        )
    )
    try:
        await provenance_jobs.anchor_chain_heads(timestamp=0)
    finally:
        provenance_jobs.use_runtime(None)
    assert ("org:anchor-task", 1) in {(r.chain_id, r.seq) for r in await anchors(engines["audit_reader"])}


async def test_the_nightly_verification_publishes_a_signed_root(
    engines: dict[str, AsyncEngine], fresh_signer: LocalSigner
) -> None:
    owner, app, reader = engines["bridge_owner"], engines["bridge_app"], engines["audit_reader"]
    await append(owner, "org:nightly", 2)
    day = date(2026, 9, 27)
    async with create_session_factory(app)() as s:
        report = await verify_and_publish_root(reader, s, fresh_signer, day)
    assert report.published
    assert report.merkle_root == root_over(await heads(reader))
    async with owner.connect() as conn:
        row = (await conn.execute(text("SELECT * FROM transparency_roots WHERE day = :d"), {"d": day})).one()
    assert bytes(row.merkle_root) == report.merkle_root
    assert row.key_id == fresh_signer.key_id
    assert verify_signature(fresh_signer.public_key, root_message(day, report.merkle_root), bytes(row.signature))

    async with create_session_factory(app)() as s:
        again = await verify_and_publish_root(reader, s, fresh_signer, day)
    assert not again.published

    async with client(app, None) as c:
        listed = (await c.get("/api/transparency")).json()["roots"]
        one = (await c.get("/api/transparency?limit=1")).json()["roots"]
    assert listed[0]["day"] == "2026-09-27"
    assert listed[0]["merkle_root"] == report.merkle_root.hex()
    assert listed[0]["key_id"] == fresh_signer.key_id
    assert len(one) == 1


async def test_the_nightly_task_closes_the_day_through_the_runtime(
    engines: dict[str, AsyncEngine], fresh_signer: LocalSigner
) -> None:
    provenance_jobs.use_runtime(
        provenance_jobs.ProvenanceRuntime(
            session_factory=create_session_factory(engines["bridge_app"]),
            signer=fresh_signer,
            audit_engine=engines["audit_reader"],
        )
    )
    try:
        # 21:30 UTC on 1 October 2026 is 00:30 on 2 October in Nairobi: the run closes 1 October.
        await audit_jobs.verify_chain(timestamp=1_790_890_200)
    finally:
        provenance_jobs.use_runtime(None)
    async with engines["bridge_owner"].connect() as conn:
        days = (await conn.execute(text("SELECT day FROM transparency_roots ORDER BY day"))).scalars().all()
    assert date(2026, 10, 1) in days


async def test_a_broken_chain_publishes_nothing(engines: dict[str, AsyncEngine], fresh_signer: LocalSigner) -> None:
    owner, app, reader = engines["bridge_owner"], engines["bridge_app"], engines["audit_reader"]
    await append(owner, "org:nightly-broken", 3)
    async with owner.begin() as conn:
        await conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
        await conn.execute(
            text("UPDATE audit_events SET action = 'x.forged' WHERE chain_id = 'org:nightly-broken' AND seq = 2")
        )
        await conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER USER"))
    day = date(2026, 9, 28)
    async with create_session_factory(app)() as s:
        with pytest.raises(ChainVerificationError, match="org:nightly-broken") as info:
            await verify_and_publish_root(reader, s, fresh_signer, day)
    assert set(info.value.broken) == {"org:nightly-broken"}
    async with owner.connect() as conn:
        assert (await conn.execute(text("SELECT 1 FROM transparency_roots WHERE day = :d"), {"d": day})).first() is None
