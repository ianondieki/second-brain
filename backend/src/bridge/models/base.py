"""Declarative base, naming convention and table classification for RLS (REQ-TEN-01)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bridge.ids import uuid7

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Tenancy(StrEnum):
    """How a table is scoped. Declared on every table as ``__table_args__ = ({"info": {"tenancy": ...}},)``.

    Optional ``info`` keys used by the generated RLS tests: ``tenant_column`` / ``user_column`` name the owning
    columns, ``via`` names the parent table a child inherits its visibility from, and ``db_role`` names the database
    role that reads the table on the request path when it is not ``bridge_app`` (Tier-2 tables: ``bridge_app`` has
    no privilege on them and switches role with ``bridge.db.as_role``).
    """

    ORG = "org"  # rows belong to one organisation; RLS by membership
    USER = "user"  # rows belong to one user; RLS by app.user_id
    ORG_OR_USER = "org_or_user"  # rows belong to a user or an organisation (e.g. subscriptions)
    # Owner-scoped content (proposals, problems): the owner reads and writes; every signed-in user reads rows that are
    # published, not hidden and clear of moderation holds; staff admin|moderator read everything.
    PUBLISHED = "published"
    # Platform staff tables (moderation queue, invitation approvals): app_is_staff() reads and updates; the app inserts.
    STAFF = "staff"
    # Public registration evidence (provenance_records): every reader reads every row (/verify is anonymous); rows are
    # written only by the worker bound to the owner of the version they register.
    EVIDENCE = "evidence"
    GLOBAL = "global"  # reference data readable by everyone (niches, plans, holidays, regions)
    SYSTEM = "system"  # internal tables with no tenant (auth credentials, sessions, suppressions, jobs)


# Tenancy classes whose tables have Row-Level Security (every other class has none).
RLS_TENANCIES = frozenset(
    {Tenancy.ORG, Tenancy.USER, Tenancy.ORG_OR_USER, Tenancy.PUBLISHED, Tenancy.STAFF, Tenancy.EVIDENCE}
)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class IdMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)


class CreatedMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TimestampsMixin(CreatedMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
