"""REQ-AUD-01 (Phase 2) / AC-IP-2: hourly RFC 3161 anchors of the audit chain heads (only heads that moved; the
tokens verify with openssl over each head's hash), and the nightly verification that publishes a signed Merkle root
of the chain heads, or nothing when a chain is broken. Runs on its own database: the shared one holds chains that
other tests break on purpose."""

from __future__ import annotations

import base64
import json
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import ConfigurationError
from bridge.db import create_session_factory
from bridge.ids import uuid7
from bridge.jobs import audit as audit_jobs
from bridge.jobs import provenance as provenance_jobs
from bridge.provenance.signing import LocalSigner, register_public_key, root_message, verify_signature
from bridge.provenance.transparency import (
    AnchorRejectedError,
    ChainHead,
    ChainVerificationError,
    anchor_chain_heads,
    root_over,
    verify_and_publish_root,
)
from bridge.provenance.tsa import MAX_CLOCK_SKEW, TimestampToken, TsaClient, TsaError
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
        return TsaClient([self.local_tsa.endpoint("http://tsa.test/tsr")], transport=httpx.MockTransport(self.handler))


class AheadOfTheDatabase(TsaClient):
    """The local TSA, but tokens over the chosen digests (every digest when none are chosen) record a time ten
    minutes ahead: the TSA and the worker agree, the database's clock is behind (skew between hosts, which the worker
    cannot see before the insert)."""

    def __init__(self, local_tsa: LocalTsa, ahead: set[bytes] | None = None) -> None:
        super().__init__([local_tsa.endpoint("http://tsa.test/tsr")], transport=local_tsa.transport())
        self.ahead = ahead

    async def timestamp(self, digest: bytes, *, max_ahead: timedelta = MAX_CLOCK_SKEW) -> TimestampToken:
        token = await super().timestamp(digest, max_ahead=max_ahead)
        if self.ahead is None or digest in self.ahead:
            return replace(token, gen_time=token.gen_time + timedelta(minutes=10))
        return token


@asynccontextmanager
async def database_clock_guard(owner: AsyncEngine) -> AsyncIterator[None]:
    """A test trigger refusing anchors timed more than a minute after the database clock, as schema v2's
    chain_anchors_guard does (the trial inserts of the unanchored-head probe are timed at the epoch and pass)."""
    async with owner.begin() as conn:
        await conn.execute(
            text(
                "CREATE FUNCTION test_anchor_time_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN"
                " IF NEW.tsa_time > clock_timestamp() + interval '1 minute' THEN"
                " RAISE EXCEPTION 'chain_anchors: the TSA time is later than the database clock'"
                " USING ERRCODE = 'check_violation'; END IF; RETURN NEW; END $$"
            )
        )
        await conn.execute(
            text(
                "CREATE TRIGGER test_anchor_time_guard BEFORE INSERT ON chain_anchors"
                " FOR EACH ROW EXECUTE FUNCTION test_anchor_time_guard()"
            )
        )
    try:
        yield
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("DROP TRIGGER test_anchor_time_guard ON chain_anchors"))
            await conn.execute(text("DROP FUNCTION test_anchor_time_guard()"))


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


async def test_capped_runs_anchor_pending_heads_in_anchor_order(
    engines: dict[str, AsyncEngine], local_tsa: LocalTsa
) -> None:
    """With room for one anchor per run, three moved chains are anchored one run at a time in a fixed order: oldest
    head first, then chain id (appended here in chain-id order, so both rules agree whichever the heads function
    reports), never a different subset on a rerun."""
    sessions = create_session_factory(engines["bridge_app"])
    tsa = CountingTsa(local_tsa)
    async with sessions() as s:
        await anchor_chain_heads(s, tsa.client())  # drain what earlier tests left pending
    names = ["global-order-a", "org:order-b", "user:order-c"]
    for name in names:
        await append(engines["bridge_owner"], name)
    anchored: list[str] = []
    for _ in names:
        async with sessions() as s:
            report = await anchor_chain_heads(s, tsa.client(), limit=1)
        anchored += [h.chain_id for h in report.anchored]
    assert anchored == names


async def test_a_tsa_outage_anchors_nothing_and_fails_the_run(
    engines: dict[str, AsyncEngine], local_tsa: LocalTsa
) -> None:
    """With the TSA down the run stops at the first failed attempt (each one may take the whole TSA deadline, and a
    run may hold up to MAX_ANCHORS_PER_RUN heads): the other heads wait for the next hourly run."""
    sessions = create_session_factory(engines["bridge_app"])
    tsa = CountingTsa(local_tsa)
    async with sessions() as s:
        await anchor_chain_heads(s, tsa.client())  # drain what earlier tests left pending
    tsa.fail_all = True
    tsa.calls = 0
    for name in ("org:anchor-outage", "org:anchor-outage-2", "user:anchor-outage-3"):
        await append(engines["bridge_owner"], name)
    before = len(await anchors(engines["audit_reader"]))
    async with sessions() as s:
        with pytest.raises(TsaError, match="no chain head could be timestamped") as info:
            await anchor_chain_heads(s, tsa.client())
    assert tsa.calls == 1
    assert "2 left for the next run" in str(info.value)
    assert len(await anchors(engines["audit_reader"])) == before
    tsa.fail_all = False
    async with sessions() as s:
        report = await anchor_chain_heads(s, tsa.client())
    assert {("org:anchor-outage", 1), ("org:anchor-outage-2", 1), ("user:anchor-outage-3", 1)} <= {
        (h.chain_id, h.seq) for h in report.anchored
    }


