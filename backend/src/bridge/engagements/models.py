"""The ``engagements`` skeleton (REQ-REPO-01; docs/spec/06 6.9).

Phase 2 creates the table so ``can_view_tier2`` can apply the no-WITHDRAWN/DECLINED/TERMINATED rule and the render
marks can switch from handle to display name at ``INTEREST_CONFIRMED``. Rows come from fixtures only: ``bridge_app``
may read but not write them until the Phase 3 state machine (``engagements/state_machine.py``) and
``engagement_events`` arrive.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import EngagementEndReason, EngagementOrigin, EngagementState
from bridge.models.types import pg_enum

DECLINED_REASONS = (
    "'NOT_PRIORITY', 'ALREADY_IN_PROGRESS_INTERNALLY', 'BUDGET', 'NOT_RELEVANT', 'NEEDS_MATURITY', 'OTHER',"
    " 'BY_DEVELOPER'"
)
EXPIRED_REASONS = "'NO_REVIEW', 'NO_DECISION', 'CONTACT_NOT_MADE', 'NO_DEV_RESPONSE'"


class Engagement(IdMixin, TimestampsMixin, Base):
    """One proposal x one organisation (docs/spec/03). ``state`` is the projection of the (Phase 3) event chain."""

    __tablename__ = "engagements"
    __table_args__ = (
        UniqueConstraint("proposal_id", "org_id"),
        ForeignKeyConstraint(
            ["proposal_id", "version_id"],
            ["proposal_versions.proposal_id", "proposal_versions.id"],
            name="fk_engagements_version",
        ),
        # docs/spec/06 6.9 Codes: DECLINED and EXPIRED carry their own reason codes; no other state has one.
        CheckConstraint(
            f"(state = 'DECLINED' AND end_reason IN ({DECLINED_REASONS}))"
            f" OR (state = 'EXPIRED' AND end_reason IN ({EXPIRED_REASONS}))"
            " OR (state NOT IN ('DECLINED', 'EXPIRED') AND end_reason IS NULL)",
            name="end_reason_matches_state",
        ),
        {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "developer_id"}},
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("proposals.id"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    developer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    version_id: Mapped[UUID] = mapped_column()
    origin: Mapped[EngagementOrigin] = mapped_column(pg_enum(EngagementOrigin, "engagement_origin"))
    state: Mapped[EngagementState] = mapped_column(pg_enum(EngagementState, "engagement_state"))
    end_reason: Mapped[EngagementEndReason | None] = mapped_column(
        pg_enum(EngagementEndReason, "engagement_end_reason")
    )
