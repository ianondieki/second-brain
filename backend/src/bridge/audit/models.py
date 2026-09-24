"""Append-only, hash-chained audit log (REQ-AUD-01; docs/spec/06 6.4 item 4).

``audit_events`` holds only ids, enums, amounts and salted digests; free text and personal data live in the mutable
``event_details`` row, so erasure never touches the chain. ``seq``, ``prev_hash``, ``event_hash`` and
``occurred_at`` are set by the database trigger ``audit_events_chain()`` under an advisory lock; values sent by the
application are overwritten. UPDATE, DELETE and TRUNCATE are rejected by triggers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, IdMixin, Tenancy
from bridge.models.enums import AuditActor
from bridge.models.types import pg_enum

AUDIT = {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "actor_user_id"}}


class AuditEvent(IdMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("chain_id", "seq"),
        UniqueConstraint("chain_id", "prev_hash"),
        # Non-empty fields keep the hashed canonical form unambiguous (the trigger also rejects '|').
        CheckConstraint("chain_id <> ''", name="chain_id_not_empty"),
        CheckConstraint("action <> ''", name="action_not_empty"),
        CheckConstraint("subject_type IS NULL OR subject_type <> ''", name="subject_type_not_empty"),
        AUDIT,
    )

    chain_id: Mapped[str] = mapped_column(String(64), server_default="global")
    seq: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_kind: Mapped[AuditActor] = mapped_column(pg_enum(AuditActor, "audit_actor"))
    actor_user_id: Mapped[UUID | None] = mapped_column(index=True)
    org_id: Mapped[UUID | None] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(80))
    subject_type: Mapped[str | None] = mapped_column(String(40))
    subject_id: Mapped[UUID | None] = mapped_column()
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary)
    event_hash: Mapped[bytes] = mapped_column(LargeBinary)


class EventDetails(Base):
    """Mutable companion of an audit event: personal data and free text, pseudonymised on erasure (Phase 8)."""

    __tablename__ = "event_details"
    __table_args__ = ({"info": {"tenancy": Tenancy.ORG_OR_USER, "via": "audit_events"}},)

    event_id: Mapped[UUID] = mapped_column(ForeignKey("audit_events.id"), primary_key=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
