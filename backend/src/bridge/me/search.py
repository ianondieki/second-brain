"""The command palette's search (REQ-UX-01; D-67; P25-B): ``GET /api/me/search?q=``.

**What is searched, by side** (``bridge.me.caller``): a developer's ideas (their own proposals, drafts included: My
ideas), engagements (theirs as the developer), problems (published ones anyone signed in may read) and companies
(listed organisations); an organisation member's Inbox (proposals pitched to their organisations), engagements
(their organisations'), Briefs (their organisations' own, every state, as the Problems screen lists them), problems
(not their own organisations' Briefs, which are under Briefs) and companies; staff's problems and companies.

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
from collections.abc import Sequence
from typing import Any, Final
from uuid import UUID

from sqlalchemy import ColumnElement, SQLColumnExpression
from sqlalchemy.orm import aliased

from bridge.directory.models import Niche
from bridge.directory.service import ORG_TYPE_LABELS, niche_label
from bridge.engagements import state_machine as sm
from bridge.errors import ApiError
from bridge.me.caller import Caller, Side
from bridge.me.schemas import SearchGroup, SearchItem, SearchKind, SearchResults
from bridge.models.enums import EngagementState, OrgKind
from bridge.proposals.models import ProposalVersion

GROUP_SIZE: Final = 5
MIN_LENGTH: Final = 2
MAX_LENGTH: Final = 80
# [[COPY-REVIEW]]
QUERY_RULE: Final = f"Type {MIN_LENGTH} to {MAX_LENGTH} characters to search."
GROUPS: Final[dict[Side, tuple[SearchKind, ...]]] = {
    "developer": ("ideas", "engagements", "problems", "companies"),
    "org": ("inbox", "engagements", "briefs", "problems", "companies"),
    "staff": ("problems", "companies"),
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


def kinds_for(caller: Caller) -> tuple[SearchKind, ...]:
    """The caller's side's groups; an organisation's own groups only when some organisation is open to them."""
    kinds = GROUPS[caller.side]
    if caller.side == "org" and not caller.orgs:
        return tuple(kind for kind in kinds if kind in ("problems", "companies"))
    return kinds


def results(q: str, found: Sequence[tuple[SearchKind, list[SearchItem]]]) -> SearchResults:
    """The response: the groups in order, each cut to ``GROUP_SIZE``, the empty ones left out."""
    return SearchResults(
        q=q, groups=[SearchGroup(kind=kind, items=items[:GROUP_SIZE]) for kind, items in found if items]
    )
