"""The LLM call ledger (REQ-LLM-01; docs/spec/08 LLM layer, docs/spec/09).

Every runtime LLM call writes one row: tenant, task, model, tokens (incl. cached), cost, latency, status and trace id.
Rows belong to a user, an organisation, both, or neither (system jobs). Users read their own rows, members their
organisation's rows and staff ``admin`` every row; the global daily cap reads the platform total through
``app_llm_spend_usd``. ``inputs`` holds the sanitised Tier-1 values and, for Tier-2 fields, only their name, tier and
length: Tier-2 plaintext is never stored here, with or without consent (the LLM layer redacts, AC-SEC-6). It is kept
30 days, written by the app but readable only by staff admin through ``app_llm_call_inputs(call_id)``: bridge_app holds
no SELECT on the column, so the mapper never loads it.

Message Batches: an item is reserved at submission (``status = 'batch_reserved'``, the estimated cost, ``batch_id`` and
``custom_id``; its ``created_at`` is the database's, whatever is sent) and settled once its result arrives through
``app_llm_settle_batch_item`` (a second row with the same pair, the ``org_id`` and ``user_id`` of the batch's earliest
reservation, the final status and cost and the database's time; false once the item has settled). A batch is the
tenant's of its earliest reservation (``app_llm_batch_owned``, which ``batch_poll`` checks before fetching results;
revision 0002 round 6). An item is its tenant's: the partial unique indexes allow one reservation and one settlement
per item and tenant (NULLS NOT DISTINCT), and the database refuses a settlement for an item only other tenants reserved
(``llm_calls_batch_guard``, round 5). A platform job's batch rows (no user, no organisation) are written only by a
session that binds no user.
Spend is read from the ``llm_spend`` view (org_id, user_id, cost_usd, created_at; revision 0002), the one rule that
counts a reservation until its item settles and then only the settled row: the tenant monthly sum reads the view
under RLS, and ``app_llm_spend_usd`` the platform total.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy

MAX_CALL_COST_USD = 100
BATCH_RESERVED = "batch_reserved"  # the status of a Message Batches reservation
COUNTS_NOT_NEGATIVE = (
    "input_tokens >= 0 AND output_tokens >= 0 AND cache_read_tokens >= 0 AND cache_write_tokens >= 0"
    " AND (latency_ms IS NULL OR latency_ms >= 0)"
)


class LlmCall(IdMixin, CreatedMixin, Base):
    __tablename__ = "llm_calls"
    # Inserted by callers that may not read the new row back (no SELECT grant or policy), so the ORM must not add
    # RETURNING for server defaults.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012
    __table_args__ = (
        Index("ix_llm_calls_org_id_created_at", "org_id", "created_at"),
        Index("ix_llm_calls_user_id_created_at", "user_id", "created_at"),
        Index("ix_llm_calls_created_at", "created_at"),
        # One row is one plausible call: the global daily cap sums every row, so a row must neither blow it (a cost
        # over 100 USD) nor offset real spend (a negative cost). Token counts and latency are never negative.
        CheckConstraint(f"cost_usd BETWEEN 0 AND {MAX_CALL_COST_USD}", name="cost_usd_range"),
        CheckConstraint(COUNTS_NOT_NEGATIVE, name="counts_not_negative"),
        CheckConstraint("(batch_id IS NULL) = (custom_id IS NULL)", name="batch_pair"),
        CheckConstraint(f"status <> '{BATCH_RESERVED}' OR batch_id IS NOT NULL", name="batch_reserved_has_batch"),
        # One reservation and one settlement per item within its tenant (NULL counts as one value).
        Index(
            "uq_llm_calls_batch_reservation",
            "batch_id",
            "custom_id",
            "org_id",
            "user_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text(f"status = '{BATCH_RESERVED}'"),
        ),
        Index(
            "uq_llm_calls_batch_settlement",
            "batch_id",
            "custom_id",
            "org_id",
            "user_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text(f"batch_id IS NOT NULL AND status <> '{BATCH_RESERVED}'"),
        ),
        {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "user_id"}},
    )

    org_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    task: Mapped[str] = mapped_column(String(80))  # a key of ai/models.yaml
    purpose: Mapped[str | None] = mapped_column(String(40))  # consent purpose when the task needs one
    model: Mapped[str] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    stop_reason: Mapped[str | None] = mapped_column(String(40))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    batch_id: Mapped[str | None] = mapped_column(String(64))  # the provider's batch id; with custom_id or neither
    custom_id: Mapped[str | None] = mapped_column(String(64))  # the item's id within the batch
    inputs: Mapped[dict[str, Any] | None] = mapped_column(JSONB, deferred=True, deferred_raiseload=True)
