"""The command palette's search (REQ-UX-01; D-67; P25-B): ``GET /api/me/search?q=``.

**What is searched, by side** (``bridge.me.caller``): a developer's ideas (their own proposals, drafts included: My
ideas), engagements (theirs as the developer), problems (published ones anyone signed in may read) and companies
(listed organisations: only developers have the Companies screen, ``/dev/companies``, which sends everyone else to
their home); an organisation member's Inbox (proposals pitched to their organisations), engagements (their
organisations'), Briefs (their organisations' own, every state, as the Problems screen lists them) and problems (not
their own organisations' Briefs, which are under Briefs); staff's problems.

**How.** Case-insensitive substring of the title (an organisation's name for companies; for a developer's engagements
the counterpart organisation's name too), the LIKE wildcards ``%`` and ``_`` and the escape ``\\`` taken literally.
Each group runs the predicate of the list it mirrors, under the caller's Row-Level Security (the request's session,
bound to the caller), and never a broader one: My ideas' owner rule; the engagement lists' party rule; the Inbox's
delivered tags of a published, clear proposal; the Briefs list's organisation rule; ``problem_is_readable``
(``bridge.public.queries.readable_problem``: published, clear, a listed organisation's, a Brief's only while it is
published and public), so staff, who read more under RLS, find what every developer finds; the directory's
``listed`` rule. At most ``GROUP_SIZE`` items each, a title starting with the words first, then the newest (companies:
then by name); groups that find nothing are left out.

**What an item carries**: its id, title, one line under it (a niche label; for an engagement the organisation and
the stage, or the stage; for a company its type and county) and the web app path it opens, an organisation's with
``?org=`` for a member of several (``orgQuery`` in the web app). Nothing else of the record.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence
from typing import Any, Final
from uuid import UUID

from sqlalchemy import ColumnElement, Select, SQLColumnExpression, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bridge.directory.models import Niche, Region
from bridge.directory.service import ORG_TYPE_LABELS, listed, niche_label
from bridge.engagements import state_machine as sm
from bridge.engagements.models import Engagement
from bridge.errors import ApiError
from bridge.me.caller import Caller, Side
from bridge.me.schemas import SearchGroup, SearchItem, SearchKind, SearchResults
from bridge.models.enums import EngagementState, ModerationState, OrgKind, ProposalStatus, TagStatus
from bridge.problems.models import Problem, ProblemBrief
from bridge.proposals.models import Proposal, ProposalVersion, Tag
from bridge.public.queries import readable_problem
from bridge.tenancy.models import Organization

GROUP_SIZE: Final = 5
MIN_LENGTH: Final = 2
MAX_LENGTH: Final = 80
# [[COPY-REVIEW]]
QUERY_RULE: Final = f"Type {MIN_LENGTH} to {MAX_LENGTH} characters to search."
GROUPS: Final[dict[Side, tuple[SearchKind, ...]]] = {
    "developer": ("ideas", "engagements", "problems", "companies"),
    "org": ("inbox", "engagements", "briefs", "problems"),
    "staff": ("problems",),
}
PROPOSAL_FALLBACK: Final = "Proposal"  # an engagement whose proposal title the caller cannot read (the lists' word)
ORG_FALLBACK: Final = "Organisation"
_Parent = aliased(Niche)
_Current = aliased(ProposalVersion)
_Draft = aliased(ProposalVersion)


def normalise(q: str) -> str:
    """The words to search for: ``q`` trimmed, ``MIN_LENGTH`` to ``MAX_LENGTH`` characters with no control character
    (the database holds no NUL), else 422 ``invalid_query`` (never quoting it)."""
    term = q.strip()
    if not MIN_LENGTH <= len(term) <= MAX_LENGTH or any(unicodedata.category(ch)[0] == "C" for ch in term):
        raise ApiError(422, "invalid_query", QUERY_RULE)
    return term


def escape_like(term: str) -> str:
    """``term`` with LIKE's escape, ``%`` and ``_`` escaped (escape character ``\\``), so each matches itself."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Words:
    """A search term as LIKE patterns: anywhere in a column, and at its start (the better match)."""

    def __init__(self, term: str) -> None:
        escaped = escape_like(term)
        self.anywhere, self.start = f"%{escaped}%", f"{escaped}%"

    def match(self, column: SQLColumnExpression[Any]) -> ColumnElement[bool]:
        return column.ilike(self.anywhere, escape="\\")

    def first(self, column: SQLColumnExpression[Any]) -> ColumnElement[bool]:
        """True when ``column`` starts with the words: ordered DESC, those come first."""
        return column.ilike(self.start, escape="\\")


# --- the web app's paths ----------------------------------------------------------------------------------------------


def org_query(caller: Caller, org_id: UUID) -> str:
    """``?org=<id>`` for a member of several organisations, else nothing (the web app's ``orgQuery``)."""
    return f"?org={org_id}" if caller.several else ""


def idea_href(proposal_id: UUID) -> str:
    return f"/dev/ideas/{proposal_id}"


def engagement_href(caller: Caller, engagement_id: UUID, org_id: UUID) -> str:
    if caller.side == "org":
        return f"/org/engagements/{engagement_id}{org_query(caller, org_id)}"
    return f"/dev/engagements/{engagement_id}"


