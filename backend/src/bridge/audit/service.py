"""Appending audit events (REQ-AUD-01). Payloads carry only ids, enums, amounts and digests; anything personal or
free-text goes to ``details`` (stored in the mutable ``event_details`` row, docs/spec/06 6.4 item 4).

Inserts are plain Core INSERTs without RETURNING: under RLS an INSERT ... RETURNING must also pass the SELECT policy,
which a system event, or an event about another subject, would not. ``seq``, ``prev_hash``, ``event_hash`` and
``occurred_at`` are set by the database trigger ``audit_events_chain()`` (migration 0001).

Chains are per scope: ``org:<id>`` for organisation events, ``user:<id>`` for a user's own events, ``global`` for
system events. The trigger serialises appends per chain with an advisory lock held until COMMIT, so one slow
transaction never stalls every other writer (security review of revision 0001). ``bridge.audit.chain`` verifies each
chain; the hourly anchor (Phase 2, T2.4) timestamps every chain head.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.models import AuditEvent, EventDetails
from bridge.ids import uuid7
from bridge.models.enums import AuditActor

# Overwritten by the trigger; present only because the columns are NOT NULL.
_PLACEHOLDER_HASH = b""


def chain_for(*, org_id: UUID | None, actor_user_id: UUID | None) -> str:
    if org_id is not None:
        return f"org:{org_id}"
    if actor_user_id is not None:
        return f"user:{actor_user_id}"
    return "global"


async def record(
    session: AsyncSession,
    action: str,
    *,
    actor_user_id: UUID | None,
    actor_kind: AuditActor = AuditActor.USER,
    org_id: UUID | None = None,
    subject_type: str | None = None,
    subject_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> UUID:
    """Append one event (in the caller's transaction) and return its id."""
    event_id = uuid7()
    chain_id = chain_for(org_id=org_id, actor_user_id=actor_user_id)
    await session.execute(
        insert(AuditEvent).values(
            id=event_id,
            chain_id=chain_id,
            seq=0,
            actor_kind=actor_kind,
            actor_user_id=actor_user_id,
            org_id=org_id,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload or {},
            prev_hash=_PLACEHOLDER_HASH,
            event_hash=_PLACEHOLDER_HASH,
        )
    )
    if details:
        await session.execute(insert(EventDetails).values(event_id=event_id, details=details))
    return event_id
