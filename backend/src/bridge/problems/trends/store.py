"""Trend cards in the database (REQ-DEV-02; D-60; P22 card B, default (5)): storing the week's candidates, the job's
look back, the trend of the day, a developer's card and the named-organisation rule on a stored card.

- ``store_candidates(db, accepted)``: one ``app_create_trend_candidate(p_card, p_sources)`` per kept card, in the
  model's order, in the caller's transaction (the job: with no user bound, or a staff admin's manual run). The card's
  confidence goes as a JSON number (``numeric(4,3)``), everything else as ``draft_trends`` copied it from the saved
  excerpts. Returns the new ids.
- ``job_state(db, since)``: whether a candidate or published card was created since ``since`` (the weekly job then
  makes no call) and the excerpt ids the candidate and published cards cite (never sent again, so a week does not
  redraft a card staff have). Read under the session's own binding: a staff admin reads every card; a session with no
  user bound reads none (revision 0010 gives the job no reader), so it answers None and the job does nothing.
- ``trend_of_day(db, today)``: the published cards ordered by ``published_at, id``, the one at index
  ``today.toordinal() mod count`` (today: the Nairobi day on the shared clock when not given), in one statement.
- ``published_card(db, id)``: a published card with its sources, for its page (None for anything else).
- ``unsourced_names(...)``: the rule ``draft_trends`` applied (``bridge.problems.trends.checks``), repeated on what is
  stored: every organisation the card names (the TECH allowlist's found in its text and its own ``named_orgs``) must
  be named by a stored source, in its quote or as its publisher, and no capitalised name may appear that no source
  carries. The staff decision refuses to publish otherwise (409 ``unsourced_name``), so a card that did not come
  through the checks cannot be published naming an organisation without a source.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.engagements.calendar import NAIROBI
from bridge.events.schemas import TrendCardDetailOut, TrendCardOut, TrendSourceOut
from bridge.problems.research.checks import named_organisations
from bridge.problems.research.sources import TECH, CatalogueKind, Excerpt, get_catalogue, url_host
from bridge.problems.trends.checks import unsourced_capitalised
from bridge.problems.trends.checks import unsourced_names as names_without_source
from bridge.problems.trends.run import Accepted, TrendCandidate
from bridge.trends.models import TrendCard, TrendCardSource

_CREATE: Final = text("SELECT app_create_trend_candidate(CAST(:card AS jsonb), CAST(:sources AS jsonb))")
# The day's index over the published cards: ``today.toordinal()`` when given, else the Nairobi day on the shared clock.
_OF_THE_DAY: Final = text(
    "SELECT t.id, t.title, t.summary, t.topic_slug, t.published_at FROM (SELECT c.id, c.title, c.summary,"
    " c.topic_slug, c.published_at, row_number() OVER (ORDER BY c.published_at, c.id) - 1 AS i,"
    " count(*) OVER () AS n FROM trend_cards c WHERE c.status = 'published') t"
    " WHERE t.i = mod(coalesce(CAST(:ordinal AS bigint), app_nairobi_today() - DATE '0001-01-01' + 1), t.n)"
)
_RECENT: Final = text(
    "SELECT EXISTS (SELECT 1 FROM trend_cards WHERE status IN ('candidate', 'published') AND created_at >= :since)"
    " AS recent, app_user_id() IS NOT NULL AND app_is_staff('{admin}') AS reader"
)
_CITED: Final = text(
    "SELECT DISTINCT s.excerpt_ref FROM trend_card_sources s JOIN trend_cards c ON c.id = s.card_id"
    " WHERE c.status IN ('candidate', 'published')"
)


def card_json(card: TrendCandidate) -> str:
    """``p_card``: ``TrendCandidate.p_card()`` with the confidence as a JSON number."""
    found: dict[str, Any] = dict(card.p_card())
    found["confidence"] = float(card.confidence)
    return json.dumps(found)


async def store_candidates(db: AsyncSession, accepted: Accepted) -> list[UUID]:
    """Every kept card of ``accepted`` as a candidate, in order (the caller commits)."""
    stored = []
    for card in accepted.cards:
        params = {"card": card_json(card), "sources": json.dumps(card.p_sources())}
        stored.append(UUID(str((await db.execute(_CREATE, params)).scalar_one())))
    return stored


@dataclass(frozen=True, slots=True)
class JobState:
    recent: bool  # a candidate or published card created since the look-back's start
    cited: frozenset[str]  # excerpt ids the candidate and published cards cite


async def job_state(db: AsyncSession, since: datetime) -> JobState | None:
    """The weekly job's look back (see the module docstring); None when the session cannot read the cards."""
    row = (await db.execute(_RECENT, {"since": since})).one()
    if not row.reader:
        return None
    cited = frozenset(str(ref) for ref in (await db.scalars(_CITED)).all())
    return JobState(bool(row.recent), cited)


