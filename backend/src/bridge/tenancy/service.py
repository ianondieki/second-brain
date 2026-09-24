"""Organisation and membership operations (REQ-TEN-01). Creation goes through the SECURITY DEFINER function
``app_create_organization`` (migration 0001): the app role has no INSERT policy on organizations."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.ids import uuid7
from bridge.models.enums import MembershipStatus, OrgKind, OrgRole
from bridge.tenancy.models import Membership, Organization

_CREATE = text(
    "SELECT app_create_organization(:id, CAST(:kind AS org_kind), :legal_name, CAST(:slug AS citext), :country)"
)


async def create_organization(
    db: AsyncSession, *, kind: OrgKind, legal_name: str, slug: str, country: str = "KE"
) -> UUID:
    """Create an organisation owned by the current tenant user (roles owner + admin); returns its id."""
    org_id = uuid7()
    await db.execute(
        _CREATE, {"id": org_id, "kind": kind.value, "legal_name": legal_name.strip(), "slug": slug, "country": country}
    )
    return org_id


@dataclass(frozen=True, slots=True)
class MyMembership:
    org: Organization
    roles: list[OrgRole]


async def my_memberships(db: AsyncSession, user_id: UUID) -> list[MyMembership]:
    """The caller's active memberships (RLS shows a user their own membership rows)."""
    rows = await db.execute(
        select(Organization, Membership)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Membership.user_id == user_id, Membership.status == MembershipStatus.ACTIVE)
        .order_by(Organization.legal_name)
    )
    return [MyMembership(org, [OrgRole(r) for r in membership.roles]) for org, membership in rows.all()]


async def membership_of(db: AsyncSession, org_id: UUID, user_id: UUID) -> Membership | None:
    return (
        await db.execute(
            select(Membership).where(
                Membership.org_id == org_id,
                Membership.user_id == user_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
