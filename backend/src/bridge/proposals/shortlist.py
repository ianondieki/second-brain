"""The organisation shortlist and side-by-side compare (REQ-REPO-02, R10; P21 track B; D-57 (5) and (6); revision 0008).

One row per (organisation, proposal) in ``org_shortlist``, shared by the organisation's members: every member reads it
(the Inbox's Shortlist view, each entry saying who added it and when), members with a Tier-2 role (reviewer,
signatory, admin: ``TIER2_ROLES``, docs/spec/06 6.1) add and remove. A proposal is added only while it is in the
organisation's Inbox: ``app_org_sees_proposal`` (pitched to it, matched by its scout, or answering its Brief), asked
first so that anything else is a 404 like an unknown id; the shortlist's INSERT policy asks again, so a proposal held
in between is refused by the database too (mapped to the same 404). Adding is idempotent (``ON CONFLICT DO NOTHING``:
the first add keeps its author and time); removing is too. Each actual add and remove writes an audit event
(``shortlist.added``, ``shortlist.removed``: ids only), so the log keeps what the working list forgets.

Compare reads 2 to 4 distinct shortlisted proposals side by side on Tier-1 facts only (D-57 (5)): the current
registered version's title, niche, country and county, maturity and ask, the certificate's id and registration time,
this organisation's engagement with the proposal (its id and state) if there is one, and the best fit score its scouts
gave the proposal if they matched it. Never a Tier-2 column, even where the organisation holds a Tier-2 grant: the
full proposal stays one click away, with its watermark and view log.

Every read asks again whether the organisation can still see each proposal (published, clear and in its Inbox,
``app_org_sees_proposal``, under the caller's RLS): a proposal held by moderation, unpublished or whose tag was
withdrawn after it was shortlisted keeps its row, so a Tier-2 member can remove it, but the list shows it as
``available`` false with no Tier-1 facts, and compare leaves it out (its ``items`` may then be fewer than asked).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final, cast
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import CursorResult, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import pagination
from bridge.audit.service import record as audit
from bridge.errors import ApiError, not_found
from bridge.models.enums import EngagementState, OrgRole, ProposalAsk, ProposalMaturity
from bridge.problems.service import niche_out
from bridge.proposals.schemas import NicheOut

TIER2_ROLES: Final = frozenset({OrgRole.ADMIN, OrgRole.REVIEWER, OrgRole.SIGNATORY})  # revision 0008's _TIER2_MEMBER
COMPARE_MIN: Final = 2
COMPARE_MAX: Final = 4
ADDED: Final = "shortlist.added"
REMOVED: Final = "shortlist.removed"
INSUFFICIENT_PRIVILEGE: Final = "42501"  # the INSERT policy's refusal (a proposal that left the Inbox meanwhile)

# The proposal's current registered version, re-read on every request and only while the organisation can still see
# the proposal: published, clear and in its Inbox (``app_org_sees_proposal``; a held proposal, or one whose tag was
# withdrawn, keeps its row but loses its facts). Tier 1 only.
_TIER1_JOINS = (
    " LEFT JOIN proposals p ON p.id = s.proposal_id AND p.status = 'published' AND p.moderation_state = 'clear'"
    " AND app_org_sees_proposal(s.org_id, s.proposal_id)"
    " LEFT JOIN proposal_versions v ON v.id = p.current_version_id"
    " LEFT JOIN niches n ON n.id = v.niche_id LEFT JOIN niches pn ON pn.id = n.parent_id"
)
_ENTRIES = (  # constant SQL fragments; every value is bound
    "SELECT s.proposal_id, s.added_at, s.added_by, u.display_name AS added_by_name,"  # noqa: S608
    " (v.id IS NOT NULL) AS available, v.title, n.id AS niche_id, n.slug AS niche_slug, n.name_en AS niche_name,"
    " pn.name_en AS parent_name FROM org_shortlist s JOIN users u ON u.id = s.added_by"
    + _TIER1_JOINS
    + " WHERE s.org_id = :org"
)
_LIST = text(
    _ENTRIES + " AND (CAST(:c_at AS timestamptz) IS NULL"
    " OR (s.added_at, s.proposal_id) < (CAST(:c_at AS timestamptz), CAST(:c_id AS uuid)))"
    " ORDER BY s.added_at DESC, s.proposal_id DESC LIMIT :limit"
)
_ONE = text(_ENTRIES + " AND s.proposal_id = :proposal")
_COMPARE = text(  # constant SQL fragments; every value is bound
    "SELECT s.proposal_id, (v.id IS NOT NULL) AS available, v.title, v.country, v.county_code,"  # noqa: S608
    " v.maturity, v.ask, v.cert_id, v.registered_at, n.id AS niche_id, n.slug AS niche_slug, n.name_en AS niche_name,"
    " pn.name_en AS parent_name, e.id AS engagement_id, e.state AS engagement_state,"
    " (SELECT max(m.score) FROM agent_matches m WHERE m.org_id = s.org_id AND m.proposal_id = s.proposal_id)"
    " AS fit_score FROM org_shortlist s"
    + _TIER1_JOINS
    + " LEFT JOIN engagements e ON e.proposal_id = s.proposal_id AND e.org_id = s.org_id"
    " WHERE s.org_id = :org AND s.proposal_id = ANY(:ids)"
)
_SEES = text("SELECT app_org_sees_proposal(:org, :proposal)")
_ADD = text(
    "INSERT INTO org_shortlist (org_id, proposal_id, added_by) VALUES (:org, :proposal, :user)"
    " ON CONFLICT (org_id, proposal_id) DO NOTHING"
)
_REMOVE = text("DELETE FROM org_shortlist WHERE org_id = :org AND proposal_id = :proposal")
_STARRED = text("SELECT proposal_id FROM org_shortlist WHERE org_id = :org AND proposal_id = ANY(:ids)")


class ShortlistEntry(BaseModel):
    proposal_id: UUID
    available: bool = Field(
        description="False once the organisation can no longer see it (held, unpublished, out of its Inbox): no"
        " Tier-1 facts then; a Tier-2 member may still remove it"
    )
    title: str | None
    niche: NicheOut | None
    added_by_id: UUID
    added_by_name: str = Field(description="The member who added it")
    added_at: datetime


class ShortlistPage(BaseModel):
    items: list[ShortlistEntry]
    next_cursor: str | None = Field(description="Pass as ?cursor= for the next page; null on the last page")


class CompareEngagement(BaseModel):
    id: UUID
    state: EngagementState


class CompareItem(BaseModel):
    """One proposal's Tier-1 facts, for the side-by-side view (never a Tier-2 field)."""

    proposal_id: UUID
    title: str | None
    niche: NicheOut | None
    country: str | None
    county_code: str | None
    maturity: ProposalMaturity | None
    ask: ProposalAsk | None = Field(description="What the developer is looking for")
    cert_id: str | None = Field(description="The registration certificate's id")
    registered_at: datetime | None = Field(description="When the certificate's version was registered")
    engagement: CompareEngagement | None = Field(description="This organisation's engagement with it, if any")
    fit_score: int | None = Field(description="The best fit (0-100) this organisation's scouts gave it; null: no match")