def inbox_href(caller: Caller, proposal_id: UUID, org_id: UUID) -> str:
    return f"/org/inbox/{proposal_id}{org_query(caller, org_id)}"


def brief_href(caller: Caller, problem_id: UUID, org_id: UUID) -> str:
    return f"/org/problems/{problem_id}{org_query(caller, org_id)}"


def problem_href(problem_id: UUID) -> str:
    return f"/problems/{problem_id}"


def company_href(org_id: UUID) -> str:
    return f"/dev/companies/{org_id}"


# --- lines under a title ----------------------------------------------------------------------------------------------


def _niche(name: str | None, parent_name: str | None) -> str | None:
    return None if name is None else niche_label(name, parent_name)


def stage_line(state: EngagementState | str) -> str:
    state = EngagementState(state)
    return sm.STAGE_LABELS.get(state, state.value)


def engagement_line(caller: Caller, org_name: str | None, state: EngagementState | str) -> str:
    """The organisation and the stage for the developer (the list's "with <organisation>"); the stage for members."""
    if caller.side == "org":
        return stage_line(state)
    return f"{org_name or ORG_FALLBACK} · {stage_line(state)}"


def company_line(kind: OrgKind | str, county: str | None) -> str:
    label = ORG_TYPE_LABELS.get(OrgKind(kind), str(kind))
    return label if county is None else f"{label} · {county}"


# --- the statements, one per group ----------------------------------------------------------------------------------


def ideas_statement(caller: Caller, words: Words) -> Select[Any]:
    """My ideas' rows (``bridge.proposals.service._MY_LIST``): the caller's proposals, the draft's title first."""
    title = func.coalesce(_Draft.title, _Current.title)
    changed = func.greatest(Proposal.updated_at, _Draft.updated_at)
    return (
        select(Proposal.id, title.label("title"), Niche.name_en.label("niche"), _Parent.name_en.label("parent"))
        .outerjoin(_Current, _Current.id == Proposal.current_version_id)
        .outerjoin(_Draft, _Draft.id == Proposal.draft_version_id)
        .outerjoin(Niche, Niche.id == func.coalesce(_Draft.niche_id, _Current.niche_id))
        .outerjoin(_Parent, _Parent.id == Niche.parent_id)
        .where(Proposal.owner_id == caller.user_id, words.match(title))
        .order_by(words.first(title).desc(), changed.desc(), Proposal.id.desc())
        .limit(GROUP_SIZE)
    )


def engagements_statement(caller: Caller, words: Words) -> Select[Any]:
    """The engagement lists' rows: the developer's own (``GET /api/me/engagements``), or the member's organisations'
    (``GET /api/orgs/{org_id}/engagements``), each with its version's title and the organisation's name as RLS shows
    them."""
    party = Engagement.org_id.in_(caller.orgs) if caller.side == "org" else Engagement.developer_id == caller.user_id
    found = words.match(ProposalVersion.title)
    if caller.side != "org":
        found = or_(found, words.match(Organization.legal_name))
    return (
        select(
            Engagement.id,
            Engagement.org_id,
            Engagement.state,
            ProposalVersion.title.label("title"),
            Organization.legal_name.label("org_name"),
        )
        .outerjoin(ProposalVersion, ProposalVersion.id == Engagement.version_id)
        .outerjoin(Organization, Organization.id == Engagement.org_id)
        .where(party, found)
        .order_by(words.first(ProposalVersion.title).desc(), Engagement.updated_at.desc(), Engagement.id.desc())
        .limit(GROUP_SIZE)
    )


def inbox_statement(caller: Caller, words: Words) -> Select[Any]:
    """The Inbox's rows (``bridge.proposals.inbox``): delivered tags of the member's organisations whose proposal is
    published and clear, with the current teaser's title and niche; newest pitch first."""
    return (
        select(
            Tag.id,
            Tag.proposal_id,
            Tag.org_id,
            ProposalVersion.title.label("title"),
            Niche.name_en.label("niche"),
            _Parent.name_en.label("parent"),
        )
        .join(Proposal, Proposal.id == Tag.proposal_id)
        .join(ProposalVersion, ProposalVersion.id == Proposal.current_version_id)
        .outerjoin(Niche, Niche.id == ProposalVersion.niche_id)
        .outerjoin(_Parent, _Parent.id == Niche.parent_id)
        .where(
            Tag.org_id.in_(caller.orgs),
            Tag.status == TagStatus.DELIVERED,
            Proposal.status == ProposalStatus.PUBLISHED,
            Proposal.moderation_state == ModerationState.CLEAR,
            words.match(ProposalVersion.title),
        )
        .order_by(words.first(ProposalVersion.title).desc(), Tag.created_at.desc(), Tag.id.desc())
        .limit(GROUP_SIZE)
    )


