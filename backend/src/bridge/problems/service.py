"""Problems for the proposal editor and the problem cards (REQ-PROP-01, REQ-RES-01, REQ-RES-02; docs/spec/06 6.3,
6.5): the linked-Problem picker (published problems clear of moderation, filtered by niche, country, county and text),
one card with its cited sources, and "Describe a new problem", which the publish flow turns into a Problem with
``source=developer``, published at once, labelled "Developer-reported" and queued for moderation
(``app_open_moderation_case``) without blocking the publication. Row-Level Security already limits reads to what
the signed-in user may see; the queries repeat the published-and-clear rule so a creator's own held problem is not
offered as a link or shown on a public teaser, and a research ``candidate`` (readable by staff under RLS) is never
returned by these public reads (AC-RES-2).

Labels (``label_for``): a developer's problem is "Developer-reported"; a published research card is "AI-drafted,
human-reviewed on <date>" (docs/spec/06 6.5; the date its review published it, Africa/Nairobi); a card the demo seed
made from a fixed answer written in code (every source's ``excerpt_ref`` starts with ``example:``, which only the
seed's path writes) says it is a seeded example, never a live AI result.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any, Final
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Select, and_, exists, not_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bridge.directory.models import Niche
from bridge.directory.service import niche_label
from bridge.ids import uuid7
from bridge.models.enums import ModerationState, ProblemSource, ProblemStatus
from bridge.problems.models import Problem, ProblemCitation
from bridge.proposals.models import ProposalProblem
from bridge.proposals.schemas import NicheOut, ProblemRef

LABELS: Final = {ProblemSource.DEVELOPER: "Developer-reported"}  # [[COPY-REVIEW]] docs/spec/06 6.3 wording
# [[COPY-REVIEW]] docs/spec/06 6.5's label, and the demo seed's (never presented as a live AI result).
AI_DRAFTED: Final = "AI-drafted, human-reviewed on {date}"
SEEDED_EXAMPLE: Final = "Seeded example for the demo (not a live AI result), human-reviewed on {date}"
EXAMPLE_REF_PREFIX: Final = "example:"  # bridge.problems.research.pipeline writes it for the demo seed's cards only
NAIROBI: Final = ZoneInfo("Africa/Nairobi")
_Parent = aliased(Niche)


def niche_out(niche_id: UUID | None, slug: str | None, name: str | None, parent_name: str | None) -> NicheOut | None:
    if niche_id is None or slug is None or name is None:
        return None
    return NicheOut(id=niche_id, slug=slug, label=niche_label(name, parent_name))


def _published_and_clear() -> ColumnElement[bool]:
    return and_(Problem.status == ProblemStatus.PUBLISHED, Problem.moderation_state == ModerationState.CLEAR)


def _with_niche(stmt: Select[Any]) -> Select[Any]:
    return stmt.outerjoin(Niche, Niche.id == Problem.niche_id).outerjoin(_Parent, _Parent.id == Niche.parent_id)


def _seeded_example() -> ColumnElement[bool]:
    """Every cited source of the card is a seeded example's (and it has one)."""
    cited = select(ProblemCitation.id).where(ProblemCitation.problem_id == Problem.id)
    return and_(
        exists(cited),
        not_(
            exists(
                cited.where(
                    or_(
                        ProblemCitation.excerpt_ref.is_(None),
                        ~ProblemCitation.excerpt_ref.startswith(EXAMPLE_REF_PREFIX, autoescape=True),
                    )
                )
            )
        ),
    )


_COLUMNS = (
    Problem.id,
    Problem.title,
    Problem.source,
    Niche.id,
    Niche.slug,
    Niche.name_en,
    _Parent.name_en,
    Problem.status,
    Problem.published_at,
    _seeded_example().label("seeded_example"),
)
_REF_WIDTH: Final = len(_COLUMNS)


def label_for(
    source: ProblemSource, status: ProblemStatus, published_at: datetime | None, seeded_example: bool
) -> str | None:
    if source is ProblemSource.RESEARCH_AGENT:
        if status is not ProblemStatus.PUBLISHED or published_at is None:
            return None
        day = published_at.astimezone(NAIROBI).date()
        when = f"{day.day} {day.strftime('%B')} {day.year}"
        return (SEEDED_EXAMPLE if seeded_example else AI_DRAFTED).format(date=when)
    return LABELS.get(source)


