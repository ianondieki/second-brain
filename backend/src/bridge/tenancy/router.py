"""Organisation API (REQ-TEN-01): /api/orgs/*. Non-members get 404, members lacking a role 403."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select

from bridge.audit.service import record as audit
from bridge.auth.deps import CurrentSession, Db, SettingsDep, ensure_step_up
from bridge.auth.models import User
from bridge.billing import entitlements
from bridge.errors import ERROR_RESPONSES, ApiError, not_found
from bridge.models.enums import MembershipStatus, OrgKind, OrgRole, OrgVerification, PlanSide
from bridge.tenancy.deps import OrgAdmin, OrgMember, OrgOwner
from bridge.tenancy.models import Membership, Organization
from bridge.tenancy.service import membership_of, my_memberships

router = APIRouter(prefix="/api/orgs", tags=["organisations"], responses=ERROR_RESPONSES)


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
    website: AnyHttpUrl | None = Field(default=None, max_length=255)

    @model_validator(mode="before")
    @classmethod
    def _no_null_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and "legal_name" in data and data["legal_name"] is None:
            raise ValueError("legal_name cannot be empty")
        return data

    @field_validator("website")
    @classmethod
    def _http_only(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None and value.scheme not in {"http", "https"}:
            raise ValueError("website must be an http(s) address")
        return value


class MemberOut(BaseModel):
    user_id: UUID
    display_name: str
    roles: list[OrgRole]


class RolesUpdate(BaseModel):
    roles: list[OrgRole] = Field(min_length=1)


class OrgEntitlementsOut(BaseModel):
    plan: str
    side: PlanSide
    limits: dict[str, Any]


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
    if "legal_name" in changed and org.verification in (OrgVerification.E1, OrgVerification.E2):
        raise ApiError(409, "verified_name_locked", "A verified organisation's name changes only through verification.")
    for name, value in changed.items():
        setattr(org, name, str(value) if name == "website" and value is not None else value)
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
async def set_member_roles(user_id: UUID, body: RolesUpdate, db: Db, settings: SettingsDep, ctx: OrgOwner) -> MemberOut:
    """Role changes are access-policy changes: owner only (404 for non-members first), then a fresh second factor."""
    ensure_step_up(ctx.live, settings)
    membership = await membership_of(db, ctx.org_id, user_id)
    if membership is None:
        raise not_found()
    roles = sorted(set(body.roles))
    if OrgRole.OWNER in membership.roles and OrgRole.OWNER not in roles:
        others = await db.execute(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.org_id == ctx.org_id,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.user_id != user_id,
                Membership.roles.overlap([OrgRole.OWNER]),
            )
        )
        if int(others.scalar_one()) == 0:
            raise ApiError(409, "last_owner", "Make someone else an owner before removing the last owner.")
    membership.roles = roles
    await audit(
        db,
        "org.member_roles_changed",
        actor_user_id=ctx.live.user.id,
        org_id=ctx.org_id,
        subject_type="membership",
        subject_id=membership.id,
        payload={"roles": [r.value for r in roles]},
    )
    await db.commit()
    member = await db.get(User, user_id)
    return MemberOut(user_id=user_id, display_name=member.display_name if member else "", roles=roles)


@router.get("/{org_id}/entitlements")
async def org_entitlements(db: Db, settings: SettingsDep, ctx: OrgMember) -> OrgEntitlementsOut:
    ent = await entitlements.for_subject(db, settings, org_id=ctx.org_id)
    return OrgEntitlementsOut(plan=ent.plan_code, side=ent.side, limits=ent.limits)
