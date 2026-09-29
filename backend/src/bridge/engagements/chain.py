"""Engagement event chain: canonical form and an independent verifier (REQ-ENG-02; docs/spec/06 6.9 Persistence).

The trigger ``engagement_events_chain()`` (revision 0003) sets ``seq``, ``prev_hash``, ``created_at`` and
``hash = sha256(prev_hash || canonical)`` under the engagement's row lock, where ``||`` joins the 32 raw bytes of
``prev_hash`` (32 zero bytes for the first event) and the UTF-8 bytes of the canonical text. This module rebuilds the
canonical text from the stored columns and walks a chain, so an edited row, a broken link, a gap or a state that does
not follow from the previous event is found even if someone bypassed the triggers.

Canonical text: one JSON object, keys in this order, no whitespace outside ``payload``::

    {"v":1,"id":"<uuid>","engagement_id":"<uuid>","seq":<n>,"created_at":<n>,"actor_user_id":"<uuid>"|null,
     "actor_role":"<code>","command":"<code>","from_state":"<code>"|null,"to_state":"<code>",
     "end_reason":"<code>"|null,"stage_deadline_at":<n>|null,"payload":<payload>}

Times are integer microseconds since the Unix epoch; uuids are lower-case and hyphenated; codes are the enum labels
(ASCII letters, digits and ``_`` only, so JSON-escaping them changes nothing); ``payload`` is PostgreSQL's ``jsonb``
text form, read back from the database as ``payload::text`` (as for the audit chain) rather than re-serialised.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

GENESIS = bytes(32)
CANONICAL_VERSION = 1
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class EventRow:
    id: UUID
    engagement_id: UUID
    seq: int
    created_at: datetime
    actor_user_id: UUID | None
    actor_role: str
    command: str
    from_state: str | None
    to_state: str
    end_reason: str | None
    stage_deadline_at: datetime | None
    payload_text: str
    prev_hash: bytes
    hash: bytes


@dataclass(frozen=True, slots=True)
class ChainProblem:
    seq: int
    event_id: UUID | None
    reason: str


def epoch_micros(ts: datetime) -> int:
    """Exact integer microseconds since the epoch (no float rounding)."""
    return (ts - _EPOCH) // timedelta(microseconds=1)


def _string(value: object | None) -> str:
    return "null" if value is None else json.dumps(str(value))


def canonical(row: EventRow) -> str:
    deadline = "null" if row.stage_deadline_at is None else str(epoch_micros(row.stage_deadline_at))
    return (
        f'{{"v":{CANONICAL_VERSION}'
        f',"id":{_string(row.id)}'
        f',"engagement_id":{_string(row.engagement_id)}'
        f',"seq":{row.seq}'
        f',"created_at":{epoch_micros(row.created_at)}'
        f',"actor_user_id":{_string(row.actor_user_id)}'
        f',"actor_role":{_string(row.actor_role)}'
        f',"command":{_string(row.command)}'
        f',"from_state":{_string(row.from_state)}'
        f',"to_state":{_string(row.to_state)}'
        f',"end_reason":{_string(row.end_reason)}'
        f',"stage_deadline_at":{deadline}'
        f',"payload":{row.payload_text}}}'
    )


def event_hash(row: EventRow) -> bytes:
    return hashlib.sha256(row.prev_hash + canonical(row).encode("utf-8")).digest()


def verify_rows(rows: Iterable[EventRow]) -> list[ChainProblem]:
    """Check one engagement's events in ``seq`` order: consecutive seq from 1, prev_hash links, recomputed hashes, a
    genesis with no ``from_state`` and every later event starting from the state the previous one reached."""
    problems: list[ChainProblem] = []
    expected_seq, expected_prev = 1, GENESIS
    previous_state: str | None = None
    for row in rows:
        if row.seq != expected_seq:
            problems.append(ChainProblem(row.seq, row.id, f"expected seq {expected_seq}"))
        if row.prev_hash != expected_prev:
            problems.append(ChainProblem(row.seq, row.id, "prev_hash does not link to the previous event"))
        if event_hash(row) != row.hash:
            problems.append(ChainProblem(row.seq, row.id, "hash does not match the row's contents"))
        if row.from_state != previous_state:
            problems.append(ChainProblem(row.seq, row.id, f"from_state is not {previous_state}"))
        expected_seq, expected_prev, previous_state = row.seq + 1, row.hash, row.to_state
    return problems


_SELECT = text(
    """
    SELECT id, engagement_id, seq, created_at, actor_user_id, actor_role::text, command, from_state::text,
           to_state::text, end_reason::text, stage_deadline_at, payload::text, prev_hash, hash
    FROM engagement_events WHERE engagement_id = :engagement_id ORDER BY seq
    """
)


async def load_chain(connection: AsyncConnection, engagement_id: UUID) -> list[EventRow]:
    """One engagement's events, as the caller may read them (a party, or staff admin, under RLS)."""
    result = await connection.execute(_SELECT, {"engagement_id": engagement_id})
    return [EventRow(*row) for row in result.all()]


async def verify_chain(connection: AsyncConnection, engagement_id: UUID) -> Sequence[ChainProblem]:
    """Verify one engagement's whole chain; an engagement with no readable event is reported too."""
    rows = await load_chain(connection, engagement_id)
    if not rows:
        return [ChainProblem(0, None, "no event")]
    return verify_rows(rows)
