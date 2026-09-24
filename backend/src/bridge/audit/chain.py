"""Audit chain canonical form and an independent verifier (REQ-AUD-01; AC-IP-2 audit half).

The database trigger ``audit_events_chain()`` (migration 0001) sets ``seq``, ``prev_hash``, ``occurred_at`` and
``event_hash = sha256(canonical)``. This module recomputes the same canonical text from the stored columns and walks
the chain, so an edited row, a broken link or a gap is found even if someone bypassed the triggers.

Canonical text (fields joined by ``|``): hex(prev_hash), seq, id, chain_id, occurred_at as integer microseconds
since the Unix epoch, actor_kind, actor_user_id or "", org_id or "", action, subject_type or "", subject_id or "",
``payload::text`` (Postgres' jsonb rendering, read back from the database as text).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

GENESIS = bytes(32)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ChainRow:
    id: UUID
    chain_id: str
    seq: int
    occurred_at: datetime
    actor_kind: str
    actor_user_id: UUID | None
    org_id: UUID | None
    action: str
    subject_type: str | None
    subject_id: UUID | None
    payload_text: str
    prev_hash: bytes
    event_hash: bytes


@dataclass(frozen=True, slots=True)
class ChainProblem:
    seq: int
    event_id: UUID | None
    reason: str


def epoch_micros(ts: datetime) -> int:
    """Exact integer microseconds since the epoch (no float rounding)."""
    return (ts - _EPOCH) // timedelta(microseconds=1)


def canonical(row: ChainRow) -> str:
    return "|".join(
        [
            row.prev_hash.hex(),
            str(row.seq),
            str(row.id),
            row.chain_id,
            str(epoch_micros(row.occurred_at)),
            row.actor_kind,
            str(row.actor_user_id) if row.actor_user_id else "",
            str(row.org_id) if row.org_id else "",
            row.action,
            row.subject_type or "",
            str(row.subject_id) if row.subject_id else "",
            row.payload_text,
        ]
    )


def event_hash(row: ChainRow) -> bytes:
    return hashlib.sha256(canonical(row).encode("utf-8")).digest()


def verify_rows(rows: Iterable[ChainRow]) -> list[ChainProblem]:
    """Check one chain's rows in ``seq`` order: consecutive seq from 1, prev_hash links, recomputed hashes."""
    problems: list[ChainProblem] = []
    expected_seq, expected_prev = 1, GENESIS
    for row in rows:
        if row.seq != expected_seq:
            problems.append(ChainProblem(row.seq, row.id, f"expected seq {expected_seq}"))
        if row.prev_hash != expected_prev:
            problems.append(ChainProblem(row.seq, row.id, "prev_hash does not link to the previous event"))
        if event_hash(row) != row.event_hash:
            problems.append(ChainProblem(row.seq, row.id, "event_hash does not match the row's contents"))
        expected_seq, expected_prev = row.seq + 1, row.event_hash
    return problems


_SELECT = text(
    """
    SELECT id, chain_id, seq, occurred_at, actor_kind::text, actor_user_id, org_id, action, subject_type,
           subject_id, payload::text, prev_hash, event_hash
    FROM audit_events WHERE chain_id = :chain_id ORDER BY seq
    """
)


async def load_chain(connection: AsyncConnection, chain_id: str = "global") -> list[ChainRow]:
    result = await connection.execute(_SELECT, {"chain_id": chain_id})
    return [ChainRow(*row) for row in result.all()]


async def verify_chain(connection: AsyncConnection, chain_id: str = "global") -> Sequence[ChainProblem]:
    """Verify a whole chain. Needs a role that can read every event (``audit_reader``; RLS hides others' rows)."""
    return verify_rows(await load_chain(connection, chain_id))


async def verify_all(connection: AsyncConnection) -> dict[str, Sequence[ChainProblem]]:
    """Verify every chain in the table (the nightly ``audit.verify_chain`` job); returns only broken chains."""
    chain_ids = (await connection.execute(text("SELECT DISTINCT chain_id FROM audit_events"))).scalars().all()
    broken: dict[str, Sequence[ChainProblem]] = {}
    for chain_id in chain_ids:
        problems = await verify_chain(connection, chain_id)
        if problems:
            broken[chain_id] = problems
    return broken
