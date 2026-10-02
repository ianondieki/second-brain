"""The facts trends are computed from, read on each request (REQ-TREND-01, REQ-TREND-02; docs/spec/06 6.6).

Two sources only, both as ``bridge_app`` under the caller's Row-Level Security:

- the tables every signed-in user may read: published problems clear of moderation (a Brief's only when the Brief is
  published and visible to the caller), their cited sources' dates and publishers, and published, clear proposals with
  the problems their current version links (Tier 1 and ids only; never a Tier-2 table, a grant, a tag or a view);
- cross-organisation signals only through ``app_trend_aggregates`` (revision 0005, D-46): counts per item, kind and
  day, with no hash and no organisation id; items below 3 distinct actors never come back.

Distinct actors (the ``min_actors`` floor before an item is Trending) are only the people and organisations behind
recent activity, all in the 30-day badge window: developers who published a proposal against the problem, publishers
of sources dated in it, the Brief's organisation when the Brief was posted in it, and the organisations whose scouts
matched a linked proposal in it (a second ``app_trend_aggregates`` call from the window's first Nairobi day; the
definer still counts organisations only from 3). A project's actors are likewise the organisations that expressed
interest in the window. The scores use the whole 180-day window. An old source, an old Brief or last season's scouts
are evidence for the score, never a crowd: a card with three year-old publishers and one new proposal has one actor.

``board`` turns them into trend subjects with the anti-gaming rules of ``bridge.matching.trending`` applied, and
scores them. Owner and creator ids are read only to drop self-boosts and count distinct actors; nothing returned by
the routes carries them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.matching.ranking_config import RankingConfig
from bridge.matching.trending import (
    NAIROBI,
    Aggregate,
    Event,
    Subject,
    Trend,
    nairobi_day,
    once_per_actor_and_day,
    organisation_side,
    trends,
    without_bursts,
)

SCOUT_MATCH: Final = "scout_match"
ORG_INTEREST: Final = "org_interest"
EXAMPLE_REF_PREFIX: Final = "example:"  # bridge.problems.service: a demo seed card's sources

_NOW = text("SELECT app_clock_now()")
_AGGREGATES = text(
    "SELECT item_id, kind, day, events, actors, orgs FROM app_trend_aggregates(:since, :now) WHERE kind = ANY(:kinds)"
)
_PROBLEMS = text(
    "SELECT p.id, p.source::text AS source, p.title, p.statement, p.niche_id, n.parent_id, p.country,"
    " rc.name AS country_name, p.county_code, r.name AS county_name, p.created_by, p.published_at, p.confidence,"
    " p.status::text AS status, o.id AS org_id, o.slug::text AS org_slug, o.legal_name AS org_name"
    " FROM problems p LEFT JOIN niches n ON n.id = p.niche_id"
    " LEFT JOIN regions r ON r.code = p.county_code LEFT JOIN regions rc ON rc.code = p.country"
    " LEFT JOIN organizations o ON o.id = p.org_id"
    " WHERE p.status = 'published' AND p.moderation_state = 'clear' AND (p.source <> 'org_brief' OR EXISTS"
    " (SELECT 1 FROM problem_briefs b WHERE b.problem_id = p.id AND b.status = 'published'))"
)
_SOURCES = text(
    "SELECT problem_id, publisher, url, source_type, published_date, excerpt_ref FROM problem_sources"
    " WHERE problem_id = ANY(:ids)"
)
_PROPOSALS = text(
    "SELECT p.id, p.owner_id, p.niche_id, n.parent_id, p.county_code, p.published_at, pp.problem_id"
    " FROM proposals p JOIN proposal_problems pp ON pp.proposal_version_id = p.current_version_id"
    " LEFT JOIN niches n ON n.id = p.niche_id"
    " WHERE p.status = 'published' AND p.moderation_state = 'clear' AND p.published_at IS NOT NULL"
)


@dataclass(frozen=True, slots=True)
class ProblemFact:
    id: UUID
    source: str
    title: str
    statement: str
    niche_id: UUID | None
    parent_id: UUID | None
    country: str
    country_name: str | None
    county_code: str | None
    county_name: str | None
    created_by: UUID | None
    published_at: datetime | None
    confidence: Decimal | None
    status: str
    seeded_example: bool = False
    # A Brief's organisation as the reader's RLS shows it (listed in the directory): its label and reference.
    org_id: UUID | None = None
    org_slug: str | None = None
    org_name: str | None = None


@dataclass(frozen=True, slots=True)
class SourceFact:
    problem_id: UUID
    publisher_key: str  # the publisher (lower-cased), else the URL's host: the independence key
    official: bool
    published_date: date | None


@dataclass(frozen=True, slots=True)
class ProposalFact:
    id: UUID
    owner_id: UUID
    niche_id: UUID | None
    parent_id: UUID | None
    county_code: str | None
    published_at: datetime
    problem_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class Facts:
    now: datetime
    problems: dict[UUID, ProblemFact]
    sources: list[SourceFact]
    proposals: dict[UUID, ProposalFact]
    aggregates: list[Aggregate]  # over the whole window: the scores
    recent_aggregates: list[Aggregate] = field(default_factory=list)  # over the badge window: the actors and counts


@dataclass(slots=True)
class ProblemSignals:
    """What a problem's badge and chips may quote (counts over ``badge_days``; organisations only from 3)."""

    new_sources: int = 0
    new_official_sources: int = 0
    new_proposals: int = 0
    proposals: int = 0  # published, clear proposals linking it now (crowding, Opportunity Gap)
    orgs_scouting: int | None = None  # organisations whose scouts matched a linked proposal (>= min_orgs)
    brief: bool = False
    project_ids: list[UUID] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Board:
    facts: Facts
    problems: dict[UUID, Trend]
    projects: dict[UUID, Trend]
    signals: dict[UUID, ProblemSignals]


