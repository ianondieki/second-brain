"""Technology trend cards: the tables of revision 0010 (P22 track B, REQ-DEV-02, D-60).

A trend card is drafted by the trend job (bridge_app with no user bound: the weekly run, or a staff admin's manual
run), from the excerpts of official technology publishers, and enters the database only through
``app_create_trend_candidate(card, sources)``: a ``candidate`` with 1 to 5 sources. A staff admin publishes or rejects
it once (``app_decide_trend_card``); then nothing of it changes. Rules the database enforces (revision 0010; the
publisher allowlist, the research checks and the daily rotation are the application's):

- ``trend_cards`` and ``trend_card_sources`` (tenancy CURATED): staff admin reads every row, a developer
  (``app_is_developer()``: never staff) the published cards and their sources; nobody else any. bridge_app writes
  neither table directly and never reads ``decided_by`` (who decided is the audit log's): deferred with raiseload.
  The weekly job (no user bound) reads no row: ``app_trend_job_state(since)`` tells it only whether a card that is not
  rejected was created at or after ``since`` and which excerpts such cards cite.
- A card's title (120), summary (600), topic slug (lower-case words joined by hyphens, 40), optional confidence (0
  to 1, three decimals) and generating call's trace id, and named organisations (as ``problems.named_orgs``: at most
  10, each 1 to 200 characters, distinct) never change; its status moves once, ``candidate`` to ``published``
  (``published_at`` set, and only with a source) or ``rejected``.
- A source sits at ``position`` 1 to 5 of its card (so a card has at most five), added only while the card is a
  candidate and never changed: an https URL (the research rule, 400), a publisher (160), the published and retrieved
  dates (retrieved on or after published), a quote (600), the saved excerpt's id (``excerpt_ref``) and what the source
  supports in the card (400).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from bridge.events.models import https_url
from bridge.models.base import Base, IdMixin, Tenancy

CURATED = {"info": {"tenancy": Tenancy.CURATED}}

CARD_STATUSES = ("candidate", "published", "rejected")
CARD_DECISIONS = ("publish", "reject")  # app_decide_trend_card's p_decision
TITLE_MAX_CHARS = 120
SUMMARY_MAX_CHARS = 600
TOPIC_SLUG_MAX_CHARS = 40
TRACE_ID_MAX_CHARS = 80
NAMED_ORGS_MAX = 10
NAMED_ORG_MAX_CHARS = 200
SOURCES_MIN, SOURCES_MAX = 1, 5
PUBLISHER_MAX_CHARS = 160
QUOTE_MAX_CHARS = 600
SUPPORT_MAX_CHARS = 400
EXCERPT_REF = "^[A-Za-z0-9_.:-]{1,32}$"  # problem_sources.excerpt_ref (revision 0005)
TOPIC_SLUG = "^[a-z0-9]+(-[a-z0-9]+)*$"
TRACE_ID = f"^[A-Za-z0-9._:-]{{1,{TRACE_ID_MAX_CHARS}}}$"


def _text(column: str, max_chars: int) -> str:
    """Not blank, at most ``max_chars`` characters, no control character."""
    return f"{column} ~ '[^[:space:]]' AND char_length({column}) <= {max_chars} AND {column} !~ '[[:cntrl:]]'"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


CARD_DECISION_COMPLETE = (
    "(decided_by IS NULL) = (decided_at IS NULL) AND (status = 'candidate') = (decided_at IS NULL)"
    " AND (status = 'published') = (published_at IS NOT NULL)"
)


class TrendCard(IdMixin, Base):
    """A technology trend card (a research-card type), labelled "Trend · AI-drafted, human-reviewed on {date}" once
    published. Inserted only by ``app_create_trend_candidate``; decided only by ``app_decide_trend_card``."""

    __tablename__ = "trend_cards"
    __table_args__ = (
        Index("ix_trend_cards_status_published_at", "status", "published_at"),
        CheckConstraint(_text("title", TITLE_MAX_CHARS), name="title_valid"),
        CheckConstraint(_text("summary", SUMMARY_MAX_CHARS), name="summary_valid"),
        CheckConstraint(
            f"topic_slug ~ '{TOPIC_SLUG}' AND char_length(topic_slug) <= {TOPIC_SLUG_MAX_CHARS}",
            name="topic_slug_valid",
        ),
        CheckConstraint(_in("status", CARD_STATUSES), name="status_known"),
        CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint(f"llm_trace_id IS NULL OR llm_trace_id ~ '{TRACE_ID}'", name="llm_trace_id_valid"),
        CheckConstraint(
            f"app_text_set_is_valid(named_orgs, {NAMED_ORGS_MAX}, {NAMED_ORG_MAX_CHARS})"
            " AND array_to_string(named_orgs, ' ') !~ '[[:cntrl:]]'",
            name="named_orgs_valid",
        ),
        CheckConstraint(CARD_DECISION_COMPLETE, name="decision_complete"),
        CURATED,
    )

    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    topic_slug: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'candidate'"))  # CARD_STATUSES
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    llm_trace_id: Mapped[str | None] = mapped_column(Text)
    # Who decided is the audit log's: bridge_app holds no SELECT on it (never select it).
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), deferred=True, deferred_raiseload=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    named_orgs: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))


class TrendCardSource(IdMixin, Base):
    """One source of a trend card, at ``position`` 1 to 5 (the order the card cites them). Inserted only with its card
    by ``app_create_trend_candidate``; never changed."""

    __tablename__ = "trend_card_sources"
    __table_args__ = (
        UniqueConstraint("card_id", "position"),
        CheckConstraint(f"position BETWEEN {SOURCES_MIN} AND {SOURCES_MAX}", name="position_range"),
        CheckConstraint(https_url("url"), name="url_valid"),
        CheckConstraint(_text("publisher", PUBLISHER_MAX_CHARS), name="publisher_valid"),
        CheckConstraint("retrieved_at >= published_date", name="retrieved_after_published"),
        CheckConstraint(_text("quote", QUOTE_MAX_CHARS), name="quote_valid"),
        CheckConstraint(f"excerpt_ref ~ '{EXCERPT_REF}'", name="excerpt_ref_format"),
        CheckConstraint(_text("support", SUPPORT_MAX_CHARS), name="support_valid"),
        CURATED,
    )

    card_id: Mapped[UUID] = mapped_column(ForeignKey("trend_cards.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(SmallInteger)
    url: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text)
    published_date: Mapped[date] = mapped_column(Date)
    retrieved_at: Mapped[date] = mapped_column(Date)
    quote: Mapped[str] = mapped_column(Text)
    excerpt_ref: Mapped[str] = mapped_column(Text)
    support: Mapped[str] = mapped_column(Text)
