"""Discover (REQ-TREND-02; docs/spec/06 6.6): Trending Problems with their sources and Why chips, Trending Projects
beside the problems they solve, and the Opportunity Gap. Computed on read from ``bridge.matching.trend_facts``.

- Trending Problems: published, clear problems that are Trending (z-score, score and actors over the floors) or New
  this week (cold start), Trending first. Each carries its newest cited sources, its Why chips and a badge that
  explains itself ("Trending in ICT › Fintech · Kenya: 2 new sources, 4 companies scouting"); organisations are
  counted only from 3 (``app_trend_aggregates``) and never named.
- Trending Projects: published, clear proposals that are Trending (verified organisations' interest) or New this week,
  each with the visible problem it solves (a proposal with none is not listed, AC-TREND-2); their badges and chips
  never count or name an organisation, and their scores are not returned (a score would count the organisations).
- Briefs (REQ-DIR-05): verified organisations' published, open Problem Briefs, newest first, read directly (not
  scored): "Posted by <organisation>" with the organisation, budget band, deadline and the proposals linking each.
- Opportunity Gap: the top decile, by trend z-score, of the problems in the filter's scope that have a z-score
  (niches with a baseline) and a positive score; of those, the ones whose z-score reaches the Trending floor (1.0)
  and that have fewer than 3 published proposals (AC-TREND-2). The decile is the scope's (a niche's top tenth when
  filtered), and the z floor keeps a quiet scope's top tenth, which is no trend, out.

Filters: a niche slug (a parent includes its children), a county code and words (a problem's title or statement holds
them, ignoring case: ``problems.service.words_match``; a project matches through the problems it solves); the
baselines are the whole platform's. Chips and badges are code-written copy ([[COPY-REVIEW]]).

Saved searches (P21 track C): ``NewMatches`` counts, for a saved view and filters, what this module's own queries list
that was published in a window: the visible problems Trending Problems draws from (``trend_facts.visible_problems``,
in the filters' scope), or the open Briefs of the Briefs view. A problem published since the last alert is New this
week, so the count is what the Discover page now shows for those filters (bar its 20-item cut).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import Row, Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bridge import pagination
from bridge.directory.models import Niche
from bridge.directory.service import listed, niche_label
from bridge.matching.config import get_weights
from bridge.matching.discover_schemas import (
    DiscoverBrief,
    DiscoverBriefsOut,
    DiscoverProblem,
    DiscoverSource,
    OpportunityGapOut,
    ProjectTrendOut,
    TrendingOut,
    TrendingProblem,
    TrendingProject,
    TrendOut,
)
from bridge.matching.ranking_config import RankingConfig
from bridge.matching.trend_facts import Board, ProblemFact, ProblemSignals, board, load, visible_problems
from bridge.matching.trending import Trend, nairobi_day
from bridge.models.enums import BriefStatus, BriefVisibility, ModerationState, ProblemSource, ProblemStatus
from bridge.problems import brief_rules, briefs
from bridge.problems.brief_schemas import BriefFacts
from bridge.problems.models import Problem, ProblemBrief
from bridge.problems.service import label_for, niche_out, org_ref, published_after, published_facts, words_match
from bridge.proposals.schemas import NicheOut, OrgRef, ProblemRef
from bridge.proposals.serializers import teaser_items
from bridge.tenancy.models import Organization

_NICHES = text("SELECT id, slug::text AS slug, name_en, parent_id FROM niches")
_CITATIONS = text(
    "SELECT problem_id, url, publisher, source_type, published_date, retrieved_at, quote FROM problem_sources"
    " WHERE problem_id = ANY(:ids) ORDER BY published_date DESC NULLS LAST, url, id"
)
BRIEF_CHIP: Final = "Verified organisation brief"  # [[COPY-REVIEW]] every chip and badge below
NEW_CHIP: Final = "New this week"
INTEREST_CHIP: Final = "Verified organisation interest"  # one organisation or several: never a count
PROJECT_BADGE_REASON: Final = "verified organisations asking"
SOLVES_TRENDING_CHIP: Final = "Solves a trending problem"
MAX_CHIPS: Final = 3


@dataclass(frozen=True, slots=True)
class NicheInfo:
    id: UUID
    slug: str
    name: str
    parent_id: UUID | None


class Niches:
    """The niche tree (a global table): labels and filter scopes."""

    def __init__(self, rows: Iterable[NicheInfo]) -> None:
        self.by_id = {n.id: n for n in rows}

    def out(self, niche_id: UUID | None) -> NicheOut | None:
        niche = self.by_id.get(niche_id) if niche_id else None
        if niche is None:
            return None
        parent = self.by_id.get(niche.parent_id) if niche.parent_id else None
        return NicheOut(id=niche.id, slug=niche.slug, label=niche_label(niche.name, parent.name if parent else None))

    def scope(self, slug: str) -> set[UUID]:
        """The niche of that slug and its children (an unknown slug: nothing)."""
        root = {n.id for n in self.by_id.values() if n.slug == slug}
        return root | {n.id for n in self.by_id.values() if n.parent_id in root}


async def niches(db: AsyncSession) -> Niches:
    rows = (await db.execute(_NICHES)).all()
    return Niches(NicheInfo(r.id, r.slug, r.name_en, r.parent_id) for r in rows)


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def problem_out(p: ProblemFact, tree: Niches) -> DiscoverProblem:
    by = org_ref(p.org_id, p.org_slug, p.org_name) if p.source == ProblemSource.ORG_BRIEF else None
    label = label_for(
        ProblemSource(p.source),
        ProblemStatus(p.status),
        p.published_at,
        p.seeded_example,
        org_name=None if by is None else by.name,
    )
    published_at, seeded_example = published_facts(ProblemStatus(p.status), p.published_at, p.seeded_example)
    return DiscoverProblem(
        id=p.id,
        title=p.title,
        source=ProblemSource(p.source),
        label=label,
        niche=tree.out(p.niche_id),
        statement=p.statement,
        country=p.country,
        county_code=p.county_code,
        published_at=published_at,
        seeded_example=seeded_example,
        org=by,
    )


def problem_ref(p: ProblemFact, tree: Niches) -> ProblemRef:
    out = problem_out(p, tree)
    return ProblemRef(
        id=out.id,
        title=out.title,
        source=out.source,
        label=out.label,
        niche=out.niche,
        seeded_example=out.seeded_example,
        published_at=out.published_at,
        org=out.org,
    )


def _facts_quoted(s: ProblemSignals) -> list[str]:
    """What a problem's badge and chips may say, most telling first (organisations only when counted, from 3)."""
    parts = []
    if s.new_official_sources:
        parts.append(plural(s.new_official_sources, "new official source", "new official sources"))
    elif s.new_sources:
        parts.append(plural(s.new_sources, "new source", "new sources"))
    if s.orgs_scouting:
        parts.append(plural(s.orgs_scouting, "company scouting", "companies scouting"))
    if s.new_proposals:
        parts.append(plural(s.new_proposals, "new proposal", "new proposals"))
    return parts


