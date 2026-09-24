"""Organisation API (REQ-TEN-01): /api/orgs/*. Non-members get 404, members lacking a role 403."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from bridge.audit.service import record as audit
from bridge.auth.deps import CurrentSession, Db, StepUpSession
from bridge.auth.models import User
from bridge.errors import ApiError, not_found
from bridge.models.enums import MembershipStatus, OrgKind, OrgRole, OrgVerification
from bridge.tenancy.deps import OrgAdmin, OrgMember, OrgOwner
from bridge.tenancy.models import Membership, Organization
from bridge.tenancy.service import membership_of, my_memberships

router = APIRouter(prefix="/api/orgs", tags=["organisations"])


class OrgOut(BaseModel):
    id: UUID
    legal_name: str
    slug: str
    kind: OrgKind
    country: str
    verification: OrgVerification
    website: str | None


class MyOrgOut(BaseModel):
    org: OrgOut
    roles: list[OrgRole]


class OrgUpdate(BaseModel):
    legal_name: str | None = Field(default=None, min_length=2, max_length=200)
    website: str | None = Field(default=None, max_length=255)


class MemberOut(BaseModel):
    user_id: UUID
    display_name: str
    roles: list[OrgRole]


class RolesUpdate(BaseModel):
    roles: list[OrgRole] = Field(min_length=1)


def org_out(org: Organization) -> OrgOut:
    return OrgOut(
        id=org.id,
        legal_name=org.legal_name,
        slug=org.slug,
        kind=org.kind,
        country=org.country,
        verification=org.verification,
        website=org.website,
    )


@router.get("")
async def list_my_orgs(live: CurrentSession, db: Db) -> list[MyOrgOut]:
    return [MyOrgOut(org=org_out(m.org), roles=m.roles) for m in await my_memberships(db, live.user.id)]


@router.get("/{org_id}")
async def get_org(db: Db, ctx: OrgMember) -> OrgOut:
    org = await db.get(Organization, ctx.org_id)
    if org is None:
        raise not_found()
    return org_out(org)


@router.patch("/{org_id}")
async def update_org(body: OrgUpdate, db: Db, ctx: OrgAdmin) -> OrgOut:
    org = await db.get(Organization, ctx.org_id)
    if org is None:
        raise not_found()
    changed = body.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(org, field, value)
    await audit(
        db,
        "org.updated",
        actor_user_id=ctx.live.user.id,
        org_id=org.id,
        subject_type="organization",
        subject_id=org.id,
        payload={"fields": sorted(changed)},
    )
    await db.commit()
    return org_out(org)


@router.get("/{org_id}/members")
async def list_members(db: Db, ctx: OrgMember) -> list[MemberOut]:
    rows = await db.execute(
        select(Membership, User.display_name)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == ctx.org_id, Membership.status == MembershipStatus.ACTIVE)
        .order_by(User.display_name)
    )
    return [
        MemberOut(user_id=m.user_id, display_name=name, roles=[OrgRole(r) for r in m.roles]) for m, name in rows.all()
    ]


@router.put("/{org_id}/members/{user_id}/roles")
async def set_member_roles(user_id: UUID, body: RolesUpdate, db: Db, live: StepUpSession, ctx: OrgOwner) -> MemberOut:
    """Role changes are access-policy changes: owner only, with a fresh second factor (step-up)."""
    membership = await membership_of(db, ctx.org_id, user_id)
    if membership is None:
        raise not_found()
    roles = sorted(set(body.roles))
    if user_id == live.user.id and OrgRole.OWNER not in roles:
        raise ApiError(409, "last_owner", "Hand ownership to someone else before removing your own owner role.")
    membership.roles = roles
    await audit(
        db,
        "org.member_roles_changed",
        actor_user_id=live.user.id,
        org_id=ctx.org_id,
        subject_type="membership",
        subject_id=membership.id,
        payload={"roles": [r.value for r in roles]},
    )
    await db.commit()
    member = await db.get(User, user_id)
    return MemberOut(user_id=user_id, display_name=member.display_name if member else "", roles=roles)
