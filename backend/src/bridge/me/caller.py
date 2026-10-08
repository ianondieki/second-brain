"""Who is asking, as the palette and the calendar need it (REQ-UX-01, REQ-UX-05; P25-B): the side ``GET
/api/auth/me`` reports and, for an organisation member, the organisations whose screens they may open.

**Side.** The ``/me`` rule: staff when the account has a staff role, else a developer when it has a developer profile,
else an organisation member when it has an active membership, else a developer (an account still signing up).

**Organisations.** The organisation routes admit an active member (``bridge.tenancy.deps.org_member``) except where a
role of theirs needs two-step sign-in and the account has none on, or this session has not given its second factor:
those organisations are left out here too, so the palette never finds what the Inbox, the Engagements list or the
Briefs would refuse. ``several`` says whether the person belongs to more than one organisation (all of them, as the
web app's ``orgQuery`` counts ``/me``'s memberships): only then do an organisation's links carry ``?org=``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth.service import has_developer_profile
from bridge.auth.sessions import LiveSession
from bridge.models.enums import MFA_REQUIRED_ORG_ROLES, OrgRole
from bridge.tenancy.service import MyMembership, my_memberships

Side = Literal["developer", "org", "staff"]


@dataclass(frozen=True, slots=True)
class Caller:
    user_id: UUID
    side: Side
    orgs: tuple[UUID, ...] = ()  # the organisations whose screens the person may open now
    several: bool = False  # a member of more than one organisation (links then name it: ?org=)


def side_of(*, staff: bool, developer: bool, member: bool) -> Side:
    """``GET /api/auth/me``'s side for a session past its second factor."""
    if staff:
        return "staff"
    if developer:
        return "developer"
    return "org" if member else "developer"


def open_orgs(memberships: Iterable[tuple[UUID, Iterable[OrgRole]]], *, second_factor: bool) -> tuple[UUID, ...]:
    """The organisations ``org_member`` admits: all, except those where a role needs two-step sign-in while
    ``second_factor`` (on for the account and given in this session) is false."""
    return tuple(org_id for org_id, roles in memberships if second_factor or not (set(roles) & MFA_REQUIRED_ORG_ROLES))


def caller_from(live: LiveSession, memberships: Sequence[MyMembership], *, developer: bool) -> Caller:
    side = side_of(staff=bool(live.user.staff_role), developer=developer, member=bool(memberships))
    if side != "org":
        return Caller(live.user.id, side)
    second_factor = live.user.totp_enabled_at is not None and live.row.mfa_verified_at is not None
    orgs = open_orgs(((m.org.id, m.roles) for m in memberships), second_factor=second_factor)
    return Caller(live.user.id, side, orgs, several=len(memberships) > 1)


async def caller_of(db: AsyncSession, live: LiveSession) -> Caller:
    """The caller, read under their own Row-Level Security (their profile and their own membership rows)."""
    memberships = await my_memberships(db, live.user.id)
    return caller_from(live, memberships, developer=await has_developer_profile(db, live.user.id))
