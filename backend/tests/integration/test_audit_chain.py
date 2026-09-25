"""REQ-AUD-01 / AC-IP-2 (audit half, asserted early): the hash chain verifies, edits are rejected by trigger or
found by the verifier. Hypothesis appends random event sequences; each example uses its own chain id."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from bridge.audit.chain import verify_chain
from bridge.ids import uuid7

JSON_TEXT = st.characters(codec="utf-8", exclude_characters="\x00")  # utf-8 codec excludes lone surrogates
payloads = st.dictionaries(
    st.text(alphabet="abcdefghij_", min_size=1, max_size=8),
    # Postgres text and jsonb cannot hold NUL or lone surrogates; audit payloads are ids, enums and digests anyway.
    st.one_of(st.integers(-(10**6), 10**6), st.booleans(), st.text(JSON_TEXT, max_size=12), st.none()),
    max_size=4,
)
events = st.lists(st.tuples(st.sampled_from(["a.created", "b.updated", "c.signed"]), payloads), min_size=1, max_size=6)


async def append(engine: AsyncEngine, chain_id: str, action: str, payload: dict[str, object]) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_events (id, chain_id, seq, actor_kind, action, payload, prev_hash, event_hash) "
                "VALUES (:id, :chain, 0, 'system', :action, CAST(:payload AS jsonb), ''::bytea, ''::bytea)"
            ),
            {"id": uuid7(), "chain": chain_id, "action": action, "payload": json.dumps(payload)},
        )


@pytest.fixture(scope="module")
async def superuser_engine(database_url: object) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)  # type: ignore[arg-type]
    yield engine
    await engine.dispose()


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(sequence=events)
async def test_random_sequences_verify(
    owner_engine: AsyncEngine, audit_reader_engine: AsyncEngine, sequence: list[tuple[str, dict[str, object]]]
) -> None:
    chain_id = f"prop-{uuid4().hex[:10]}"
    for action, payload in sequence:
        await append(owner_engine, chain_id, action, payload)
    async with audit_reader_engine.connect() as conn:
        assert await verify_chain(conn, chain_id) == []


async def test_seq_and_links_are_set_by_the_database(owner_engine: AsyncEngine) -> None:
    chain_id = f"links-{uuid4().hex[:10]}"
    for n in range(3):
        await append(owner_engine, chain_id, "x.happened", {"n": n})
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT seq, prev_hash, event_hash FROM audit_events WHERE chain_id = :c ORDER BY seq"),
                {"c": chain_id},
            )
        ).all()
    assert [r.seq for r in rows] == [1, 2, 3]
    assert bytes(rows[0].prev_hash) == bytes(32)
    assert bytes(rows[1].prev_hash) == bytes(rows[0].event_hash)
    assert all(len(bytes(r.event_hash)) == 32 for r in rows)


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_events SET action = 'x.forged' WHERE chain_id = :c", "DELETE FROM audit_events WHERE chain_id = :c"],
)
async def test_update_and_delete_are_rejected(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, statement: str
) -> None:
    chain_id = f"guard-{uuid4().hex[:10]}"
    await append(owner_engine, chain_id, "x.happened", {})
    for engine in (owner_engine, app_engine):
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError):
                await conn.execute(text(statement), {"c": chain_id})


async def test_truncate_is_rejected(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("TRUNCATE audit_events"))


async def test_the_verifier_finds_a_tampered_row(
    owner_engine: AsyncEngine, superuser_engine: AsyncEngine, audit_reader_engine: AsyncEngine
) -> None:
    """Someone with superuser rights disables the triggers and edits one byte of a payload: the chain breaks."""
    chain_id = f"tamper-{uuid4().hex[:10]}"
    for n in range(4):
        await append(owner_engine, chain_id, "x.happened", {"amount": n})
    async with superuser_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
        await conn.execute(
            text("UPDATE audit_events SET payload = '{\"amount\": 99}' WHERE chain_id = :c AND seq = 2"),
            {"c": chain_id},
        )
        await conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER USER"))
    async with audit_reader_engine.connect() as conn:
        problems = await verify_chain(conn, chain_id)
    assert [p.seq for p in problems] == [2]
    assert "event_hash" in problems[0].reason


maybe_uuid = st.one_of(st.none(), st.uuids(version=4))
rich_events = st.lists(
    st.fixed_dictionaries(
        {
            "action": st.sampled_from(["a.created", "b.updated", "c.signed"]),
            "payload": payloads,
            "actor": maybe_uuid,
            "org": maybe_uuid,
            "subject_type": st.one_of(st.none(), st.sampled_from(["user", "org", "proposal"])),
            "subject": maybe_uuid,
        }
    ),
    min_size=2,
    max_size=6,
)
# Tail deletion and a full re-hash of every later row are not detectable from the chain alone (residual in
# THREAT_MODEL.md; external anchoring arrives with provenance). Everything else must be found.
EDITS = {
    "action": "action = 'x.forged'",
    "payload": "payload = payload || '{\"forged\": true}'::jsonb",
    "actor": "actor_user_id = gen_random_uuid()",
    "org": "org_id = gen_random_uuid()",
    "subject_type": "subject_type = 'forged'",
    "subject": "subject_id = gen_random_uuid()",
    "time": "occurred_at = occurred_at + interval '1 second'",
    "relink": "prev_hash = sha256(prev_hash)",
}
tampering = st.one_of(
    st.tuples(st.just("edit"), st.sampled_from(sorted(EDITS))), st.tuples(st.just("delete"), st.none())
)


async def append_rich(engine: AsyncEngine, chain_id: str, event: dict[str, object]) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_events (id, chain_id, seq, actor_kind, actor_user_id, org_id, action, subject_type, "
                "subject_id, payload, prev_hash, event_hash) VALUES (:id, :chain, 0, CAST(:kind AS audit_actor), "
                ":actor, :org, :action, :subject_type, :subject, CAST(:payload AS jsonb), ''::bytea, ''::bytea)"
            ),
            {
                "id": uuid7(),
                "chain": chain_id,
                "kind": "user" if event["actor"] else "system",
                "actor": event["actor"],
                "org": event["org"],
                "action": event["action"],
                "subject_type": event["subject_type"],
                "subject": event["subject"],
                "payload": json.dumps(event["payload"]),
            },
        )


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(sequence=rich_events, tamper=tampering, pick=st.integers(min_value=0, max_value=10**6))
async def test_any_tampering_is_found(
    owner_engine: AsyncEngine,
    superuser_engine: AsyncEngine,
    audit_reader_engine: AsyncEngine,
    sequence: list[dict[str, object]],
    tamper: tuple[str, str | None],
    pick: int,
) -> None:
    """Random chains with actors, organisations and subjects verify; then a superuser with the triggers disabled edits
    any field of any row, relinks a row, or deletes a row before the tail, and the verifier reports it."""
    chain_id = f"tamper-{uuid4().hex[:10]}"
    for event in sequence:
        await append_rich(owner_engine, chain_id, event)
    async with audit_reader_engine.connect() as conn:
        assert await verify_chain(conn, chain_id) == []
    kind, field = tamper
    if kind == "edit":
        seq = 1 + pick % len(sequence)
        statement = f"UPDATE audit_events SET {EDITS[str(field)]} WHERE chain_id = :c AND seq = :s"
    else:
        seq = 1 + pick % (len(sequence) - 1)  # not the tail
        statement = "DELETE FROM audit_events WHERE chain_id = :c AND seq = :s"
    async with superuser_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
        await conn.execute(text(statement), {"c": chain_id, "s": seq})
        await conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER USER"))
    async with audit_reader_engine.connect() as conn:
        assert await verify_chain(conn, chain_id) != []