def problem_badge(p: ProblemFact, s: ProblemSignals, trend: Trend, tree: Niches) -> str | None:
    if not trend.trending:
        return None
    niche = tree.out(p.niche_id)
    place = p.county_name or p.country_name or p.country
    where = f"{niche.label} · {place}" if niche else place
    parts = _facts_quoted(s)[:2]
    return f"Trending in {where}: {', '.join(parts)}" if parts else f"Trending in {where}"


def problem_chips(s: ProblemSignals, trend: Trend) -> list[str]:
    chips = [f"{part} this month" if "new" in part else part for part in _facts_quoted(s)]
    if s.brief:
        chips.append(BRIEF_CHIP)
    if trend.new_this_week:
        chips.append(NEW_CHIP)
    return chips[:MAX_CHIPS]


def trend_out(p: ProblemFact, s: ProblemSignals, trend: Trend, tree: Niches) -> TrendOut:
    badge = problem_badge(p, s, trend, tree)
    return TrendOut(
        trending=trend.trending, new_this_week=trend.new_this_week, z=trend.z, score=trend.score, badge=badge
    )


def _order(trend: Trend) -> tuple[bool, float, float]:
    return (not trend.trending, -(trend.z or 0.0), -trend.score)


def _in_scope(niche_id: UUID | None, county: str | None, scope: set[UUID] | None, want: str | None) -> bool:
    return (scope is None or niche_id in scope) and (want is None or county == want)