def _window(now: datetime, days: int) -> datetime:
    """The start of the Nairobi day ``days`` before ``now`` (a day boundary, never a caller's instant)."""
    start = nairobi_day(now) - timedelta(days=days)
    return datetime.combine(start, time.min, tzinfo=NAIROBI)


def _publisher_key(publisher: str | None, url: str) -> str:
    if publisher and publisher.strip():
        return publisher.strip().lower()
    return (urlsplit(url).hostname or url).lower()


async def _aggregates(db: AsyncSession, since: datetime, now: datetime) -> list[Aggregate]:
    params = {"since": since, "now": now, "kinds": [SCOUT_MATCH, ORG_INTEREST]}
    return [
        Aggregate(row.item_id, row.kind, row.day, float(row.events), int(row.actors), row.orgs)
        for row in (await db.execute(_AGGREGATES, params)).all()
    ]


async def load(db: AsyncSession, cfg: RankingConfig) -> Facts:
    now: datetime = (await db.execute(_NOW)).scalar_one()
    aggregates = await _aggregates(db, _window(now, cfg.trending.window_days), now)
    recent_aggregates = await _aggregates(db, _window(now, cfg.trending.badge_days), now)
    problem_rows = (await db.execute(_PROBLEMS)).all()
    source_rows = (await db.execute(_SOURCES, {"ids": [r.id for r in problem_rows]})).all()
    refs: dict[UUID, list[str | None]] = defaultdict(list)
    sources = []
    for s in source_rows:
        refs[s.problem_id].append(s.excerpt_ref)
        sources.append(
            SourceFact(s.problem_id, _publisher_key(s.publisher, s.url), s.source_type == "official", s.published_date)
        )
    problems = {
        r.id: ProblemFact(
            **r._asdict(),
            seeded_example=bool(refs[r.id]) and all((x or "").startswith(EXAMPLE_REF_PREFIX) for x in refs[r.id]),
        )
        for r in problem_rows
    }
    linked: dict[UUID, list[UUID]] = defaultdict(list)
    first: dict[UUID, tuple[UUID, UUID | None, UUID | None, str | None, datetime]] = {}
    for row in (await db.execute(_PROPOSALS)).all():
        if row.problem_id in problems:  # a held or hidden problem is not a link anyone may see
            linked[row.id].append(row.problem_id)
        first[row.id] = (row.owner_id, row.niche_id, row.parent_id, row.county_code, row.published_at)
    proposals = {pid: ProposalFact(pid, *first[pid], tuple(sorted(problem_ids))) for pid, problem_ids in linked.items()}
    return Facts(now, problems, sources, proposals, aggregates, recent_aggregates)


