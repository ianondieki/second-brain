"""Admin-editable reference data: the Kenyan holiday calendar (REQ-BD-01, used by REQ-REM-00's business-day helper)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy


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