def _ref(row: Any) -> ProblemRef:
    problem_id, title, source, niche_id, slug, name, parent_name, status, published_at, seeded = row
    return ProblemRef(
        id=problem_id,
        title=title,
        source=source,
        label=label_for(ProblemSource(source), ProblemStatus(status), published_at, bool(seeded)),
        niche=niche_out(niche_id, slug, name, parent_name),
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_published(
    db: AsyncSession,
    *,
    niche: str | None,
    q: str | None,
    limit: int,
    offset: int,
    country: str | None = None,
    county: str | None = None,
) -> list[tuple[ProblemRef, str, datetime | None]]:
    """Published, clear problems (picker), newest first: (reference, statement, published_at). ``country`` and
    ``county`` match the problem's own region exactly (AC-RES-4)."""
    stmt = _with_niche(select(*_COLUMNS, Problem.statement)).where(_published_and_clear())
    if niche is not None:
        stmt = stmt.where(or_(Niche.slug == niche, _Parent.slug == niche))
    if country is not None:
        stmt = stmt.where(Problem.country == country)
    if county is not None:
        stmt = stmt.where(Problem.county_code == county)
    if q is not None:
        pattern = f"%{_escape_like(q)}%"
        stmt = stmt.where(or_(Problem.title.ilike(pattern, escape="\\"), Problem.statement.ilike(pattern, escape="\\")))
    stmt = stmt.order_by(Problem.published_at.desc().nulls_last(), Problem.id.desc()).limit(limit).offset(offset)
    return [(_ref(row[:_REF_WIDTH]), row[_REF_WIDTH], row.published_at) for row in (await db.execute(stmt)).all()]


async def linkable(db: AsyncSession, problem_ids: Iterable[UUID]) -> set[UUID]:
    """Which of these problems may be linked: published and clear."""
    ids = list(problem_ids)
    if not ids:
        return set()
    stmt = select(Problem.id).where(Problem.id.in_(ids), _published_and_clear())
    return set((await db.execute(stmt)).scalars().all())


async def refs_for_version(db: AsyncSession, version_id: UUID, *, public: bool) -> list[ProblemRef]:
    """A version's linked problems; ``public`` keeps only published, clear ones (what every reader may see)."""
    stmt = _with_niche(select(*_COLUMNS).join(ProposalProblem, ProposalProblem.problem_id == Problem.id)).where(
        ProposalProblem.proposal_version_id == version_id
    )
    if public:
        stmt = stmt.where(_published_and_clear())
    return [_ref(row) for row in (await db.execute(stmt.order_by(Problem.title, Problem.id))).all()]


async def get_published(db: AsyncSession, problem_id: UUID) -> tuple[ProblemRef, Any, list[ProblemCitation]] | None:
    """One published, clear problem (never a candidate, AC-RES-2): its reference, its row's display columns and its
    cited sources, newest first; None when there is none the caller may see."""
    stmt = _with_niche(
        select(
            *_COLUMNS,
            Problem.statement,
            Problem.affected_group,
            Problem.country,
            Problem.county_code,
            Problem.ai_generated,
            Problem.confidence,
            Problem.named_orgs,
        )
    ).where(Problem.id == problem_id, _published_and_clear())
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        return None
    citations = (
        await db.scalars(
            select(ProblemCitation)
            .where(ProblemCitation.problem_id == problem_id)
            .order_by(ProblemCitation.published_date.desc().nulls_last(), ProblemCitation.url, ProblemCitation.id)
        )
    ).all()
    return _ref(row[:_REF_WIDTH]), row, list(citations)


_INSERT_DEVELOPER_PROBLEM = text(
    "INSERT INTO problems (id, source, niche_id, title, statement, status, created_by, moderation_state, published_at)"
    " VALUES (:id, 'developer', :niche, :title, :statement, 'published', :user, CAST(:moderation AS moderation_state),"
    " now())"
)
_OPEN_CASE = text(
    "SELECT app_open_moderation_case(:subject_type, :subject_id, CAST(:reasons AS text[]),"
    " CAST(:source AS moderation_source), CAST(:classifier AS jsonb))"
)


async def create_developer_problem(
    db: AsyncSession, *, user_id: UUID, niche_id: UUID | None, title: str, statement: str, held: bool
) -> UUID:
    """A developer's new Problem, published at once (held instead when the pre-screen holds it)."""
    problem_id = uuid7()
    moderation = ModerationState.HELD if held else ModerationState.CLEAR
    params = {"id": problem_id, "niche": niche_id, "title": title, "statement": statement, "user": user_id}
    await db.execute(_INSERT_DEVELOPER_PROBLEM, params | {"moderation": moderation.value})
    return problem_id


async def open_case(
    db: AsyncSession, subject_type: str, subject_id: UUID, reasons: Sequence[str], classifier: str | None
) -> UUID:
    """File a rules (``regex``) moderation case about a proposal or problem; the database checks the caller."""
    params = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "reasons": list(reasons),
        "source": "regex",
        "classifier": classifier,
    }
    case_id: UUID = (await db.execute(_OPEN_CASE, params)).scalar_one()
    return case_id
