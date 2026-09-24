"""Notification preferences, the delivery ledger, in-app notifications and email suppressions (REQ-NOT-01)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import DeliveryStatus, NotificationChannel, SuppressionReason
from bridge.models.types import CIText, pg_enum

USER = {"info": {"tenancy": Tenancy.USER, "tenant_column": "user_id"}}


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (USER,)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    channel: Mapped[NotificationChannel] = mapped_column(
        pg_enum(NotificationChannel, "notification_channel"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")


class NotificationDelivery(IdMixin, TimestampsMixin, Base):
    """One message to one recipient on one channel. ``dedupe_key`` makes a send idempotent (for example one EM7 per
    user, channel and local date, AC-MAIL-3). Bodies are not stored; ``to_address`` is kept for bounce handling."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        CheckConstraint("user_id IS NOT NULL OR org_id IS NOT NULL", name="has_recipient_scope"),
        {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "user_id"}},
    )

    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    org_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    channel: Mapped[NotificationChannel] = mapped_column(pg_enum(NotificationChannel, "notification_channel"))
    to_address: Mapped[str] = mapped_column(String(320))
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    local_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[DeliveryStatus] = mapped_column(
        pg_enum(DeliveryStatus, "delivery_status"), server_default=DeliveryStatus.QUEUED.value
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_transient: Mapped[bool | None] = mapped_column(Boolean)
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InAppNotification(IdMixin, CreatedMixin, Base):
    __tablename__ = "in_app_notifications"
    __table_args__ = (USER,)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(500))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailSuppression(IdMixin, CreatedMixin, Base):
    """Addresses never emailed again (bounce, complaint, unsubscribe, manual). Checked before every send."""

    __tablename__ = "email_suppressions"
    __table_args__ = ({"info": {"tenancy": Tenancy.SYSTEM}},)

    email: Mapped[str] = mapped_column(CIText(), unique=True)
    reason: Mapped[SuppressionReason] = mapped_column(pg_enum(SuppressionReason, "suppression_reason"))
    source: Mapped[str | None] = mapped_column(String(80))