class CompareOut(BaseModel):
    items: list[CompareItem] = Field(
        description="In the order asked; a proposal the organisation can no longer see (held, unpublished, out of its"
        " Inbox) is left out"
    )


def _entry(row: Any) -> ShortlistEntry:
    return ShortlistEntry(
        proposal_id=row.proposal_id,
        available=row.available,
        title=row.title,
        niche=niche_out(row.niche_id, row.niche_slug, row.niche_name, row.parent_name),
        added_by_id=row.added_by,
        added_by_name=row.added_by_name,
        added_at=row.added_at,
    )


async def entries(db: AsyncSession, org_id: UUID, *, limit: int, cursor: str | None) -> ShortlistPage:
    """The organisation's shortlist, newest first, ``limit`` a page (``bridge.pagination``)."""
    after = pagination.decode(cursor)
    if after is not None and after.at is None:  # every entry has its moment: this list never wrote such a cursor
        raise pagination.invalid_cursor()
    params = {
        "org": org_id,
        "c_at": after.at if after else None,
        "c_id": after.id if after else None,
        "limit": limit + 1,
    }
    rows = (await db.execute(_LIST, params)).all()
    last = rows[limit - 1] if len(rows) > limit else None
    return ShortlistPage(
        items=[_entry(row) for row in rows[:limit]],
        next_cursor=None if last is None else pagination.encode(last.added_at, last.proposal_id),
    )


async def _entry_of(db: AsyncSession, org_id: UUID, proposal_id: UUID) -> ShortlistEntry | None:
    row = (await db.execute(_ONE, {"org": org_id, "proposal": proposal_id})).one_or_none()
    return None if row is None else _entry(row)


