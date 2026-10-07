"""The statements behind the public activity feed and the Explore summary, and who runs them (REQ-UX-03,
REQ-DIR-01, REQ-REPO-02; P24-B; docs/spec/06 6.1, 6.2).

**Who reads.** Row-Level Security shows published, clear rows to any signed-in user and nothing of them to a session
with no user bound. These reads bind ``PUBLIC_READER``, the nil UUID, which is never an account (account ids are
UUIDv7, made by the server): RLS then shows exactly what every signed-in user may read and nothing more (no row is
owned by it, it is a member of no organisation, invited to no Brief and not staff), so a bug in a predicate here can
never reach a draft, a held row, an organisation's own Brief or an invited one. The transaction is READ ONLY.

**What is read.** On top of RLS each statement repeats the public predicate: a problem only while
``problem_is_readable`` (revision 0012) would say so (published, clear, no organisation or a listed one, a Brief's only
while the Brief is published and public: the problem list's rule, ``bridge.problems.service``, plus the Brief
visibility rule); a proposal only while published and clear. Only these columns: ids and times, titles that are
already public (a problem's or Brief's, a proposal's current teaser title), county and niche names from the reference
tables, and whether a problem is a seeded example card. Never a person, a handle, an organisation, a statement or any
other text, and no engagement (stage events are deferred: they need a definer function from db-migrations).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final
from uuid import UUID

from sqlalchemy import (
    Boolean,
    ColumnElement,
    Select,
    Text,
    and_,
    case,
    exists,
    func,
    literal_column,
    not_,
    or_,
    select,
    text,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from bridge.db import bind_tenant
from bridge.directory.models import Niche, Region
from bridge.directory.service import LISTED_LEVELS
from bridge.models.enums import (
    BriefStatus,
    BriefVisibility,
    ModerationState,
    ProblemSource,
    ProblemStatus,
    ProposalStatus,
    VersionStatus,
)
from bridge.problems.models import Problem, ProblemBrief, ProblemCitation
from bridge.problems.service import EXAMPLE_REF_PREFIX
from bridge.proposals.models import Proposal, ProposalVersion
from bridge.tenancy.models import Organization

FEED_SIZE: Final = 20
NEWEST: Final = 3  # problems per county and per niche on Explore
PUBLIC_READER: Final = UUID(int=0)  # the nil UUID: never an account
_READ_ONLY = text("SET TRANSACTION READ ONLY")
_Parent = aliased(Niche)
_Poster = aliased(Organization)
_Brief = aliased(ProblemBrief)
_PROBLEM_POSTED = literal_column("'problem_posted'", Text)
_BRIEF_OPENED = literal_column("'brief_opened'", Text)
_VERSION_REGISTERED = literal_column("'version_registered'", Text)
_NOT_AN_EXAMPLE = literal_column("false", Boolean)


def readable_problem() -> ColumnElement[bool]:
    """``problem_is_readable`` (revision 0012) as a correlated predicate on ``problems``."""
    listed = select(_Poster.id).where(
        _Poster.id == Problem.org_id, _Poster.verification.in_(LISTED_LEVELS), _Poster.delisted_at.is_(None)
    )
    public_brief = select(_Brief.problem_id).where(
        _Brief.problem_id == Problem.id,
        _Brief.status == BriefStatus.PUBLISHED,
        _Brief.visibility == BriefVisibility.PUBLIC,
    )
    return and_(
        Problem.status == ProblemStatus.PUBLISHED,
        Problem.moderation_state == ModerationState.CLEAR,
        or_(Problem.org_id.is_(None), exists(listed)),
        or_(Problem.source != ProblemSource.ORG_BRIEF, exists(public_brief)),
    )


def example_card() -> ColumnElement[bool]:
    """Every cited source of the problem is a saved demo excerpt (and it has one): the seed's research cards."""
    cited = select(ProblemCitation.id).where(ProblemCitation.problem_id == Problem.id)
    not_example = or_(
        ProblemCitation.excerpt_ref.is_(None),
        ~ProblemCitation.excerpt_ref.startswith(EXAMPLE_REF_PREFIX, autoescape=True),
    )
    return and_(exists(cited), not_(exists(cited.where(not_example))))