async def _board(db: AsyncSession, cfg: RankingConfig) -> tuple[Board, Niches]:
    return board(await load(db, cfg), cfg), await niches(db)


async def _sources(db: AsyncSession, ids: list[UUID], per_problem: int) -> dict[UUID, list[DiscoverSource]]:
    out: dict[UUID, list[DiscoverSource]] = defaultdict(list)
    if not ids or per_problem == 0:
        return out
    for row in (await db.execute(_CITATIONS, {"ids": ids})).all():
        if len(out[row.problem_id]) < per_problem:
            out[row.problem_id].append(DiscoverSource(**{k: v for k, v in row._asdict().items() if k != "problem_id"}))
    return out


async def _problem_items(
    db: AsyncSession, b: Board, tree: Niches, cfg: RankingConfig, ids: list[UUID], projects: dict[UUID, list[UUID]]
) -> list[TrendingProblem]:
    sources = await _sources(db, ids, cfg.discover.sources_per_problem)
    items = []
    for pid in ids:
        fact, signals, trend = b.facts.problems[pid], b.signals[pid], b.problems[pid]
        items.append(
            TrendingProblem(
                problem=problem_out(fact, tree),
                trend=trend_out(fact, signals, trend, tree),
                why=problem_chips(signals, trend),
                sources=sources.get(pid, []),
                proposal_count=signals.proposals,
                project_ids=projects.get(pid, [])[: cfg.discover.projects_per_problem],
            )
        )
    return items


async def _with_words(db: AsyncSession, ids: Iterable[UUID], words: str) -> set[UUID]:
    """Which of these problems hold ``words`` in their title or statement (``words_match``)."""
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return set()
    return set((await db.scalars(select(Problem.id).where(Problem.id.in_(wanted), words_match(words)))).all())


async def trending(
    db: AsyncSession, cfg: RankingConfig, *, niche: str | None, county: str | None, words: str | None = None
) -> TrendingOut:
    b, tree = await _board(db, cfg)
    scope = None if niche is None else tree.scope(niche)
    shown = [
        pid
        for pid, fact in b.facts.problems.items()
        if (b.problems[pid].trending or b.problems[pid].new_this_week)
        and _in_scope(fact.niche_id, fact.county_code, scope, county)
    ]
    projected = [
        prop
        for prop in b.facts.proposals.values()
        if (b.projects[prop.id].trending or b.projects[prop.id].new_this_week)
        and _in_scope(prop.niche_id, prop.county_code, scope, county)
    ]
    matching: set[UUID] | None = None
    if words is not None:  # a problem by its own text; a project through the problems it solves
        matching = await _with_words(db, [*shown, *(pid for prop in projected for pid in prop.problem_ids)], words)
        shown = [pid for pid in shown if pid in matching]
    shown.sort(key=lambda pid: (*_order(b.problems[pid]), str(pid)))
    shown = shown[: cfg.discover.items]

    project_rows = []
    for prop in projected:
        linked = [pid for pid in prop.problem_ids if matching is None or pid in matching]
        if not linked:
            continue
        problem = min(linked, key=lambda pid: (*_order(b.problems[pid]), str(pid)))
        project_rows.append((prop.id, problem, b.projects[prop.id]))
    project_rows.sort(key=lambda row: (*_order(row[2]), str(row[0])))
    project_rows = project_rows[: cfg.discover.items]
    teasers = await teaser_items(db, [row[0] for row in project_rows])
    projects, beside = [], defaultdict(list)
    for proposal_id, problem_id, trend in project_rows:
        if proposal_id not in teasers:
            continue
        problem_trend = b.problems[problem_id]
        chips = [INTEREST_CHIP] if trend.actors else []
        chips += [SOLVES_TRENDING_CHIP] if problem_trend.trending else []
        chips += [NEW_CHIP] if trend.new_this_week else []
        project_niche = tree.out(b.facts.proposals[proposal_id].niche_id)
        badge = None
        if trend.trending:
            where = f"Trending in {project_niche.label}" if project_niche else "Trending"
            badge = f"{where}: {PROJECT_BADGE_REASON}"
        projects.append(
            TrendingProject(
                proposal=teasers[proposal_id],
                problem=problem_ref(b.facts.problems[problem_id], tree),
                trend=ProjectTrendOut(trending=trend.trending, new_this_week=trend.new_this_week, badge=badge),
                why=chips[:MAX_CHIPS],
            )
        )
        beside[problem_id].append(proposal_id)
    problems = await _problem_items(db, b, tree, cfg, shown, beside)
    return TrendingOut(generated_at=b.facts.now, problems=problems, projects=projects)