def reviewed_on(published_at: datetime) -> date:
    return published_at.astimezone(NAIROBI).date()


def _card_out(row: Any) -> TrendCardOut:
    return TrendCardOut(
        id=row.id,
        title=row.title,
        summary=row.summary,
        topic_slug=row.topic_slug,
        published_at=row.published_at,
        reviewed_on=reviewed_on(row.published_at),
    )


async def trend_of_day(db: AsyncSession, today: date | None = None) -> TrendCardOut | None:
    """The published card of ``today`` (see the module docstring), in one statement."""
    ordinal = None if today is None else today.toordinal()
    row = (await db.execute(_OF_THE_DAY, {"ordinal": ordinal})).one_or_none()
    return None if row is None else _card_out(row)


async def published_card(db: AsyncSession, card_id: UUID) -> TrendCardDetailOut | None:
    """A published card with its sources in order, as the caller reads it (None otherwise)."""
    C, S = TrendCard, TrendCardSource
    row = (
        await db.execute(
            select(C.id, C.title, C.summary, C.topic_slug, C.published_at, C.named_orgs).where(
                C.id == card_id, C.status == "published"
            )
        )
    ).one_or_none()
    if row is None:
        return None
    sources = (
        await db.execute(
            select(S.url, S.publisher, S.published_date, S.retrieved_at, S.quote)
            .where(S.card_id == card_id)
            .order_by(S.position)
        )
    ).all()
    return TrendCardDetailOut(
        **_card_out(row).model_dump(),
        named_orgs=list(row.named_orgs),
        sources=[TrendSourceOut.model_validate(s, from_attributes=True) for s in sources],
    )


@dataclass(frozen=True, slots=True)
class StoredSource:
    url: str
    publisher: str
    published_date: date
    retrieved_at: date
    quote: str
    excerpt_ref: str


def _as_excerpt(source: StoredSource, topic: str) -> Excerpt:
    return Excerpt(
        id=source.excerpt_ref,
        niche=topic,
        country=TECH,
        url=source.url,
        host=url_host(source.url) or "",
        publisher=source.publisher,
        source_type="official",
        official=True,
        published_date=source.published_date,
        retrieved_at=source.retrieved_at,
        quote=source.quote,
        topic=topic,
    )


def unsourced_names(
    title: str, summary: str, topic: str, named_orgs: Sequence[str], sources: Sequence[StoredSource]
) -> tuple[str, ...]:
    """The names a stored card carries that no stored source names (see the module docstring); empty when it may be
    published."""
    allowlist = get_catalogue(CatalogueKind.TRENDS).allowlists[TECH]
    excerpts = [_as_excerpt(source, topic) for source in sources]
    names = named_organisations((title, summary), named_orgs, allowlist)
    found = names_without_source(names, excerpts, allowlist) + unsourced_capitalised(
        title, summary, excerpts, allowlist
    )
    return tuple(dict.fromkeys(found))