def _rowcount(result: Any) -> int:
    return int(cast(CursorResult[Any], result).rowcount)


async def add(db: AsyncSession, org_id: UUID, user_id: UUID, proposal_id: UUID) -> ShortlistEntry:
    """Shortlist a proposal of the organisation's Inbox (404 for anything else); a repeat changes nothing. Commits."""
    if not (await db.execute(_SEES, {"org": org_id, "proposal": proposal_id})).scalar_one():
        raise not_found("No proposal in your organisation's Inbox has this id.")
    try:
        added = _rowcount(await db.execute(_ADD, {"org": org_id, "proposal": proposal_id, "user": user_id}))
    except DBAPIError as exc:  # the INSERT policy: the proposal left the Inbox since the check
        await db.rollback()
        if getattr(exc.orig, "sqlstate", None) != INSUFFICIENT_PRIVILEGE:
            raise
        raise not_found("No proposal in your organisation's Inbox has this id.") from exc
    if added:
        await audit(db, ADDED, actor_user_id=user_id, org_id=org_id, subject_type="proposal", subject_id=proposal_id)
    await db.commit()
    entry = await _entry_of(db, org_id, proposal_id)
    if entry is None:  # removed by another member between the commit and this read
        raise not_found("No proposal in your organisation's Inbox has this id.")
    return entry


async def remove(db: AsyncSession, org_id: UUID, user_id: UUID, proposal_id: UUID) -> None:
    """Take a proposal off the shortlist (nothing happens when it is not on it). Commits."""
    removed = _rowcount(await db.execute(_REMOVE, {"org": org_id, "proposal": proposal_id}))
    if removed:
        await audit(db, REMOVED, actor_user_id=user_id, org_id=org_id, subject_type="proposal", subject_id=proposal_id)
    await db.commit()


def compare_ids(raw: str) -> list[UUID]:
    """The proposals to compare from ``?ids=a,b[,c,d]``: 2 to 4 distinct ids, in the order given; 422 otherwise."""
    parts = [part.strip() for part in raw.split(",")]
    try:
        ids = [UUID(part) for part in parts]
    except ValueError as exc:
        raise ApiError(422, "invalid_ids", "Name the proposals to compare by their ids, separated by commas.") from exc
    if len(set(ids)) != len(ids):
        raise ApiError(422, "compare_repeated", "Name each proposal to compare once.")
    if not COMPARE_MIN <= len(ids) <= COMPARE_MAX:
        raise ApiError(422, "compare_count", f"Compare {COMPARE_MIN} to {COMPARE_MAX} shortlisted proposals.")
    return ids


def _compare_item(row: Any) -> CompareItem:
    engagement = None
    if row.engagement_id is not None:
        engagement = CompareEngagement(id=row.engagement_id, state=row.engagement_state)
    return CompareItem(
        proposal_id=row.proposal_id,
        title=row.title,
        niche=niche_out(row.niche_id, row.niche_slug, row.niche_name, row.parent_name),
        country=row.country,
        county_code=row.county_code,
        maturity=row.maturity,
        ask=row.ask,
        cert_id=row.cert_id,
        registered_at=row.registered_at,
        engagement=engagement,
        fit_score=row.fit_score,
    )


async def compare(db: AsyncSession, org_id: UUID, ids: Sequence[UUID]) -> CompareOut:
    """Tier-1 facts of shortlisted proposals, in the order of ``ids``, leaving out any the organisation can no longer
    see; 422 when one is not on the shortlist."""
    rows = {row.proposal_id: row for row in (await db.execute(_COMPARE, {"org": org_id, "ids": list(ids)})).all()}
    if any(proposal_id not in rows for proposal_id in ids):
        raise ApiError(422, "not_shortlisted", "Compare only proposals on your organisation's shortlist.")
    return CompareOut(items=[_compare_item(rows[pid]) for pid in ids if rows[pid].available])


async def starred(db: AsyncSession, org_id: UUID, proposal_ids: Sequence[UUID]) -> set[UUID]:
    """Which of these proposals are on the organisation's shortlist (the Inbox's star)."""
    ids = list(dict.fromkeys(proposal_ids))
    if not ids:
        return set()
    return set((await db.execute(_STARRED, {"org": org_id, "ids": ids})).scalars().all())
