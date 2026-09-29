"""Problems, sources, research runs, Problem Briefs and brief invitations (REQ-DIR-05, REQ-PROP-01, REQ-RES-01;
docs/spec/06 6.2, 6.3, 6.5).

Tenancy PUBLISHED: the creator (or, for a Brief, the organisation's members) reads and writes a problem; every
signed-in user reads published problems clear of moderation holds (an org Brief's problem only when the Brief itself
is visible to them); ``candidate`` problems (research output) are readable by staff only. ``moderation_state`` and
``status`` change only through the staff functions of revision 0002.

Research (revision 0005): a staff admin's ``research_runs`` row (tenancy STAFF, staff admin only) is the unit of a
run; its cards enter only through ``app_create_research_candidate`` (a ``candidate`` with ``created_by`` NULL,
``research_run_id``, ``named_orgs`` and sources with ``excerpt_ref``; bridge_app neither inserts nor updates those
columns), and ``problems_research_guard`` refuses to publish a research card without one official source or two
distinct publishers (AC-RES-1), or one naming an organisation without an official source.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import (
    BriefStatus,
    BriefVisibility,
    ModerationState,
    ProblemSource,
    ProblemStatus,
    ResearchRunStatus,
)
from bridge.models.types import Vector, pg_enum


class Problem(IdMixin, TimestampsMixin, Base):
    __tablename__ = "problems"
    __table_args__ = (
        UniqueConstraint("id", "org_id"),  # target of problem_briefs (problem_id, org_id)
        CheckConstraint("app_text_set_is_valid(named_orgs, 10, 200)", name="named_orgs_valid"),
        CheckConstraint("research_run_id IS NULL OR source = 'research_agent'", name="research_run_only_for_research"),
        {"info": {"tenancy": Tenancy.PUBLISHED, "tenant_column": "org_id", "user_column": "created_by"}},
    )

    source: Mapped[ProblemSource] = mapped_column(pg_enum(ProblemSource, "problem_source"))
    niche_id: Mapped[UUID | None] = mapped_column(ForeignKey("niches.id"), index=True)
    country: Mapped[str] = mapped_column(String(2), server_default="KE")
    county_code: Mapped[str | None] = mapped_column(ForeignKey("regions.code"))
    title: Mapped[str] = mapped_column(String(90))
    statement: Mapped[str] = mapped_column(Text)
    affected_group: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[ProblemStatus] = mapped_column(
        pg_enum(ProblemStatus, "problem_status"), server_default=ProblemStatus.PENDING_REVIEW.value
    )
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    org_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"), index=True)  # Briefs only
    ai_generated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    cluster_id: Mapped[UUID | None] = mapped_column()
    moderator_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    moderation_state: Mapped[ModerationState] = mapped_column(
        pg_enum(ModerationState, "moderation_state"), server_default=ModerationState.CLEAR.value
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    embed_model: Mapped[str | None] = mapped_column(String(80))
    embed_version: Mapped[str | None] = mapped_column(String(40))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Revision 0005 (research cards only; written by app_create_research_candidate, never by the app role).
    research_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("research_runs.id"), index=True)
    named_orgs: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")  # <= 10 (D-45)


class ProblemCitation(IdMixin, CreatedMixin, Base):
    """A cited source of a problem (research agent citations, links a Brief author adds)."""

    __tablename__ = "problem_sources"
    __table_args__ = (
        CheckConstraint("excerpt_ref IS NULL OR excerpt_ref ~ '^[A-Za-z0-9_.:-]{1,32}$'", name="excerpt_ref_format"),
        {"info": {"tenancy": Tenancy.PUBLISHED, "via": "problems"}},
    )

    problem_id: Mapped[UUID] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    publisher: Mapped[str | None] = mapped_column(String(200))
    source_type: Mapped[str | None] = mapped_column(String(40))
    published_date: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quote: Mapped[str | None] = mapped_column(Text)
    excerpt_ref: Mapped[str | None] = mapped_column(String(32))  # the saved excerpt's id (revision 0005)


class ResearchRun(IdMixin, TimestampsMixin, Base):
    """One research run per (niche, region) by a staff admin (docs/spec/06 6.5; revision 0005). ``created_at`` is its
    start. The caps are CHECKs (AC-RES-3: at most 25 searches and 40 fetches); a stopped or failed run carries a stop
    reason (a code). Tenancy STAFF: staff admin reads, inserts (as ``started_by``) and updates; nobody else sees it."""

    __tablename__ = "research_runs"
    __table_args__ = (
        CheckConstraint("searches BETWEEN 0 AND 25 AND fetches BETWEEN 0 AND 40", name="run_caps"),
        CheckConstraint("input_tokens >= 0 AND candidates >= 0 AND discarded >= 0", name="counts_not_negative"),
        CheckConstraint("cost_usd BETWEEN 0 AND 100", name="cost_usd_range"),
        CheckConstraint("(status = 'running') = (finished_at IS NULL)", name="finished_unless_running"),
        CheckConstraint(
            "(status IN ('stopped', 'failed')) = (stop_reason IS NOT NULL)"
            " AND (stop_reason IS NULL OR stop_reason ~ '^[a-z][a-z0-9_]{0,39}$')",
            name="stop_reason_is_a_code",
        ),
        {"info": {"tenancy": Tenancy.STAFF}},
    )

    niche_id: Mapped[UUID] = mapped_column(ForeignKey("niches.id"))
    country: Mapped[str] = mapped_column(String(2), server_default="KE")
    county_code: Mapped[str | None] = mapped_column(ForeignKey("regions.code"))
    status: Mapped[ResearchRunStatus] = mapped_column(
        pg_enum(ResearchRunStatus, "research_run_status"), server_default=ResearchRunStatus.RUNNING.value
    )
    started_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    searches: Mapped[int] = mapped_column(Integer, server_default="0")
    fetches: Mapped[int] = mapped_column(Integer, server_default="0")
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    candidates: Mapped[int] = mapped_column(Integer, server_default="0")
    discarded: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default="0")
    stop_reason: Mapped[str | None] = mapped_column(String(40))
    demo_fallback: Mapped[bool] = mapped_column(Boolean, server_default="false")


class ProblemBrief(TimestampsMixin, Base):
    """An organisation's Problem Brief: the problem row holds the ProblemCard fields (``source = org_brief``).
    Public published Briefs are readable by every signed-in user; invited ones by the organisation's members and the
    invited users. Only E2 organisations publish, and only once the problem is published and clear (policy check)."""

    __tablename__ = "problem_briefs"
    __table_args__ = (
        UniqueConstraint("problem_id", "org_id"),  # target of brief_invitations (brief_id, org_id)
        ForeignKeyConstraint(
            ["problem_id", "org_id"],
            ["problems.id", "problems.org_id"],
            name="fk_problem_briefs_problem",
            ondelete="CASCADE",
        ),
        {"info": {"tenancy": Tenancy.ORG, "tenant_column": "org_id"}},
    )

    problem_id: Mapped[UUID] = mapped_column(primary_key=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    visibility: Mapped[BriefVisibility] = mapped_column(
        pg_enum(BriefVisibility, "brief_visibility"), server_default=BriefVisibility.PUBLIC.value
    )
    budget_band: Mapped[str | None] = mapped_column(String(32))  # a band code from config, not an amount
    deadline: Mapped[date | None] = mapped_column(Date)
    status: Mapped[BriefStatus] = mapped_column(
        pg_enum(BriefStatus, "brief_status"), server_default=BriefStatus.DRAFT.value
    )


class BriefInvitation(IdMixin, CreatedMixin, Base):
    """A user invited to an invited-only Brief. ``org_id`` is denormalised (composite foreign key) so the policies of
    ``problem_briefs`` and ``brief_invitations`` never have to read each other recursively."""

    __tablename__ = "brief_invitations"
    __table_args__ = (
        UniqueConstraint("brief_id", "user_id"),
        ForeignKeyConstraint(
            ["brief_id", "org_id"],
            ["problem_briefs.problem_id", "problem_briefs.org_id"],
            name="fk_brief_invitations_brief",
            ondelete="CASCADE",
        ),
        {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "user_id"}},
    )

    brief_id: Mapped[UUID] = mapped_column()
    org_id: Mapped[UUID] = mapped_column(index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
