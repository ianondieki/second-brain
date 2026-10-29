"""Plans, subscriptions and payments (REQ-BIL-01, REQ-BIL-08; docs/spec/05). Prices are placeholders from
``config/plans.yaml`` until G3."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import BillingInterval, PaymentStatus, PlanSide, SubscriptionStatus
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


class Payment(IdMixin, TimestampsMixin, Base):
    """One checkout of a paid plan (docs/spec/05; REQ-BIL-04 interface; revision 0005). The prototype's provider is the
    fake one only (``FakePaymentProvider``, D-36); no phone number is stored.

    The subject (the user, or the organisation's owner, admin or finance member) inserts it pending, for an active,
    non-default plan of the subject's side at exactly its price, with a platform-generated ``provider_ref``. Nothing
    else is the app's: ``app_settle_payment`` settles it once (``settled_at`` is the database's clock) and
    ``app_activate_paid_subscription`` links the subscription it activated (idempotent). ``payments_guard`` refuses
    DELETE and every other change, for every role. Refresh the row after calling either function.
    """

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (org_id IS NULL)", name="one_subject"),
        CheckConstraint("amount_kes_minor > 0", name="amount_positive"),
        CheckConstraint("provider IN ('fake')", name="provider_known"),
        CheckConstraint("provider_ref ~ '^[A-Za-z0-9_-]{16,64}$'", name="provider_ref_format"),
        CheckConstraint("(status = 'pending') = (settled_at IS NULL)", name="settled_unless_pending"),
        CheckConstraint(
            "failure_code IS NULL OR (status IN ('failed', 'cancelled') AND failure_code ~ '^[a-z][a-z0-9_]{0,39}$')",
            name="failure_code_when_failed",
        ),
        CheckConstraint("subscription_id IS NULL OR status = 'succeeded'", name="linked_only_when_succeeded"),
        {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "user_id"}},
    )

    # No ON DELETE CASCADE: payment records outlive their subject (erasure pseudonymises; REQ-SEC-02).
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    org_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("plans.id"))
    amount_kes_minor: Mapped[int] = mapped_column(BigInteger)
    provider: Mapped[str] = mapped_column(String(16))
    provider_ref: Mapped[str] = mapped_column(String(64), unique=True)  # platform-generated
    status: Mapped[PaymentStatus] = mapped_column(
        pg_enum(PaymentStatus, "payment_status"),
        server_default=PaymentStatus.PENDING.value,
    )
    initiated_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the database's clock
    subscription_id: Mapped[UUID | None] = mapped_column(ForeignKey("subscriptions.id"), unique=True)
    failure_code: Mapped[str | None] = mapped_column(String(40))  # a code, never free text