def _org_rows(facts: Facts, cfg: RankingConfig, kind: str, *, recent: bool = False) -> dict[UUID, list[Aggregate]]:
    source = facts.recent_aggregates if recent else facts.aggregates
    rows = [a for a in source if a.kind == kind and a.item_id in facts.proposals]
    by_item: dict[UUID, list[Aggregate]] = defaultdict(list)
    for row in organisation_side(without_bursts(rows, cfg.trending.young_share), cfg.trending.min_orgs):
        by_item[row.item_id].append(row)
    return by_item


def board(facts: Facts, cfg: RankingConfig) -> Board:
    """Every visible problem's and project's trend, and the counts a problem's badge may quote."""
    t = cfg.trending
    today = nairobi_day(facts.now)
    recent = today - timedelta(days=t.badge_days)
    oldest = today - timedelta(days=t.window_days)  # table facts older than the signals' window count for nothing
    events: dict[UUID, list[Event]] = defaultdict(list)
    actors: dict[UUID, set[object]] = defaultdict(set)
    signals = {pid: ProblemSignals(brief=p.source == "org_brief") for pid, p in facts.problems.items()}

    for p in facts.problems.values():
        if p.source == "org_brief" and p.published_at is not None and nairobi_day(p.published_at) >= oldest:
            events[p.id].append(Event("verified_org_brief", nairobi_day(p.published_at), 1))
            if nairobi_day(p.published_at) >= recent:  # the Brief's organisation acts when it posts
                actors[p.id].add(("brief", p.id))
    for s in {(s.problem_id, s.publisher_key, s.published_date): s for s in facts.sources}.values():
        if s.published_date is None or s.published_date < oldest:
            continue
        events[s.problem_id].append(
            Event("official_source" if s.official else "independent_source", s.published_date, 1)
        )
        if s.published_date >= recent:  # only fresh coverage is an actor (an old source is evidence, not a crowd)
            actors[s.problem_id].add(("publisher", s.publisher_key))
            signals[s.problem_id].new_sources += 1
            signals[s.problem_id].new_official_sources += int(s.official)

    submitted = []
    for proposal in facts.proposals.values():
        day = nairobi_day(proposal.published_at)
        for problem_id in proposal.problem_ids:
            signals[problem_id].proposals += 1
            signals[problem_id].new_proposals += int(day >= recent)
            if day >= oldest and proposal.owner_id != facts.problems[problem_id].created_by:  # no self-boost
                submitted.append((proposal.owner_id, problem_id, day))
                if day >= recent:
                    actors[problem_id].add(("owner", proposal.owner_id))
    for (problem_id, day), count in once_per_actor_and_day(submitted).items():
        events[problem_id].append(Event("proposal_submitted", day, count))

    scouts, recent_scouts = _org_rows(facts, cfg, SCOUT_MATCH), _org_rows(facts, cfg, SCOUT_MATCH, recent=True)
    solving: dict[UUID, list[UUID]] = defaultdict(list)
    for proposal in facts.proposals.values():
        for problem_id in proposal.problem_ids:
            solving[problem_id].append(proposal.id)
    for problem_id, proposal_ids in solving.items():
        per_day: dict[date, float] = {}
        orgs = 0
        for proposal_id in proposal_ids:
            for row in scouts.get(proposal_id, ()):
                per_day[row.day] = max(per_day.get(row.day, 0.0), row.events)  # once per organisation and day
            for row in recent_scouts.get(proposal_id, ()):  # organisations scouting in the badge window (from 3)
                orgs = max(orgs, row.actors)
        events[problem_id].extend(Event(SCOUT_MATCH, day, count) for day, count in per_day.items())
        if orgs:
            signals[problem_id].orgs_scouting = orgs
            actors[problem_id].update(("orgs", n) for n in range(orgs))

    problem_subjects = [
        Subject(p.id, p.niche_id, p.published_at, tuple(events[p.id]), len(actors[p.id]))
        for p in facts.problems.values()
    ]
    interest, recent_interest = _org_rows(facts, cfg, ORG_INTEREST), _org_rows(facts, cfg, ORG_INTEREST, recent=True)
    project_subjects = [
        Subject(
            prop.id,
            prop.niche_id,
            prop.published_at,
            tuple(Event(ORG_INTEREST, row.day, row.events) for row in interest.get(prop.id, ())),
            max((row.actors for row in recent_interest.get(prop.id, ())), default=0),
        )
        for prop in facts.proposals.values()
    ]
    return Board(
        facts=facts,
        problems=trends(problem_subjects, t.problems, t, facts.now),
        projects=trends(project_subjects, t.projects, t, facts.now),
        signals=signals,
    )
