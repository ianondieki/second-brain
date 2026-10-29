"""Scout agents, their runs and their matches (REQ-SCOUT-01, REQ-SCOUT-02; docs/spec/06 6.8; revision 0005).

Tenancy ORG: an organisation's members read its scouts, runs and matches (narrowed to ``app.org_id`` when a request
is scoped to one organisation); nobody else sees anything.

- ``scout_agents``: the form (niches, counties, keywords, maturity, budget band, ``min_fit``, frequency, language,
  recipients), its pause and the incremental cursor. Its owner or admin writes it (as ``created_by``); recipients are
  active reviewers of the organisation when the list is written (the digest re-checks at send time). Deleting a scout
  deletes its runs and matches.
- ``agent_runs``: one scan (``trigger`` = the frequency that fired it). An acting member (owner, admin, signatory or
  reviewer; the scan job binds the ``act_as_user_id`` of ``app_scouts_due``) starts it running and finishes it
  (completed, or failed with an error code: a code, never free text); never deleted by the app. ``started_at`` is the
  database's clock (``app_clock_now()``): leave it out.
- ``agent_matches``: one proposal matched by one scout, once across runs (UNIQUE scout, proposal), for the current
  registered version of a published, clear proposal; only the feedback columns (as oneself) and ``digest_sent_at``
  change afterwards.

Tier 1 and metadata only (docs/spec/06 6.8): nothing here holds Tier-2 text. The scan job calls ``app_scouts_due``
with no user bound, then binds each scout's acting member and organisation (``bind_tenant``) for its run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import AgentRunStatus, MatchFeedback, ProposalMaturity, ScoutFrequency
from bridge.models.types import pg_enum, pg_enum_array

ORG = {"info": {"tenancy": Tenancy.ORG, "tenant_column": "org_id"}}
CODE = "'^[a-z][a-z0-9_]{0,39}$'"  # an error or feedback code: never free text


class ScoutAgent(IdMixin, TimestampsMixin, Base):
    """An organisation's scout: a form, not a prompt (docs/spec/06 6.8)."""

    __tablename__ = "scout_agents"
    __table_args__ = (
        UniqueConstraint("id", "org_id"),  # target of the (scout_id, org_id) foreign keys of runs and matches
        CheckConstraint("app_uuid_set_is_valid(niches, 1, 5)", name="niches_valid"),
        CheckConstraint("app_uuid_set_is_valid(recipients, 0, 20)", name="recipients_valid"),
        CheckConstraint("app_text_set_is_valid(counties, 47, 8)", name="counties_valid"),
        CheckConstraint("app_text_set_is_valid(include_keywords, 20, 60)", name="include_keywords_valid"),
        CheckConstraint("app_text_set_is_valid(exclude_keywords, 20, 60)", name="exclude_keywords_valid"),
        CheckConstraint("cardinality(maturity) <= 4 AND array_position(maturity, NULL) IS NULL", name="maturity_valid"),
        CheckConstraint("budget_band IS NULL OR budget_band ~ '^[a-z0-9_-]{1,32}$'", name="budget_band_code"),
        CheckConstraint("min_fit BETWEEN 0 AND 100", name="min_fit_range"),
        CheckConstraint("language IN ('en', 'sw')", name="language_known"),
        ORG,
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    niches: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))  # 1 to 5 distinct niche ids
    counties: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")  # region codes; empty = any
    include_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")  # <= 20 x 60 characters
    exclude_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")  # <= 20 x 60 characters
    maturity: Mapped[list[ProposalMaturity]] = mapped_column(
        pg_enum_array(ProposalMaturity, "proposal_maturity"), server_default="{}"
    )  # empty = any
    budget_band: Mapped[str | None] = mapped_column(String(32))  # a band code from config, not an amount
    min_fit: Mapped[int] = mapped_column(SmallInteger, server_default="60")
    frequency: Mapped[ScoutFrequency] = mapped_column(
        pg_enum(ScoutFrequency, "scout_frequency"), server_default=ScoutFrequency.WEEKLY.value
    )
    language: Mapped[str] = mapped_column(String(2), server_default="en")
    recipients: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")  # reviewer seats, <= 20
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The incremental cursor: the last publication a completed run covered (time, then proposal id).
    cursor_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor_proposal_id: Mapped[UUID | None] = mapped_column()
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


