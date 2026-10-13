"""The organisation's Team (REQ-TEN-02; docs/platform/tasks/P28.md track C; revision 0015's team half).

Reads (``team_view``, any active member): the active members by name with their roles and the day they joined (the
membership's creation), each one's address only for an owner or admin reading; the open invitations (owners and
admins only, else null: the table's own policy shows them no others); the default reviewer per niche (active niches
only: a retired niche can be neither chosen nor shown, and the next PUT of the set drops its row); the escalation
contact.

Writes (an owner or admin; the routes check the role first, the policies of revisions 0001 and 0015 are the backstop):

- **Remove a member** (``remove_member``): the membership is set ``removed`` (members never leave by DELETE). Only an
  owner removes an owner or a signatory (403 ``protected_member``, as revision 0001's policy); the organisation's last
  active owner is never removed (409 ``last_owner``: checked first under a row lock on the organisation, as the role
  change does, with ``memberships_last_owner_guard``'s SQLSTATE 55000 as the backstop). In the same transaction the
  member's open assignments the caller can see are closed (P27's ``engagement_assignments``: the database stamps
  ``unassigned_at``), each audited as an unassignment; ``memberships_clear_team_seats`` (revision 0015) then closes
  any the caller cannot see (an engagement of the caller's own as its developer, D-68) and clears the member's niche
  defaults and escalation-contact seat. Audited on the organisation's chain with ids only.

The niche defaults and the escalation contact are written by ``bridge.tenancy.team_settings``.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.auth.models import User
from bridge.directory.models import Niche
from bridge.engagements.models import EngagementAssignment
from bridge.errors import ApiError, forbidden, not_found
from bridge.models.enums import MembershipStatus, OrgRole
from bridge.tenancy.deps import OrgContext
from bridge.tenancy.models import Invitation, Membership, Organization, OrgEscalationContact, OrgNicheDefault
from bridge.tenancy.team_schemas import EscalationContact, NicheDefault, OrgInvitation, OrgTeam, OrgTeamMember

MANAGERS: Final = frozenset({OrgRole.OWNER, OrgRole.ADMIN})
PROTECTED: Final = frozenset({OrgRole.OWNER, OrgRole.SIGNATORY})  # only an owner grants or removes these
FORMER_MEMBER: Final = "Former member"  # [[COPY-REVIEW]] an inviter who has left (their name is not the roster's)
# [[COPY-REVIEW]] the API's refusals (the web app shows its own words).
PROTECTED_MEMBER: Final = "Only an owner can remove an owner or a signatory."
LAST_OWNER: Final = "Make someone else an owner before removing the last owner."


def manages(org: OrgContext) -> bool:
    """Whether the caller is an owner or admin of the organisation."""
    return bool(org.roles & MANAGERS)


def sqlstate(exc: DBAPIError) -> str | None:
    state: str | None = getattr(exc.orig, "sqlstate", None)
    return state


# ------------------------------------------------------------------------------------------------------------ reads


async def team_view(db: AsyncSession, org: OrgContext) -> OrgTeam:
    """The Team page as the caller reads it (four statements, three for a member who is not an owner or admin)."""
    admin = manages(org)
    rows = await db.execute(
        select(Membership.user_id, Membership.roles, Membership.created_at, User.display_name, User.email)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org.org_id, Membership.status == MembershipStatus.ACTIVE)
        .order_by(User.display_name, Membership.user_id)
    )
    members = [
        OrgTeamMember(
            user_id=user_id,
            name=name,
            email=str(email) if admin else None,
            roles=sorted(OrgRole(r) for r in roles),
            joined_at=joined,
        )
        for user_id, roles, joined, name, email in rows.tuples()
    ]
    invitations = await open_invitations(db, org.org_id) if admin else None
    d = OrgNicheDefault
    defaults = await db.execute(
        select(Niche.slug, Niche.name_en, d.user_id, User.display_name)
        .join(Niche, Niche.id == d.niche_id)
        .join(User, User.id == d.user_id)
        .where(d.org_id == org.org_id, Niche.active.is_(True))  # a retired niche's default is not shown (nor set)
        .order_by(Niche.name_en, Niche.slug)
    )
    escalation = (
        await db.execute(
            select(OrgEscalationContact.user_id, User.display_name)
            .outerjoin(User, User.id == OrgEscalationContact.user_id)
            .where(OrgEscalationContact.org_id == org.org_id)
        )
    ).one_or_none()
    contact = None
    if escalation is not None:  # the organisation's members' read only (revision 0015's own table)
        contact = EscalationContact(user_id=escalation[0], name=escalation[1] or FORMER_MEMBER)
    return OrgTeam(
        members=members,
        invitations=invitations,
        niche_defaults=[
            NicheDefault(niche_slug=slug, niche_name=name, user_id=user_id, name=person)
            for slug, name, user_id, person in defaults.tuples()
        ],
        escalation_contact=contact,
    )


async def open_invitations(db: AsyncSession, org_id: UUID, *, only: UUID | None = None) -> list[OrgInvitation]:
    """The organisation's open invitations, newest first (an owner's or admin's read: the table's policy); ``only``
    narrows to one."""
    i = Invitation
    query = (
        select(
            i.id,
            i.email,
            i.roles,
            i.created_at,
            i.expires_at,
            (i.expires_at <= func.app_clock_now()).label("expired"),
            User.display_name,
        )
        .outerjoin(User, User.id == i.invited_by)
        .where(i.org_id == org_id, i.accepted_at.is_(None), i.revoked_at.is_(None))
        .order_by(i.created_at.desc(), i.id.desc())
    )
    if only is not None:
        query = query.where(i.id == only)
    rows = await db.execute(query)
    return [
        OrgInvitation(
            id=row.id,
            email=str(row.email),
            roles=sorted(OrgRole(r) for r in row.roles),
            created_at=row.created_at,
            expires_at=row.expires_at,
            expired=bool(row.expired),
            invited_by_name=row.display_name or FORMER_MEMBER,
        )
        for row in rows
    ]


# ----------------------------------------------------------------------------------------------- remove a member


async def remove_member(db: AsyncSession, org: OrgContext, user_id: UUID) -> list[UUID]:
    """Remove ``user_id`` from the organisation (see the module docstring), in the caller's transaction (the router
    commits). Returns the engagements whose assignment to them was closed."""
    target = (
        await db.execute(
            select(Membership).where(
                Membership.org_id == org.org_id,
                Membership.user_id == user_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise not_found()
    held = frozenset(OrgRole(r) for r in target.roles)
    if held & PROTECTED and OrgRole.OWNER not in org.roles:
        raise forbidden("protected_member", PROTECTED_MEMBER)
    # Serialise removals and role changes in this organisation, so two owners cannot remove each other at once.
    await db.execute(select(Organization.id).where(Organization.id == org.org_id).with_for_update())
    if OrgRole.OWNER in held and not await _another_owner(db, org.org_id, user_id):
        raise ApiError(409, "last_owner", LAST_OWNER)
    a = EngagementAssignment
    closed = await db.execute(  # the database stamps unassigned_at with the shared clock, whatever is sent
        update(a)
        .where(a.org_id == org.org_id, a.assignee_user_id == user_id, a.unassigned_at.is_(None))
        .values(unassigned_at=func.now())
        .returning(a.engagement_id)
    )
    cleared = sorted(closed.scalars().all())
    try:
        removed = await db.execute(
            update(Membership)
            .where(Membership.id == target.id, Membership.status == MembershipStatus.ACTIVE)
            .values(status=MembershipStatus.REMOVED, updated_at=func.now())
            .returning(Membership.id)
        )
    except DBAPIError as exc:
        if sqlstate(exc) == "55000":  # memberships_last_owner_guard: a concurrent removal won
            raise ApiError(409, "last_owner", LAST_OWNER) from exc
        raise
    if removed.first() is None:  # the policy refused it (a protected member) or it changed meanwhile
        raise forbidden("protected_member", PROTECTED_MEMBER)
    actor = org.live.user.id
    for engagement_id in cleared:
        await audit(
            db,
            "engagement.assigned",
            actor_user_id=actor,
            org_id=org.org_id,
            subject_type="engagement",
            subject_id=engagement_id,
            payload={
                "engagement_id": str(engagement_id),
                "assignment_id": None,
                "assignee_user_id": None,
                "reason": "member_removed",
            },
        )
    await audit(
        db,
        "org.member_removed",
        actor_user_id=actor,
        org_id=org.org_id,
        subject_type="membership",
        subject_id=target.id,
        payload={"user_id": str(user_id), "assignments_cleared": len(cleared)},
    )
    return cleared


async def _another_owner(db: AsyncSession, org_id: UUID, user_id: UUID) -> bool:
    others = await db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.org_id == org_id,
            Membership.status == MembershipStatus.ACTIVE,
            Membership.user_id != user_id,
            Membership.roles.overlap([OrgRole.OWNER]),
        )
    )
    return int(others or 0) > 0