async def opportunity_gap(
    db: AsyncSession, cfg: RankingConfig, *, niche: str | None, county: str | None
) -> OpportunityGapOut:
    b, tree = await _board(db, cfg)
    scope = None if niche is None else tree.scope(niche)
    ranked = [
        pid
        for pid, fact in b.facts.problems.items()
        if b.problems[pid].z is not None
        and b.problems[pid].score > 0
        and _in_scope(fact.niche_id, fact.county_code, scope, county)
    ]
    ranked.sort(key=lambda pid: (-(b.problems[pid].z or 0.0), -b.problems[pid].score, str(pid)))
    top = ranked[: math.ceil(len(ranked) * cfg.discover.gap_decile)]
    gap = [
        pid
        for pid in top
        if (b.problems[pid].z or 0.0) >= cfg.trending.z_trending  # the floor: a quiet scope's "top" is not a trend
        and b.signals[pid].proposals < cfg.discover.gap_fewer_than
    ][: cfg.discover.items]
    return OpportunityGapOut(generated_at=b.facts.now, items=await _problem_items(db, b, tree, cfg, gap, {}))


_Parent = aliased(Niche)


def _briefs_query(niche: str | None, county: str | None, words: str | None, today: date) -> Select[Any]:
    """The Briefs view's rows (``briefs_view``): published and clear, public, not closed, the deadline not before
    ``today``, the organisation listed, in the filters' scope; under the reader's RLS."""
    stmt = (
        select(
            Problem.id,
            Problem.title,
            Problem.statement,
            Problem.niche_id,
            Niche.slug.label("niche_slug"),
            Niche.name_en.label("niche_name"),
            _Parent.name_en.label("parent_name"),
            Problem.country,
            Problem.county_code,
            Problem.published_at,
            Organization.id.label("org_id"),
            Organization.slug.label("org_slug"),
            Organization.legal_name.label("org_name"),
            ProblemBrief.budget_band,
            ProblemBrief.deadline,
        )
        .join(ProblemBrief, ProblemBrief.problem_id == Problem.id)
        .join(Organization, Organization.id == Problem.org_id)
        .outerjoin(Niche, Niche.id == Problem.niche_id)
        .outerjoin(_Parent, _Parent.id == Niche.parent_id)
        .where(
            Problem.source == ProblemSource.ORG_BRIEF,
            Problem.status == ProblemStatus.PUBLISHED,
            Problem.moderation_state == ModerationState.CLEAR,
            ProblemBrief.status == BriefStatus.PUBLISHED,
            ProblemBrief.visibility == BriefVisibility.PUBLIC,
            listed(),  # a delisted organisation's Briefs leave the view (its members read it under RLS too)
            or_(ProblemBrief.deadline.is_(None), ProblemBrief.deadline >= today),
        )
    )
    if niche is not None:
        stmt = stmt.where(or_(Niche.slug == niche, _Parent.slug == niche))
    if county is not None:
        stmt = stmt.where(Problem.county_code == county)
    if words is not None:
        stmt = stmt.where(words_match(words))
    return stmt


