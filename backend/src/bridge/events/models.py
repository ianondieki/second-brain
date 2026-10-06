"""This week's events: the tables of revision 0010 (P22 track B, REQ-DEV-02, D-60, D-61).

Rules the database enforces (revision 0010; the E2 verification of the posting organisation, the Nairobi week, the
Home strip and the reminders' timing are the application's):

- ``events`` (tenancy PUBLISHED: an organisation's when ``org_id`` is set, the platform's otherwise). Posted as a
  ``draft`` by an editor of the organisation (owner, admin, signatory or reviewer: the Briefs' editors) for that
  organisation, or by a staff admin with no organisation ("Platform"); ``created_by`` is the poster. The poster edits
  the content columns while it is a draft, and nobody edits them after. ``status`` moves only from ``draft`` to
  ``published`` or ``rejected`` (``app_decide_event``: staff admin or moderator) or ``cancelled``, and from
  ``published`` to ``cancelled`` (``app_cancel_event``: staff, an editor of the organisation); ``decided_*`` and
  ``cancelled_at`` come with it. Readers: staff admin and moderator every event, a developer (``app_is_developer()``:
  never staff) the published ones, an organisation's active members its events in any status; nobody else any.
  bridge_app never reads ``decided_by`` (who decided is the audit log's): it is deferred with raiseload.
- An event is online with a join URL (no venue, no county) or in person at a venue in a county (no join URL); it ends
  after it starts and at most three days later; every URL is https on an ASCII host, without user info or whitespace,
  at most 400 characters.
- ``event_reminders`` (tenancy USER): a developer's "Remind me", one row per developer and event, inserted on a
  published event that has not ended and deleted by Decline; never updated; read by its developer only (no staff
  read). The reminder job (bridge_app with no user bound) lists due rows only through ``app_event_reminders_due(now)``,
  then reads and writes as each developer (``bind_tenant``), as the other reminder jobs do.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, FetchedValue, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, IdMixin, Tenancy

PUBLISHED = {"info": {"tenancy": Tenancy.PUBLISHED, "tenant_column": "org_id", "user_column": "created_by"}}
USER = {"info": {"tenancy": Tenancy.USER, "tenant_column": "user_id"}}

EVENT_STATUSES = ("draft", "published", "rejected", "cancelled")
EVENT_DECISIONS = ("publish", "reject")  # app_decide_event's p_decision
EDITOR_ROLES = ("owner", "admin", "signatory", "reviewer")  # who posts, edits and cancels an organisation's events
TITLE_MAX_CHARS = 120
DESCRIPTION_MAX_CHARS = 1000
VENUE_MAX_CHARS = 160
URL_MAX_CHARS = 400
MAX_SPAN_DAYS = 3


def _text(column: str, max_chars: int) -> str:
    """Not blank, at most ``max_chars`` characters, no control character."""
    return f"{column} ~ '[^[:space:]]' AND char_length({column}) <= {max_chars} AND {column} !~ '[[:cntrl:]]'"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def https_url(column: str, max_chars: int = URL_MAX_CHARS) -> str:
    """The research sources' URL rule (``app_research_source_is_valid``, revision 0005): https on an ASCII host
    (letters, digits, dots and hyphens, an optional port), no user info, no whitespace, no control character."""
    return (
        f"{column} ~ '^https://[A-Za-z0-9.-]+(:[0-9]+)?(/[^[:space:]]*)?$' AND {column} !~ '[[:cntrl:]]'"
        f" AND char_length({column}) <= {max_chars}"
    )


# Plain text over lines: tab, line feed and carriage return are allowed, no other control character.
DESCRIPTION_VALID = (
    f"description ~ '[^[:space:]]' AND char_length(description) <= {DESCRIPTION_MAX_CHARS}"
    " AND description !~ '[\\x01-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]'"
)
PLACE_VALID = (
    "(online AND join_url IS NOT NULL AND venue IS NULL AND county_code IS NULL)"
    " OR (NOT online AND venue IS NOT NULL AND county_code IS NOT NULL AND join_url IS NULL)"
)
SPAN_VALID = f"ends_at > starts_at AND ends_at <= starts_at + interval '{MAX_SPAN_DAYS} days'"
DECISION_COMPLETE = (
    "(decided_by IS NULL) = (decided_at IS NULL) AND (status = 'cancelled') = (cancelled_at IS NOT NULL)"
    " AND CASE status WHEN 'draft' THEN decided_at IS NULL WHEN 'cancelled' THEN true ELSE decided_at IS NOT NULL END"
)


class Event(IdMixin, Base):
    """A technology event posted by an organisation's editor (``org_id``) or a staff admin (``org_id`` NULL: the
    platform). bridge_app inserts ``id``, ``org_id``, ``created_by`` (the caller) and the content columns as a draft
    (``status`` is the database's default), updates the content columns of its own draft only, and never deletes;
    ``updated_at`` is the database's (``events_guard``: the shared clock on every content or status change, never
    what was sent; read it back). Decisions and cancellations only through ``app_decide_event`` and
    ``app_cancel_event``. The E2 verification of the posting organisation is the application's check (as for Briefs),
    not the database's."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_status_starts_at", "status", "starts_at"),
        Index("ix_events_org_id_created_at", "org_id", "created_at"),
        Index("ix_events_county_code_published", "county_code", postgresql_where=text("status = 'published'")),
        CheckConstraint(_text("title", TITLE_MAX_CHARS), name="title_valid"),
        CheckConstraint(DESCRIPTION_VALID, name="description_valid"),
        CheckConstraint(SPAN_VALID, name="span_valid"),
        CheckConstraint(PLACE_VALID, name="place_valid"),
        CheckConstraint(f"venue IS NULL OR ({_text('venue', VENUE_MAX_CHARS)})", name="venue_valid"),
        CheckConstraint(f"join_url IS NULL OR ({https_url('join_url')})", name="join_url_valid"),
        CheckConstraint(f"link IS NULL OR ({https_url('link')})", name="link_valid"),
        CheckConstraint(_in("status", EVENT_STATUSES), name="status_known"),
        CheckConstraint(DECISION_COMPLETE, name="decision_complete"),
        PUBLISHED,
    )

    org_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    online: Mapped[bool] = mapped_column(Boolean)
    venue: Mapped[str | None] = mapped_column(Text)
    county_code: Mapped[str | None] = mapped_column(ForeignKey("regions.code"))
    join_url: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))  # EVENT_STATUSES
    # Who decided is the audit log's: bridge_app holds no SELECT on it (never select it).
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), deferred=True, deferred_raiseload=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))
    # The database's (events_guard sets it on every content or status change): an ORM edit expires it, so the next
    # read (a reviewer's ``seen``) is the stored value, never a stale one.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("app_clock_now()"), server_onupdate=FetchedValue()
    )


class EventReminder(Base):
    """A developer's "Remind me" on a published event (N26 by email the day before, N27 in-app the morning of): the app
    inserts ``user_id`` (the caller) and ``event_id`` while the event is published and has not ended, and deletes the
    row on Decline; ``created_at`` is the database's clock. Never updated."""

    __tablename__ = "event_reminders"
    __table_args__ = (Index("ix_event_reminders_event_id", "event_id"), USER)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))