def activity_statement() -> Select[Any]:
    """The 20 newest public events: published problems and Briefs, and published proposals' registered versions."""
    problems = (
        select(
            Problem.id.label("row_id"),
            case((Problem.source == ProblemSource.ORG_BRIEF, _BRIEF_OPENED), else_=_PROBLEM_POSTED).label("kind"),
            Problem.published_at.label("at"),
            Region.name.label("county"),
            Niche.name_en.label("niche_name"),
            _Parent.name_en.label("parent_name"),
            Problem.title.label("title"),
            example_card().label("example"),
        )
        .outerjoin(Region, Region.code == Problem.county_code)
        .outerjoin(Niche, Niche.id == Problem.niche_id)
        .outerjoin(_Parent, _Parent.id == Niche.parent_id)
        .where(readable_problem(), Problem.published_at.is_not(None))
        .order_by(Problem.published_at.desc(), Problem.id.desc())
        .limit(FEED_SIZE)
    )
    versions = (
        select(
            ProposalVersion.id.label("row_id"),
            _VERSION_REGISTERED.label("kind"),
            ProposalVersion.registered_at.label("at"),
            Region.name.label("county"),
            Niche.name_en.label("niche_name"),
            _Parent.name_en.label("parent_name"),
            Proposal.title.label("title"),  # the teaser as published now, never an older version's text
            _NOT_AN_EXAMPLE.label("example"),
        )
        .join(Proposal, Proposal.id == ProposalVersion.proposal_id)
        .outerjoin(Region, Region.code == Proposal.county_code)
        .outerjoin(Niche, Niche.id == Proposal.niche_id)
        .outerjoin(_Parent, _Parent.id == Niche.parent_id)
        .where(
            ProposalVersion.status == VersionStatus.REGISTERED,
            ProposalVersion.registered_at.is_not(None),
            Proposal.status == ProposalStatus.PUBLISHED,
            Proposal.moderation_state == ModerationState.CLEAR,
        )
        .order_by(ProposalVersion.registered_at.desc(), ProposalVersion.id.desc())
        .limit(FEED_SIZE)
    )
    merged = union_all(problems, versions).subquery("feed")
    return select(merged).order_by(merged.c.at.desc(), merged.c.row_id.desc()).limit(FEED_SIZE)


def explore_statement() -> Select[Any]:
    """Every readable problem's rank and group size by county and by top-level niche, keeping each group's newest
    three (newest first), with the total and how many are not seeded example cards."""
    readable = (
        select(
            Problem.id.label("id"),
            Problem.title.label("title"),
            Problem.published_at.label("posted_at"),
            Problem.county_code.label("county_code"),
            Region.name.label("county_name"),
            Niche.name_en.label("niche_name"),
            _Parent.name_en.label("parent_name"),
            func.coalesce(_Parent.id, Niche.id).label("top_id"),
            func.coalesce(_Parent.name_en, Niche.name_en).label("top_name"),
            example_card().label("example"),
        )
        .outerjoin(Region, Region.code == Problem.county_code)
        .outerjoin(Niche, Niche.id == Problem.niche_id)
        .outerjoin(_Parent, _Parent.id == Niche.parent_id)
        .where(readable_problem())
    ).subquery("readable")
    newest = (readable.c.posted_at.desc().nulls_last(), readable.c.id.desc())
    ranked = select(
        readable,
        func.count().over(partition_by=readable.c.county_code).label("county_count"),
        func.row_number().over(partition_by=readable.c.county_code, order_by=newest).label("county_rank"),
        func.count().over(partition_by=readable.c.top_id).label("niche_count"),
        func.row_number().over(partition_by=readable.c.top_id, order_by=newest).label("niche_rank"),
        func.count().over().label("total"),
        func.count().filter(not_(readable.c.example)).over().label("unmarked"),
    ).subquery("ranked")
    return (
        select(ranked)
        .where(or_(ranked.c.county_rank <= NEWEST, ranked.c.niche_rank <= NEWEST))
        .order_by(ranked.c.posted_at.desc().nulls_last(), ranked.c.id.desc())
    )


async def read(factory: async_sessionmaker[AsyncSession], statement: Select[Any]) -> Sequence[Any]:
    """``statement``'s rows, read as the public reader in a read-only transaction of its own."""
    async with factory() as session:
        await bind_tenant(session, user_id=PUBLIC_READER)
        async with session.begin():
            await session.execute(_READ_ONLY)
            return (await session.execute(statement)).all()
