"""Plans and subscriptions (REQ-BIL-01; docs/spec/05). Prices are placeholders from ``config/plans.yaml`` until G3."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import BillingInterval, PlanSide, SubscriptionStatus
from bridge.models.types import pg_enum

LIVE = "status IN ('trialing', 'active', 'past_due')"


class Plan(IdMixin, TimestampsMixin, Base):
    __tablename__ = "plans"
    __table_args__ = (
        # At most one default plan per side: the free plan a user or organisation may subscribe to self-serve.
        Index("uq_plans_default_side", "side", unique=True, postgresql_where=text("is_default")),
        {"info": {"tenancy": Tenancy.GLOBAL}},
    )

    code: Mapped[str] = mapped_column(String(40), unique=True)
    side: Mapped[PlanSide] = mapped_column(pg_enum(PlanSide, "plan_side"))
    name: Mapped[str] = mapped_column(String(80))
    price_kes_minor: Mapped[int] = mapped_column(BigInteger)
    interval: Mapped[BillingInterval] = mapped_column(pg_enum(BillingInterval, "billing_interval"))
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    version: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    # Set by the seed from config/plans.yaml (`default: true`); the only plans bridge_app may subscribe to directly.
    is_default: Mapped[bool] = mapped_column(Boolean, server_default="false")


class Subscription(IdMixin, TimestampsMixin, Base):
    """A user's or an organisation's plan. At most one live subscription per subject (partial unique indexes)."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (org_id IS NULL)", name="one_subject"),
        Index("uq_subscriptions_live_user", "user_id", unique=True, postgresql_where=text(LIVE)),
        Index("uq_subscriptions_live_org", "org_id", unique=True, postgresql_where=text(LIVE)),
        {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "user_id"}},
    )

    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    org_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[SubscriptionStatus] = mapped_column(pg_enum(SubscriptionStatus, "subscription_status"))
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
