"""The organisation's team settings (REQ-TEN-02; docs/platform/tasks/P28.md track C): the default reviewer per niche and
the escalation contact. An owner or admin writes them (the routes check the role first; revision 0015's policies and
guards are the backstop); each write appends an audit event on the organisation's chain with ids only.

- **Niche defaults** (``set_niche_defaults``): the whole set is replaced; a niche is named by its slug (an unknown or
  retired one is 422 ``unknown_niche``), once (422 ``duplicate_niche``); its default is an active member holding
  ``reviewer``, ``signatory`` or ``admin`` (422 ``invalid_default_reviewer``; the database also admits an owner who
  holds none of them, the API on purpose does not). A new engagement in that niche is assigned to them
  (``bridge.engagements.team.assign_niche_default``).
- **Escalation contact** (``set_escalation_contact``): an active member or nobody (422 ``invalid_member``), kept in
  ``org_escalation_contacts`` (revision 0015: members read it, never another organisation): an upsert on ``org_id``, or
  a DELETE for nobody.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.auth.models import User
from bridge.directory.models import Niche
from bridge.errors import ApiError
from bridge.ids import uuid7
from bridge.models.enums import MembershipStatus, OrgRole
from bridge.tenancy.deps import OrgContext
from bridge.tenancy.models import Membership, OrgEscalationContact, OrgNicheDefault
from bridge.tenancy.team import sqlstate, team_view
from bridge.tenancy.team_schemas import EscalationContact, NicheDefault, NicheDefaultIn

DEFAULT_REVIEWER_ROLES: Final = frozenset({OrgRole.REVIEWER, OrgRole.SIGNATORY, OrgRole.ADMIN})
# [[COPY-REVIEW]] the API's refusals (the web app shows its own words).
UNKNOWN_NICHE: Final = "Choose niches from the list."
DUPLICATE_NICHE: Final = "Each niche has one default reviewer."
INVALID_DEFAULT: Final = "Choose an active member who is a reviewer, signatory or admin."
INVALID_MEMBER: Final = "Choose an active member of this organisation."


async def _active_roles(db: AsyncSession, org_id: UUID, user_ids: Sequence[UUID]) -> dict[UUID, frozenset[OrgRole]]:
    rows = await db.execute(
        select(Membership.user_id, Membership.roles).where(
            Membership.org_id == org_id,
            Membership.user_id.in_(list(user_ids)),
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    return {user: frozenset(OrgRole(r) for r in roles) for user, roles in rows.tuples()}


async def niche_defaults(db: AsyncSession, org: OrgContext) -> list[NicheDefault]:
    return (await team_view(db, org)).niche_defaults


async def set_niche_defaults(db: AsyncSession, org: OrgContext, items: Sequence[NicheDefaultIn]) -> list[NicheDefault]:
    """Replace the organisation's niche defaults with ``items``, in the caller's transaction (the router commits)."""
    slugs = [item.niche_slug for item in items]
    if len(set(slugs)) != len(slugs):
        raise ApiError(422, "duplicate_niche", DUPLICATE_NICHE)
    found: dict[str, UUID] = dict(  # a list of pairs: a Result has keys(), so dict() would read it as a mapping
        (await db.execute(select(Niche.slug, Niche.id).where(Niche.slug.in_(slugs), Niche.active.is_(True))))
        .tuples()
        .all()
    )
    unknown = sorted(set(slugs) - set(found))
    if unknown:
        raise ApiError(422, "unknown_niche", UNKNOWN_NICHE, niche_slugs=unknown)
    roles = await _active_roles(db, org.org_id, [item.user_id for item in items])
    if any(not roles.get(item.user_id, frozenset()) & DEFAULT_REVIEWER_ROLES for item in items):
        raise ApiError(422, "invalid_default_reviewer", INVALID_DEFAULT)
    wanted = {found[item.niche_slug]: item.user_id for item in items}
    d = OrgNicheDefault
    try:
        await db.execute(delete(d).where(d.org_id == org.org_id, d.niche_id.not_in(list(wanted))))
        for niche_id, user_id in wanted.items():
            statement = pg_insert(d).values(id=uuid7(), org_id=org.org_id, niche_id=niche_id, user_id=user_id)
            await db.execute(
                statement.on_conflict_do_update(
                    index_elements=[d.org_id, d.niche_id],
                    set_={"user_id": statement.excluded.user_id},
                    where=d.user_id != statement.excluded.user_id,
                )
            )
    except DBAPIError as exc:
        if sqlstate(exc) == "23514":  # org_niche_defaults_guard: the member left or lost the roles meanwhile
            raise ApiError(422, "invalid_default_reviewer", INVALID_DEFAULT) from exc
        raise
    await audit(
        db,
        "org.niche_defaults_set",
        actor_user_id=org.live.user.id,
        org_id=org.org_id,
        subject_type="organization",
        subject_id=org.org_id,
        payload={"items": [{"niche_id": str(n), "user_id": str(u)} for n, u in sorted(wanted.items())]},
    )
    return await niche_defaults(db, org)


# --------------------------------------------------------------------------------------------- escalation contact


async def _member_name(db: AsyncSession, org_id: UUID, user_id: UUID) -> str | None:
    """The display name of an active member of the organisation, else None."""
    name: str | None = await db.scalar(
        select(User.display_name)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.org_id == org_id,
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    return name


async def set_escalation_contact(db: AsyncSession, org: OrgContext, user_id: UUID | None) -> EscalationContact | None:
    """Name the organisation's escalation contact (an active member) or nobody, in the caller's transaction."""
    name = None
    if user_id is not None:
        name = await _member_name(db, org.org_id, user_id)
        if name is None:
            raise ApiError(422, "invalid_member", INVALID_MEMBER)
    c = OrgEscalationContact
    try:
        if user_id is None:
            await db.execute(delete(c).where(c.org_id == org.org_id))
        else:
            statement = pg_insert(c).values(org_id=org.org_id, user_id=user_id)
            await db.execute(
                statement.on_conflict_do_update(index_elements=[c.org_id], set_={"user_id": statement.excluded.user_id})
            )
    except DBAPIError as exc:
        if sqlstate(exc) == "23514":  # the guard: they left meanwhile
            raise ApiError(422, "invalid_member", INVALID_MEMBER) from exc
        raise
    await audit(
        db,
        "org.escalation_contact_set",
        actor_user_id=org.live.user.id,
        org_id=org.org_id,
        subject_type="organization",
        subject_id=org.org_id,
        payload={"user_id": None if user_id is None else str(user_id)},
    )
    return None if user_id is None else EscalationContact(user_id=user_id, name=str(name))
