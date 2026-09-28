"""Anchoring the audit chains (REQ-AUD-01 Phase 2; docs/spec/06 6.4 item 4; ADR-003 item 4).

Hourly ``anchor_chain_heads``: an RFC 3161 token over the head (last ``event_hash``) of every audit chain that moved
since its last anchor, into ``chain_anchors``, at most ``MAX_ANCHORS_PER_RUN`` per run in ``anchor_order`` (oldest head
first, then chain id). The heads come from ``app_audit_chain_heads()`` (ids, sequence numbers
and hashes only); ``provenance_worker`` executes it and inserts anchors but may not read ``chain_anchors``, so a head
is known to be anchored when a trial insert of it inside a savepoint conflicts (the savepoint is always rolled back,
so the append-only table never sees it). A cleaner definer function (``app_unanchored_chain_heads()``) is noted for
db-migrations. TSA calls happen outside any transaction.

Nightly ``verify_and_publish_root``: ``audit_reader`` verifies every chain (``bridge.audit.chain``) in one
REPEATABLE READ snapshot; only when all verify, the day's root is published: a Merkle tree (RFC 6962 hashing: leaf
``SHA-256(0x00 || leaf)``, node ``SHA-256(0x01 || left || right)``) over the chain heads of that snapshot, sorted by
chain id, where a leaf is ``chain_id (UTF-8) || 0x00 || seq (8 bytes, big-endian) || event_hash``. The root is signed
(``signing.root_message``) by a published, unretired key and stored in ``transparency_roots`` with that key's id
(public at ``/api/transparency``; retired keys stay listed at ``/.well-known/provenance-keys.json``). The snapshot
time is reported and logged; storing it needs a ``transparency_roots`` column (schema follow-up on the REQ-PROV-01
card). A broken chain publishes nothing and raises ``ChainVerificationError``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from bridge.audit.chain import ChainProblem, verify_all
from bridge.config import ConfigurationError
from bridge.db import as_role
from bridge.ids import uuid7
from bridge.logging import get_logger
from bridge.provenance.signing import Signer, root_message
from bridge.provenance.tsa import TimestampToken, TsaClient, TsaError

WORKER = "provenance_worker"
MAX_ANCHORS_PER_RUN = 500
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
log = get_logger("bridge.provenance.transparency")


class ChainVerificationError(RuntimeError):
    """The nightly verification found a broken chain; no root is published for the day."""

    def __init__(self, broken: dict[str, Sequence[ChainProblem]]) -> None:
        self.broken = broken
        super().__init__(f"{len(broken)} audit chain(s) failed verification: {', '.join(sorted(broken)[:10])}")


@dataclass(frozen=True, slots=True)
class ChainHead:
    chain_id: str
    seq: int
    event_hash: bytes
    occurred_at: datetime | None = None  # when the head event was appended, if the source reports it


@dataclass(slots=True)
class AnchorReport:
    heads: int = 0
    anchored: list[ChainHead] = field(default_factory=list)
    failed: list[ChainHead] = field(default_factory=list)
    deferred: list[ChainHead] = field(default_factory=list)  # not tried after a failure: the next run takes them


def leaf(head: ChainHead) -> bytes:
    return head.chain_id.encode("utf-8") + b"\x00" + head.seq.to_bytes(8, "big") + head.event_hash


def merkle_root(leaves: Sequence[bytes]) -> bytes:
    """RFC 6962 Merkle tree hash; the empty tree hashes to SHA-256 of nothing."""
    if not leaves:
        return hashlib.sha256(b"").digest()
    if len(leaves) == 1:
        return hashlib.sha256(b"\x00" + leaves[0]).digest()
    split = 1 << ((len(leaves) - 1).bit_length() - 1)  # the largest power of two below the length
    return hashlib.sha256(b"\x01" + merkle_root(leaves[:split]) + merkle_root(leaves[split:])).digest()


def root_over(heads: Sequence[ChainHead]) -> bytes:
    return merkle_root([leaf(h) for h in sorted(heads, key=lambda h: h.chain_id)])


# Every column the heads function returns: today chain_id, seq and event_hash; occurred_at (the head's time) once
# db-migrations adds it (schema follow-up on the REQ-PROV-01 card). Until then heads are ordered by chain id alone.
_HEADS = text("SELECT h.* FROM app_audit_chain_heads() AS h")


def anchor_order(heads: Sequence[ChainHead]) -> list[ChainHead]:
    """Oldest head first, then chain id: a capped run takes the heads that have waited longest, and a rerun takes
    the same ones. A head of unknown age counts as the oldest (it cannot be shown to be young)."""
    return sorted(heads, key=lambda h: (h.occurred_at or _EPOCH, h.chain_id))


_INSERT_ANCHOR = text(
    "INSERT INTO chain_anchors (id, chain_id, seq, event_hash, tsa_token, tsa_time, tsa_serial)"
    " VALUES (:id, :chain_id, :seq, :event_hash, :token, :tsa_time, :serial) ON CONFLICT DO NOTHING"
)


async def _unanchored(session: AsyncSession, heads: Sequence[ChainHead]) -> list[ChainHead]:
    """Heads with no anchor yet: a trial insert that conflicts means the head is anchored (always rolled back)."""
    fresh: list[ChainHead] = []
    for head in heads:
        trial = await session.begin_nested()
        result = await session.execute(
            _INSERT_ANCHOR,
            {
                "id": uuid7(),
                "chain_id": head.chain_id,
                "seq": head.seq,
                "event_hash": head.event_hash,
                "token": b"\x00",
                "tsa_time": _EPOCH,
                "serial": "trial",
            },
        )
        await trial.rollback()
        if cast(CursorResult[Any], result).rowcount == 1:
            fresh.append(head)
    return fresh


async def anchor_chain_heads(
    session: AsyncSession, tsa: TsaClient, *, limit: int = MAX_ANCHORS_PER_RUN
) -> AnchorReport:
    """Timestamp every chain head not anchored yet (at most ``limit`` per run; the rest wait for the next hour).

    The first failed timestamp ends the run's TSA calls: each attempt may last the whole TSA deadline, so trying every
    pending head during an outage would hold the worker for hours. Tokens already obtained are stored."""
    report = AnchorReport()
    async with session.begin(), as_role(session, WORKER):
        rows = (await session.execute(_HEADS)).all()
        heads = [ChainHead(r.chain_id, r.seq, bytes(r.event_hash), r._mapping.get("occurred_at")) for r in rows]
        report.heads = len(heads)
        pending = anchor_order(await _unanchored(session, heads))[:limit]
    tokens: list[tuple[ChainHead, TimestampToken]] = []
    for index, head in enumerate(pending):
        try:
            tokens.append((head, await tsa.timestamp(head.event_hash)))
        except TsaError as exc:
            report.failed.append(head)
            report.deferred = pending[index + 1 :]
            log.warning(
                "provenance.anchor_failed",
                chain_id=head.chain_id,
                seq=head.seq,
                reason=str(exc),
                deferred=len(report.deferred),
            )
            break
    if tokens:
        async with session.begin(), as_role(session, WORKER):
            for head, token in tokens:
                inserted = await session.execute(
                    _INSERT_ANCHOR,
                    {
                        "id": uuid7(),
                        "chain_id": head.chain_id,
                        "seq": head.seq,
                        "event_hash": head.event_hash,
                        "token": token.response,
                        "tsa_time": token.gen_time,
                        "serial": token.serial,
                    },
                )
                if cast(CursorResult[Any], inserted).rowcount == 1:
                    report.anchored.append(head)
    log.info(
        "provenance.anchored",
        heads=report.heads,
        anchored=len(report.anchored),
        failed=len(report.failed),
        deferred=len(report.deferred),
    )
    if pending and not tokens:
        raise TsaError(
            f"no chain head could be timestamped ({len(report.failed)} tried, {len(report.deferred)} left for the"
            " next run)"
        )
    return report


# The first statement of the REPEATABLE READ transaction takes its snapshot: the root covers every audit event
# committed before this time and none after (recorded in transparency_roots once schema v2 has the column).
_SNAPSHOT_TIME = text("SELECT statement_timestamp()")
_READER_HEADS = text(
    "SELECT DISTINCT ON (chain_id) chain_id, seq, event_hash FROM audit_events ORDER BY chain_id, seq DESC"
)
_ROOT_EXISTS = text("SELECT 1 FROM transparency_roots WHERE day = :day")
_KEY = text("SELECT retired_at FROM provenance_keys WHERE key_id = :key_id")
_INSERT_ROOT = text(
    "INSERT INTO transparency_roots (day, merkle_root, signature, key_id)"
    " VALUES (:day, :root, :signature, :key_id) ON CONFLICT DO NOTHING"
)


@dataclass(frozen=True, slots=True)
class RootReport:
    day: date
    merkle_root: bytes
    chains: int
    published: bool
    snapshot_at: datetime  # when the snapshot whose chain heads the root covers was taken


async def verify_and_publish_root(
    audit_engine: AsyncEngine, session: AsyncSession, signer: Signer, day: date
) -> RootReport:
    """Verify every chain as ``audit_reader``, then publish the signed root for ``day`` (idempotent per day).

    Only a published, unretired key signs a root (``ConfigurationError`` otherwise, so the job fails at once): the
    root names that key, and the key stays on ``/.well-known/provenance-keys.json`` after it is retired."""
    async with audit_engine.connect() as raw:
        connection = await raw.execution_options(isolation_level="REPEATABLE READ")
        async with connection.begin():
            snapshot_at: datetime = (await connection.execute(_SNAPSHOT_TIME)).scalar_one()
            broken = await verify_all(connection)
            rows = (await connection.execute(_READER_HEADS)).all()
    if broken:
        log.error("audit.chain_broken", chains=sorted(broken)[:50], count=len(broken))
        raise ChainVerificationError(broken)
    heads = [ChainHead(r.chain_id, r.seq, bytes(r.event_hash)) for r in rows]
    root = root_over(heads)
    async with session.begin():
        if (await session.execute(_ROOT_EXISTS, {"day": day})).first() is not None:
            return RootReport(day, root, len(heads), published=False, snapshot_at=snapshot_at)
        key = (await session.execute(_KEY, {"key_id": signer.key_id})).one_or_none()
        if key is None or key.retired_at is not None:
            raise ConfigurationError(
                f"signing key {signer.key_id} is not published or is retired: publish the current key with"
                " python -m bridge.provenance register-key"
            )
        signature = await signer.sign(root_message(day, root))
        async with as_role(session, WORKER):
            inserted = await session.execute(
                _INSERT_ROOT, {"day": day, "root": root, "signature": signature, "key_id": signer.key_id}
            )
    published = cast(CursorResult[Any], inserted).rowcount == 1
    log.info(
        "audit.transparency_root",
        day=day.isoformat(),
        chains=len(heads),
        published=published,
        key_id=signer.key_id,
        snapshot_at=snapshot_at.isoformat(),
    )
    return RootReport(day, root, len(heads), published, snapshot_at)