async def briefs_view(
    db: AsyncSession,
    *,
    niche: str | None,
    county: str | None,
    limit: int,
    after: pagination.MomentCursor | None,
    words: str | None = None,
) -> DiscoverBriefsOut:
    """Verified organisations' Problem Briefs (REQ-DIR-05): published and clear, public, not closed and whose deadline
    has not passed (Africa/Nairobi, platform clock), newest first, under the reader's RLS; each with its organisation,
    budget band, deadline and the published proposals linking it."""
    stmt = _briefs_query(niche, county, words, await briefs.today(db))
    if after is not None:
        stmt = stmt.where(published_after(after))
    order = (Problem.published_at.desc().nulls_last(), Problem.id.desc())
    rows = (await db.execute(stmt.order_by(*order).limit(limit + 1))).all()
    page, weights = rows[:limit], get_weights()
    counts = await briefs.proposal_counts(db, [row.id for row in page])
    items = []
    for row in page:
        org = OrgRef(id=row.org_id, slug=row.org_slug, name=row.org_name)
        label = label_for(ProblemSource.ORG_BRIEF, ProblemStatus.PUBLISHED, row.published_at, False, org_name=org.name)
        problem = DiscoverProblem(
            id=row.id,
            title=row.title,
            source=ProblemSource.ORG_BRIEF,
            label=label,
            niche=niche_out(row.niche_id, row.niche_slug, row.niche_name, row.parent_name),
            seeded_example=False,
            published_at=row.published_at,
            org=org,
            statement=row.statement,
            country=row.country,
            county_code=row.county_code,
        )
        band = brief_rules.band_out(row.budget_band, weights)
        brief = BriefFacts(org=org, budget_band=band, deadline=row.deadline, open=True)  # the view lists open ones only
        items.append(DiscoverBrief(problem=problem, brief=brief, proposal_count=counts.get(row.id, 0)))
    last = page[-1] if len(rows) > limit else None
    return DiscoverBriefsOut(
        items=items, next_cursor=None if last is None else pagination.encode(last.published_at, last.id)
    )


@dataclass(frozen=True, slots=True)
class SavedQuery:
    """A saved Discover view and filters (P21 track C): ``problems`` or ``briefs``, a niche slug, a county code and
    words, each optional."""

    view: str
    niche: str | None = None
    county: str | None = None
    words: str | None = None


class NewMatches:
    """How many items Discover lists for a saved query that were published after ``since`` and at or before ``now``,
    read under the session's RLS (bind it to the person first). The visible problems and the niche tree are read once
    per instance (one person's searches)."""

    def __init__(self, db: AsyncSession, now: datetime) -> None:
        self._db, self._now = db, now
        self._problems: tuple[Sequence[Row[Any]], Niches] | None = None

    async def _visible(self) -> tuple[Sequence[Row[Any]], Niches]:
        if self._problems is None:
            self._problems = (await visible_problems(self._db, self._now), await niches(self._db))
        return self._problems

    async def count(self, query: SavedQuery, since: datetime) -> int:
        if query.view == "briefs":
            stmt = _briefs_query(query.niche, query.county, query.words, nairobi_day(self._now)).where(
                Problem.published_at > since, Problem.published_at <= self._now
            )
            return int(await self._db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows, tree = await self._visible()
        scope = None if query.niche is None else tree.scope(query.niche)
        ids = [
            row.id
            for row in rows
            if row.published_at is not None
            and since < row.published_at <= self._now
            and _in_scope(row.niche_id, row.county_code, scope, query.county)
        ]
        if query.words is not None:
            return len(await _with_words(self._db, ids, query.words))
        return len(ids)
