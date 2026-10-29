"""Accounts, credentials and sessions (REQ-AUTH-01). Tenancy SYSTEM: looked up before any tenant context exists
(login, session cookie, magic link), so these tables have no RLS; only ``bridge.auth`` reads them."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import AuthProvider, LoginTokenPurpose, StaffRole, UserStatus
from bridge.models.types import CIText, pg_enum

SYSTEM = {"info": {"tenancy": Tenancy.SYSTEM}}


class User(IdMixin, TimestampsMixin, Base):
    __tablename__ = "users"
    __table_args__ = (SYSTEM,)
    # subject_salt is a column of the table but not of the mapper: the ORM never selects, returns or writes it (the app
    # role holds no SELECT on it). Digests come from the database: app_subject_digest(user_id, data).
    __mapper_args__ = {"exclude_properties": ["subject_salt"]}  # noqa: RUF012

    email: Mapped[str] = mapped_column(CIText(), unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(120))
    locale: Mapped[str] = mapped_column(String(8), server_default="en")
    staff_role: Mapped[StaffRole | None] = mapped_column(pg_enum(StaffRole, "staff_role"))
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"), server_default=UserStatus.ACTIVE.value
    )
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_pending_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_last_counter: Mapped[int | None] = mapped_column()
    totp_recovery_hashes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    # Per-subject salt (revision 0002): owner refs SHA-256(subject_salt || user_id) in manifests and salted digests in
    # audit payloads (docs/spec/06 6.4). Set once by the database; the app neither reads nor updates it and gets the
    # digests from app_subject_digest(). Unmapped (see __mapper_args__); declared here so the table matches.
    subject_salt = mapped_column(LargeBinary, server_default=text("gen_random_bytes(32)"), nullable=False)
    # Revision 0003 (D-37): an account of the seeded demo data, the only data a free LLM provider may receive. Set only
    # by the owner role (the seed); bridge_app may read it but neither insert nor update it, so never set it in app
    # code (an INSERT naming the column is refused).
    demo_account: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class AuthIdentity(IdMixin, CreatedMixin, Base):
    """OAuth identities (GitHub, Google): REQ-AUTH-02, Phase 2 (D-20). Table created now so the schema is stable."""

    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "subject"), SYSTEM)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[AuthProvider] = mapped_column(pg_enum(AuthProvider, "auth_provider"))
    subject: Mapped[str] = mapped_column(String(255))


class Session(IdMixin, CreatedMixin, Base):
    """Server-side session; the cookie holds a random token, the table only its SHA-256."""

    __tablename__ = "sessions"
    __table_args__ = (SYSTEM,)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    mfa_pending: Mapped[bool] = mapped_column(Boolean, server_default="false")
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(200))


class LoginToken(IdMixin, CreatedMixin, Base):
    """Single-use magic-link token (login or email verification); only its SHA-256 is stored."""

    __tablename__ = "login_tokens"
    __table_args__ = (SYSTEM,)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    purpose: Mapped[LoginTokenPurpose] = mapped_column(pg_enum(LoginTokenPurpose, "login_token_purpose"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginAttempt(IdMixin, CreatedMixin, Base):
    """Login throttle ledger (5/min per IP and per account, docs/spec/08). Keyed by HMAC digests, never raw values."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_digest_created_at", "email_digest", "created_at"),
        Index("ix_login_attempts_ip_digest_created_at", "ip_digest", "created_at"),
        SYSTEM,
    )

    email_digest: Mapped[bytes] = mapped_column(LargeBinary)
    ip_digest: Mapped[bytes] = mapped_column(LargeBinary)
    succeeded: Mapped[bool] = mapped_column(Boolean)


class ApiToken(IdMixin, CreatedMixin, Base):
    """Scoped personal tokens (local companion --platform, Release 2). Only the SHA-256 is stored."""

    __tablename__ = "api_tokens"
    __table_args__ = (SYSTEM,)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
