"""Directory reads (REQ-DIR-01, REQ-DIR-02; docs/spec/06 6.2, docs/spec/03 Directory).

Listed organisations only: E0 (``unclaimed``), E1 or E2 and not delisted. Row-Level Security already limits a
signed-in user to those (the ``bridge_app_select_listed`` policy of revision 0002) plus their own organisations; the
queries repeat the rule, so a member of a pending or delisted organisation never sees it in the directory either.

Browsing groups organisations under two-level niche headings (``Parent › Child``). The page is a keyset over (niche
heading, organisation) pairs, so an organisation with two niches appears under both headings; organisations without a
niche come last under a null heading. Filters: org type, county (ISO 3166-2:KE), niche (a parent niche includes its
children) and a name search.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, and_, case, func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bridge.directory.models import Niche, OrgNiche, Region
from bridge.directory.responsiveness import ResponsivenessSource, responsiveness_for
from bridge.directory.schemas import (
    Badge,
    BadgeLevel,
    CountyRef,
    DirectoryGroup,
    DirectoryPage,
    FilterOptions,
    NicheChild,
    NicheNode,
    NicheRef,
    OrgCard,
    OrgTypeOption,
)
from bridge.models.enums import OrgKind, OrgVerification, RegionKind
from bridge.tenancy.models import Organization

# Approved badge copy (docs/spec/06 6.2), shown verbatim; AC-DIR-3 compares it exactly.
BADGE_TEXT: Final[Mapping[OrgVerification, str]] = {
    OrgVerification.UNCLAIMED: "Listed from public information · not on the platform · not affiliated",
    OrgVerification.E1: "Domain verified (pending legal verification)",
    # [[COPY-REVIEW]] docs/spec/06 gives no E2 badge copy: a short neutral line until the copy review.
    OrgVerification.E2: "Legal entity verified",
}
_BADGE_LEVEL: Final[Mapping[OrgVerification, BadgeLevel]] = {
    OrgVerification.UNCLAIMED: "e0",
    OrgVerification.E1: "e1",
    OrgVerification.E2: "e2",
}
LISTED_LEVELS: Final = tuple(BADGE_TEXT)
# Org types as named in docs/spec/03 (Axis 1).
ORG_TYPE_LABELS: Final[Mapping[OrgKind, str]] = {
    OrgKind.COMPANY: "Company",
    OrgKind.SME: "SME",
    OrgKind.SACCO_MFI: "SACCO/MFI",
    OrgKind.UNIVERSITY_TVET: "University/TVET",
    OrgKind.SCHOOL: "School",
    OrgKind.NATIONAL_GOVT: "National Govt",
    OrgKind.COUNTY_GOVT: "County Govt",
    OrgKind.NGO_PBO: "NGO/PBO",
    OrgKind.DEVELOPMENT_PARTNER: "Development Partner",
}
NICHE_SEPARATOR: Final = " › "  # U+203A, as in docs/spec/03 and AC-DIR-6
_NO_NICHE: Final = UUID(int=0)  # keyset stand-in for the null heading


def badge_for(verification: OrgVerification) -> Badge:
    if verification not in BADGE_TEXT:
        raise ValueError(f"verification {verification.value!r} is not listed in the directory")
    return Badge(level=_BADGE_LEVEL[verification], text=BADGE_TEXT[verification])


def niche_label(name: str, parent_name: str | None) -> str:
    return name if parent_name is None else f"{parent_name}{NICHE_SEPARATOR}{name}"


def listed() -> ColumnElement[bool]:
    return and_(Organization.verification.in_(LISTED_LEVELS), Organization.delisted_at.is_(None))


# --- cursor ---


@dataclass(frozen=True, slots=True)
class Cursor:
    """The last (heading, organisation) pair of a page."""

    rank: int  # 0 under a niche, 1 under the null heading
    label: str
    niche_id: UUID
    name: str
    org_id: UUID


def encode_cursor(cursor: Cursor) -> str:
    raw = json.dumps(
        [cursor.rank, cursor.label, str(cursor.niche_id), cursor.name, str(cursor.org_id)], ensure_ascii=False
    )
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> Cursor:
    """Raise ValueError for anything that is not a cursor this module wrote."""
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        rank, label, niche_id, name, org_id = json.loads(raw.decode("utf-8"))
        if rank not in (0, 1) or not isinstance(label, str) or not isinstance(name, str):
            raise ValueError("malformed cursor")
        return Cursor(rank, label, UUID(niche_id), name, UUID(org_id))
    except (binascii.Error, UnicodeDecodeError, TypeError, ValueError) as exc:  # JSONDecodeError is a ValueError
        raise ValueError("invalid cursor") from exc


# --- browse ---


@dataclass(frozen=True, slots=True)
class DirectoryFilters:
    kinds: Sequence[OrgKind] = ()
    counties: Sequence[str] = ()
    niches: Sequence[str] = ()  # slugs; a parent slug includes its children
    q: str | None = None


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_directory(
    db: AsyncSession,
    filters: DirectoryFilters,
    *,
    cursor: Cursor | None,
    limit: int,
    responsiveness: ResponsivenessSource,
    now: datetime,
) -> DirectoryPage:
    parent = aliased(Niche)
    rank = case((Niche.id.is_(None), 1), else_=0)
    label = func.coalesce(
        case((parent.id.is_(None), Niche.name_en), else_=parent.name_en + NICHE_SEPARATOR + Niche.name_en), ""
    )
    niche_key = func.coalesce(Niche.id, literal(_NO_NICHE))
    stmt = (
        select(Organization.id, rank, label, niche_key, Organization.legal_name, Niche.slug)
        .select_from(Organization)
        .outerjoin(OrgNiche, OrgNiche.org_id == Organization.id)
        .outerjoin(Niche, Niche.id == OrgNiche.niche_id)
        .outerjoin(parent, parent.id == Niche.parent_id)
        .where(listed())
    )
    if filters.kinds:
        stmt = stmt.where(Organization.kind.in_(filters.kinds))
    if filters.counties:
        stmt = stmt.where(Organization.county_code.in_(filters.counties))
    if filters.niches:
        stmt = stmt.where(or_(Niche.slug.in_(filters.niches), parent.slug.in_(filters.niches)))
    if filters.q:
        stmt = stmt.where(Organization.legal_name.ilike(f"%{_escape_like(filters.q)}%", escape="\\"))
    if cursor is not None:
        stmt = stmt.where(
            tuple_(rank, label, niche_key, Organization.legal_name, Organization.id)
            > tuple_(
                literal(cursor.rank),
                literal(cursor.label),
                literal(cursor.niche_id),
                literal(cursor.name),
                literal(cursor.org_id),
            )
        )
    stmt = stmt.order_by(rank, label, niche_key, Organization.legal_name, Organization.id).limit(limit + 1)
    pairs = (await db.execute(stmt)).all()
    more = len(pairs) > limit
    pairs = pairs[:limit]
    cards = await _cards(db, [p[0] for p in pairs], responsiveness=responsiveness, now=now)
    groups: list[DirectoryGroup] = []
    for org_id, pair_rank, pair_label, niche_id, _name, slug in pairs:
        if org_id not in cards:
            continue  # delisted between the two reads
        heading = None if pair_rank == 1 else NicheRef(id=niche_id, slug=slug, label=pair_label)
        if not groups or groups[-1].niche != heading:
            groups.append(DirectoryGroup(niche=heading, orgs=[]))
        groups[-1].orgs.append(cards[org_id])
    next_cursor = None
    if more:
        last = pairs[-1]
        next_cursor = encode_cursor(Cursor(last[1], last[2], last[3], last[4], last[0]))
    return DirectoryPage(groups=groups, next_cursor=next_cursor)


async def get_card(
    db: AsyncSession, org_id: UUID, *, responsiveness: ResponsivenessSource, now: datetime
) -> OrgCard | None:
    cards = await _cards(db, [org_id], responsiveness=responsiveness, now=now)
    return cards.get(org_id)


async def _cards(
    db: AsyncSession, org_ids: Sequence[UUID], *, responsiveness: ResponsivenessSource, now: datetime
) -> dict[UUID, OrgCard]:
    ids = list(dict.fromkeys(org_ids))
    if not ids:
        return {}
    orgs = (await db.execute(select(Organization).where(Organization.id.in_(ids), listed()))).scalars().all()
    parent = aliased(Niche)
    niche_rows = (
        await db.execute(
            select(OrgNiche.org_id, Niche.id, Niche.slug, Niche.name_en, parent.name_en)
            .join(Niche, Niche.id == OrgNiche.niche_id)
            .outerjoin(parent, parent.id == Niche.parent_id)
            .where(OrgNiche.org_id.in_(ids))
        )
    ).all()
    niches: dict[UUID, list[NicheRef]] = {}
    for org_id, niche_id, slug, name, parent_name in niche_rows:
        niches.setdefault(org_id, []).append(NicheRef(id=niche_id, slug=slug, label=niche_label(name, parent_name)))
    codes = {o.county_code for o in orgs if o.county_code}
    county_names: dict[str, str] = {}
    if codes:
        county_names = dict(
            (await db.execute(select(Region.code, Region.name).where(Region.code.in_(codes)))).tuples().all()
        )
    stats = await responsiveness.stats_for([o.id for o in orgs if o.verification == OrgVerification.E2])
    cards: dict[UUID, OrgCard] = {}
    for org in orgs:
        county = None
        if org.county_code:
            county = CountyRef(code=org.county_code, name=county_names.get(org.county_code, org.county_code))
        cards[org.id] = OrgCard(
            id=org.id,
            slug=org.slug,
            name=org.legal_name,
            kind=org.kind,
            niches=sorted(niches.get(org.id, []), key=lambda n: n.label.casefold()),
            county=county,
            badge=badge_for(org.verification),
            responsiveness=responsiveness_for(
                verification=org.verification, e2_verified_at=org.e2_verified_at, stats=stats.get(org.id), now=now
            ),
        )
    return cards


# --- niches and filter options ---


async def niche_tree(db: AsyncSession) -> list[NicheNode]:
    """Active niches, two levels, alphabetical; read at request time (an admin-added niche shows at once)."""
    rows = (await db.execute(select(Niche).where(Niche.active.is_(True)))).scalars().all()
    top = sorted((n for n in rows if n.parent_id is None), key=lambda n: n.name_en.casefold())
    children: dict[UUID, list[Niche]] = {}
    for niche in rows:
        if niche.parent_id is not None:
            children.setdefault(niche.parent_id, []).append(niche)
    return [
        NicheNode(
            id=node.id,
            slug=node.slug,
            name=node.name_en,
            label=node.name_en,
            isic_code=node.isic_code,
            children=[
                NicheChild(
                    id=child.id,
                    slug=child.slug,
                    name=child.name_en,
                    label=niche_label(child.name_en, node.name_en),
                    isic_code=child.isic_code,
                )
                for child in sorted(children.get(node.id, []), key=lambda n: n.name_en.casefold())
            ],
        )
        for node in top
    ]


async def filter_options(db: AsyncSession) -> FilterOptions:
    counties = (
        await db.execute(select(Region.code, Region.name).where(Region.kind == RegionKind.COUNTY).order_by(Region.name))
    ).all()
    return FilterOptions(
        org_types=[OrgTypeOption(value=kind, label=label) for kind, label in ORG_TYPE_LABELS.items()],
        counties=[CountyRef(code=code, name=name) for code, name in counties],
    )