def briefs_statement(caller: Caller, words: Words) -> Select[Any]:
    """The Problems screen's rows (``bridge.problems.briefs.list_briefs``): the member's organisations' Briefs in every
    state, newest first."""
    return (
        select(
            Problem.id,
            ProblemBrief.org_id,
            Problem.title,
            Niche.name_en.label("niche"),
            _Parent.name_en.label("parent"),
        )
        .join(ProblemBrief, ProblemBrief.problem_id == Problem.id)
        .outerjoin(Niche, Niche.id == Problem.niche_id)
        .outerjoin(_Parent, _Parent.id == Niche.parent_id)
        .where(ProblemBrief.org_id.in_(caller.orgs), words.match(Problem.title))
        .order_by(words.first(Problem.title).desc(), Problem.created_at.desc(), Problem.id.desc())
        .limit(GROUP_SIZE)
    )


def problems_statement(caller: Caller, words: Words) -> Select[Any]:
    """Problems every signed-in developer may read (``readable_problem``), newest published first; for a member, not
    their own organisations' Briefs (those are under Briefs)."""
    readable = readable_problem()
    if caller.side == "org" and caller.orgs:
        readable = and_(readable, or_(Problem.org_id.is_(None), Problem.org_id.not_in(caller.orgs)))
    return (
        select(Problem.id, Problem.title, Niche.name_en.label("niche"), _Parent.name_en.label("parent"))
        .outerjoin(Niche, Niche.id == Problem.niche_id)
        .outerjoin(_Parent, _Parent.id == Niche.parent_id)
        .where(readable, words.match(Problem.title))
        .order_by(words.first(Problem.title).desc(), Problem.published_at.desc().nulls_last(), Problem.id.desc())
        .limit(GROUP_SIZE)
    )


def companies_statement(caller: Caller, words: Words) -> Select[Any]:
    """The directory's organisations (``listed``: E0, E1 or E2 and not delisted), by name."""
    return (
        select(Organization.id, Organization.legal_name, Organization.kind, Region.name.label("county"))
        .outerjoin(Region, Region.code == Organization.county_code)
        .where(listed(), words.match(Organization.legal_name))
        .order_by(words.first(Organization.legal_name).desc(), Organization.legal_name, Organization.id)
        .limit(GROUP_SIZE)
    )


# --- rows into items ------------------------------------------------------------------------------------------------


def idea_item(caller: Caller, row: Any) -> SearchItem:
    return SearchItem(id=str(row.id), title=row.title, subtitle=_niche(row.niche, row.parent), href=idea_href(row.id))


def engagement_item(caller: Caller, row: Any) -> SearchItem:
    return SearchItem(
        id=str(row.id),
        title=row.title or PROPOSAL_FALLBACK,
        subtitle=engagement_line(caller, row.org_name, row.state),
        href=engagement_href(caller, row.id, row.org_id),
    )


def inbox_item(caller: Caller, row: Any) -> SearchItem:
    return SearchItem(
        id=str(row.id),
        title=row.title,
        subtitle=_niche(row.niche, row.parent),
        href=inbox_href(caller, row.proposal_id, row.org_id),
    )


def brief_item(caller: Caller, row: Any) -> SearchItem:
    return SearchItem(
        id=str(row.id),
        title=row.title,
        subtitle=_niche(row.niche, row.parent),
        href=brief_href(caller, row.id, row.org_id),
    )


def problem_item(caller: Caller, row: Any) -> SearchItem:
    return SearchItem(
        id=str(row.id), title=row.title, subtitle=_niche(row.niche, row.parent), href=problem_href(row.id)
    )


def company_item(caller: Caller, row: Any) -> SearchItem:
    return SearchItem(
        id=str(row.id),
        title=row.legal_name,
        subtitle=company_line(row.kind, row.county),
        href=company_href(row.id),
    )


Statement = Callable[[Caller, Words], Select[Any]]
Item = Callable[[Caller, Any], SearchItem]
READS: Final[dict[SearchKind, tuple[Statement, Item]]] = {
    "ideas": (ideas_statement, idea_item),
    "engagements": (engagements_statement, engagement_item),
    "inbox": (inbox_statement, inbox_item),
    "briefs": (briefs_statement, brief_item),
    "problems": (problems_statement, problem_item),
    "companies": (companies_statement, company_item),
}


def kinds_for(caller: Caller) -> tuple[SearchKind, ...]:
    """The caller's side's groups; an organisation's own groups only when some organisation is open to them."""
    kinds = GROUPS[caller.side]
    if caller.side == "org" and not caller.orgs:
        return tuple(kind for kind in kinds if kind == "problems")
    return kinds


def results(q: str, found: Sequence[tuple[SearchKind, list[SearchItem]]]) -> SearchResults:
    """The response: the groups in order, each cut to ``GROUP_SIZE``, the empty ones left out."""
    return SearchResults(
        q=q, groups=[SearchGroup(kind=kind, items=items[:GROUP_SIZE]) for kind, items in found if items]
    )


async def run(db: AsyncSession, caller: Caller, term: str) -> SearchResults:
    """Search every group of the caller's side, one statement each, in the caller's transaction."""
    words, found = Words(term), []
    for kind in kinds_for(caller):
        statement, item = READS[kind]
        rows = (await db.execute(statement(caller, words))).all()
        found.append((kind, [item(caller, row) for row in rows]))
    return results(term, found)