class AgentRun(IdMixin, Base):
    """One scan of one scout over a cursor window (``window_start`` exclusive, ``window_end`` inclusive)."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scout_id", "org_id"],
            ["scout_agents.id", "scout_agents.org_id"],
            name="fk_agent_runs_scout",
            ondelete="CASCADE",
        ),
        CheckConstraint("scanned_count >= 0 AND matched_count >= 0", name="counts_not_negative"),
        CheckConstraint("window_start IS NULL OR window_start <= window_end", name="window_in_order"),
        CheckConstraint("(status = 'running') = (finished_at IS NULL)", name="finished_unless_running"),
        CheckConstraint(
            f"(status = 'failed') = (error_code IS NOT NULL) AND (error_code IS NULL OR error_code ~ {CODE})",
            name="error_code_when_failed",
        ),
        ORG,
    )

    scout_id: Mapped[UUID] = mapped_column(index=True)
    org_id: Mapped[UUID] = mapped_column(index=True)
    trigger: Mapped[ScoutFrequency] = mapped_column(pg_enum(ScoutFrequency, "scout_frequency"))
    status: Mapped[AgentRunStatus] = mapped_column(
        pg_enum(AgentRunStatus, "agent_run_status"), server_default=AgentRunStatus.RUNNING.value
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scanned_count: Mapped[int] = mapped_column(Integer, server_default="0")
    matched_count: Mapped[int] = mapped_column(Integer, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(40))


class AgentMatch(IdMixin, CreatedMixin, Base):
    """A proposal a scout matched: its score, the rules that fired and the "why this matches" line."""

    __tablename__ = "agent_matches"
    __table_args__ = (
        UniqueConstraint("scout_id", "proposal_id"),  # once per scout across runs (AC-SCOUT-6)
        ForeignKeyConstraint(
            ["scout_id", "org_id"],
            ["scout_agents.id", "scout_agents.org_id"],
            name="fk_agent_matches_scout",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["proposal_id", "version_id"],
            ["proposal_versions.proposal_id", "proposal_versions.id"],
            name="fk_agent_matches_version",
        ),
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint(
            "jsonb_typeof(rule_breakdown) = 'object' AND octet_length(rule_breakdown::text) <= 4096",
            name="rule_breakdown_object",
        ),
        CheckConstraint(
            "rationale IS NULL OR (btrim(rationale) <> '' AND length(rationale) <= 600)", name="rationale_length"
        ),
        CheckConstraint(
            "(feedback IS NULL) = (feedback_by IS NULL) AND (feedback IS NULL) = (feedback_at IS NULL)"
            f" AND (feedback_reason IS NULL OR (feedback IS NOT NULL AND feedback_reason ~ {CODE}))",
            name="feedback_complete",
        ),
        ORG,
    )

    scout_id: Mapped[UUID] = mapped_column()
    org_id: Mapped[UUID] = mapped_column(index=True)
    proposal_id: Mapped[UUID] = mapped_column()
    version_id: Mapped[UUID] = mapped_column()  # the proposal's current registered version when matched
    niche_id: Mapped[UUID | None] = mapped_column(ForeignKey("niches.id"))
    score: Mapped[int] = mapped_column(SmallInteger)  # 0-100
    rule_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    rationale: Mapped[str | None] = mapped_column(Text)  # <= 600 characters, Tier 1 only
    rationale_demo_fallback: Mapped[bool] = mapped_column(Boolean, server_default="false")
    injection_suspected: Mapped[bool] = mapped_column(Boolean, server_default="false")
    digest_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feedback: Mapped[MatchFeedback | None] = mapped_column(pg_enum(MatchFeedback, "match_feedback"))
    feedback_reason: Mapped[str | None] = mapped_column(String(40))
    feedback_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