async def test_an_anchor_the_database_refuses_is_skipped_and_the_others_land(
    engines: dict[str, AsyncEngine], local_tsa: LocalTsa
) -> None:
    """Each anchor is inserted in its own savepoint: one the database refuses (its TSA time is ahead of the database
    clock) is logged and skipped, the other anchors of the run are stored, and the refused head is anchored by the
    next run."""
    owner, reader = engines["bridge_owner"], engines["audit_reader"]
    sessions = create_session_factory(engines["bridge_app"])
    async with sessions() as s:
        await anchor_chain_heads(s, CountingTsa(local_tsa).client())  # drain what earlier tests left pending
    for name in ("org:skew-a", "org:skew-b", "org:skew-c"):
        await append(owner, name)
    skewed = {h.event_hash for h in await heads(reader) if h.chain_id == "org:skew-b"}
    async with database_clock_guard(owner), sessions() as s:
        report = await anchor_chain_heads(s, AheadOfTheDatabase(local_tsa, skewed))
    assert {(h.chain_id, h.seq) for h in report.anchored} == {("org:skew-a", 1), ("org:skew-c", 1)}
    assert [(h.chain_id, h.seq) for h in report.rejected] == [("org:skew-b", 1)]
    stored = {(r.chain_id, r.seq) for r in await anchors(reader)}
    assert {("org:skew-a", 1), ("org:skew-c", 1)} <= stored
    assert ("org:skew-b", 1) not in stored
    async with sessions() as s:
        again = await anchor_chain_heads(s, CountingTsa(local_tsa).client())
    assert [(h.chain_id, h.seq) for h in again.anchored] == [("org:skew-b", 1)]


async def test_a_run_whose_every_anchor_is_refused_fails(engines: dict[str, AsyncEngine], local_tsa: LocalTsa) -> None:
    owner = engines["bridge_owner"]
    sessions = create_session_factory(engines["bridge_app"])
    async with sessions() as s:
        await anchor_chain_heads(s, CountingTsa(local_tsa).client())  # drain what earlier tests left pending
    await append(owner, "org:skew-only")
    async with database_clock_guard(owner), sessions() as s:
        with pytest.raises(AnchorRejectedError, match="1 refused by the database"):
            await anchor_chain_heads(s, AheadOfTheDatabase(local_tsa))
    assert ("org:skew-only", 1) not in {(r.chain_id, r.seq) for r in await anchors(engines["audit_reader"])}


async def test_the_anchor_takes_no_token_more_than_a_minute_ahead_of_the_worker(
    engines: dict[str, AsyncEngine], local_tsa: LocalTsa
) -> None:
    """The worker refuses a token time more than 60 s ahead of its clock, the bound the chain_anchors guard applies
    with the database's clock: a TSA running fast fails the attempt (the fallback TSA is tried) instead of reaching
    the database. Registration timestamps keep the 15 minutes either way."""
    sessions = create_session_factory(engines["bridge_app"])
    async with sessions() as s:
        await anchor_chain_heads(s, CountingTsa(local_tsa).client())  # drain what earlier tests left pending
    await append(engines["bridge_owner"], "org:tsa-fast")
    worker_behind = TsaClient(
        [local_tsa.endpoint("http://tsa.test/tsr")],
        transport=local_tsa.transport(),
        clock=lambda: datetime.now(UTC) - timedelta(minutes=5),
    )
    async with sessions() as s:
        with pytest.raises(TsaError, match="more than 60 s ahead"):
            await anchor_chain_heads(s, worker_behind)


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


async def test_a_root_names_its_key_after_retirement_and_retired_keys_sign_no_new_root(
    engines: dict[str, AsyncEngine],
) -> None:
    """A root keeps naming the key that signed it, and that key stays listed (with retired_at) on
    /.well-known/provenance-keys.json after it is retired, so the old root still verifies. A retired or never
    published key signs no new root (the job fails at once); the next key does. The report carries the time of the
    snapshot the root covers."""
    owner, app, reader = engines["bridge_owner"], engines["bridge_app"], engines["audit_reader"]
    old, new = LocalSigner(os.urandom(32)), LocalSigner(os.urandom(32))
    async with owner.begin() as conn:
        await register_public_key(conn, old)
    await append(owner, "org:rotation", 2)
    first_day, second_day = date(2026, 8, 1), date(2026, 8, 2)
    before = datetime.now(UTC)
    async with create_session_factory(app)() as s:
        first = await verify_and_publish_root(reader, s, old, first_day)
    assert first.published
    assert before <= first.snapshot_at <= datetime.now(UTC)
    async with owner.begin() as conn:
        await conn.execute(text("UPDATE provenance_keys SET retired_at = now() WHERE key_id = :k"), {"k": old.key_id})

    for refused in (old, new):  # retired, then not yet published
        async with create_session_factory(app)() as s:
            with pytest.raises(ConfigurationError, match="register-key"):
                await verify_and_publish_root(reader, s, refused, second_day)
    async with owner.begin() as conn:
        await register_public_key(conn, new)
    async with create_session_factory(app)() as s:
        assert (await verify_and_publish_root(reader, s, new, second_day)).published

    async with client(app, None) as c:
        roots = {r["day"]: r for r in (await c.get("/api/transparency")).json()["roots"]}
        keys = {k["kid"]: k for k in (await c.get("/.well-known/provenance-keys.json")).json()["keys"]}
    assert roots["2026-08-01"]["key_id"] == old.key_id
    assert roots["2026-08-02"]["key_id"] == new.key_id
    assert keys[old.key_id]["retired_at"] is not None
    assert keys[new.key_id]["retired_at"] is None
    published = base64.urlsafe_b64decode(keys[old.key_id]["x"] + "=")
    assert verify_signature(
        published,
        root_message(first_day, bytes.fromhex(roots["2026-08-01"]["merkle_root"])),
        base64.b64decode(roots["2026-08-01"]["signature"]),
    )


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
