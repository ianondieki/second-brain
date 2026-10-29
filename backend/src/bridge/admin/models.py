"""Admin-editable reference data and the staff moderation queue: the Kenyan holiday calendar (REQ-BD-01, used by
REQ-REM-00's business-day helper) and ``moderation_cases`` (REQ-MOD-01, REQ-ADM-01; docs/spec/06 6.12)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import ModerationCaseStatus, ModerationSource
from bridge.models.types import pg_enum


class Holiday(IdMixin, CreatedMixin, Base):
    """A public holiday as observed (a Sunday holiday moves to the next day, Public Holidays Act s.4)."""

    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("country", "observed_on", "name"), {"info": {"tenancy": Tenancy.GLOBAL}})

    country: Mapped[str] = mapped_column(String(2))
    holiday_on: Mapped[date] = mapped_column(Date)
    observed_on: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(120))
    provisional: Mapped[bool] = mapped_column(Boolean, server_default="false")
    source_url: Mapped[str | None] = mapped_column(String(500))


class ModerationCase(IdMixin, TimestampsMixin, Base):
    """One item in the moderation queue (Tenancy STAFF): staff admin/moderator read and decide it. A user's report is
    inserted by the app with ``reporter_id`` = that user (open, no classifier); the system sources (regex holds, the
    Tier-1 pre-screen, claim disputes, the Tier-2 similarity job) file through ``app_open_moderation_case``, which
    checks the caller against the subject and returns the case id. ``classifier`` holds the pre-screen output over
    Tier-1 fields only. Changing a subject's ``moderation_state`` is a separate step through
    ``app_moderate_proposal`` / ``app_moderate_problem``. A report of an engagement message (``subject_type =
    'message'``, revision 0008) is filed only through ``app_report_message`` (once per reporter and message) and read
    by staff only through ``app_reported_message``; a team message report (``subject_type = 'team_message'``, revision
    0011) only through ``app_report_team_message`` and ``app_reported_team_message``."""

    __tablename__ = "moderation_cases"
    # Inserted by callers that may not read the new row back (no SELECT grant or policy), so the ORM must not add
    # RETURNING for server defaults.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012
    __table_args__ = (
        Index("ix_moderation_cases_subject", "subject_type", "subject_id"),
        Index("ix_moderation_cases_status_created_at", "status", "created_at"),
        # Revision 0008: one report per reporter and engagement message.
        Index(
            "uq_moderation_cases_message_report",
            "subject_id",
            "reporter_id",
            unique=True,
            postgresql_where=text("subject_type = 'message' AND source = 'report'"),
        ),
        # Revision 0011: one report per reporter and team message.
        Index(
            "uq_moderation_cases_team_message_report",
            "subject_id",
            "reporter_id",
            unique=True,
            postgresql_where=text("subject_type = 'team_message' AND source = 'report'"),
        ),
        # 1 to 50 non-blank reasons of at most 200 characters (app_reasons_are_valid, revision 0002).
        CheckConstraint("app_reasons_are_valid(reasons, 50)", name="reasons_valid"),
        {"info": {"tenancy": Tenancy.STAFF}},
    )

    subject_type: Mapped[str] = mapped_column(String(40))  # proposal, problem, org_claim, message, user, ...
    subject_id: Mapped[UUID] = mapped_column()
    reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    source: Mapped[ModerationSource] = mapped_column(pg_enum(ModerationSource, "moderation_source"))
    status: Mapped[ModerationCaseStatus] = mapped_column(
        pg_enum(ModerationCaseStatus, "moderation_case_status"), server_default=ModerationCaseStatus.OPEN.value
    )
    classifier: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reporter_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    assigned_to: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
