"""Admin console API (REQ-ADM-01): /api/admin/*, staff only (``bridge.admin.deps``; 404 for everyone else).

- ``GET /me``: the caller's staff role (the console shell checks access with it).
- ``GET /niches``: the whole niche taxonomy, inactive niches included, for directory editing (staff admin).
- ``POST /niches``: add a niche without a deploy (staff admin; docs/spec/06 6.2, AC-DIR-5/a). The database decides
  through ``app_add_niche`` (SECURITY DEFINER: staff admin only, new lower-case hyphenated slug, a parent must be an
  active top-level niche); the new niche is selectable in the directory at once. Audited as
  ``directory.niche_added`` with ids only.
- ``GET /moderation/cases``: the moderation queue, unresolved cases first-in first-out (``?decided=true`` for the
  decided ones, newest decision first), each with its proposal's or problem's Tier-1 text, the flagged fields and the
  decisions open to the caller (staff admin or moderator; REQ-MOD-01, ``bridge.admin.moderation``).
- ``POST /moderation/cases/{case_id}/decision``: approve or reject the version reviewed (``subject_version_id``;
  409 ``case_changed`` when the author published another since) through ``bridge.admin.moderation``; audited as
  ``moderation.case_decided``.

Other queues are sub-routers of their own: ``bridge.admin.research`` (``/research/*``, P11) and ``bridge.admin.claims``
(``/claims``, read only, P15).
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bridge.admin import moderation
from bridge.admin.deps import StaffAdmin, StaffMember, StaffModerator
from bridge.audit.service import record as audit
from bridge.auth.deps import Db
from bridge.directory.models import Niche
from bridge.directory.service import niche_label
from bridge.errors import ERROR_RESPONSES, ApiError, not_found
from bridge.models.enums import AuditActor, StaffRole

router = APIRouter(prefix="/api/admin", tags=["admin"], responses=ERROR_RESPONSES)


class StaffMeOut(BaseModel):
    role: StaffRole


# The same rules as app_add_niche (revision 0002), so a malformed body is a 422 before the database is asked.
NicheSlug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)]
NicheName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
IsicCode = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{1,8}$")]


class NicheCreate(BaseModel):
    """A new niche: top level, or a child of an active top-level niche (the taxonomy has two levels)."""

    model_config = ConfigDict(extra="forbid")

    slug: NicheSlug
    name: NicheName
    parent_slug: NicheSlug | None = None
    isic_code: IsicCode | None = None


class AdminNicheOut(BaseModel):
    id: UUID
    slug: str
    name: str
    label: str
    parent_slug: str | None
    isic_code: str | None
    active: bool
    sort_order: int


@router.get("/me")
async def staff_me(staff: StaffMember) -> StaffMeOut:
    return StaffMeOut(role=staff.role)


async def _admin_niches(db: AsyncSession, niche_id: UUID | None = None) -> list[AdminNicheOut]:
    parent = aliased(Niche)
    stmt = select(Niche, parent.slug, parent.name_en).outerjoin(parent, parent.id == Niche.parent_id)
    if niche_id is not None:
        stmt = stmt.where(Niche.id == niche_id)
    out = [
        AdminNicheOut(
            id=niche.id,
            slug=niche.slug,
            name=niche.name_en,
            label=niche_label(niche.name_en, parent_name),
            parent_slug=parent_slug,
            isic_code=niche.isic_code,
            active=niche.active,
            sort_order=niche.sort_order,
        )
        for niche, parent_slug, parent_name in (await db.execute(stmt)).all()
    ]
    return sorted(out, key=lambda n: n.label.casefold())


@router.get("/niches")
async def admin_list_niches(staff: StaffAdmin, db: Db) -> list[AdminNicheOut]:
    return await _admin_niches(db)


_ADD_NICHE: Final = text("SELECT app_add_niche(:slug, :name, :parent_slug, :isic_code)")
# app_add_niche's refusals (SQLSTATE) as API errors; the staff dependency has already admitted the caller.
_NICHE_REFUSALS: Final = {
    "23505": (409, "niche_slug_taken", "A niche with this slug already exists."),
    "23514": (422, "parent_niche_not_top_level", "The parent must be an active top-level niche (two levels only)."),
    "23503": (422, "parent_niche_not_found", "There is no niche with this parent slug."),
    "22023": (422, "invalid_niche", "Check the slug, name and ISIC code."),
}


def niche_refusal(exc: DBAPIError) -> ApiError | None:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "42501":  # the database's staff check (app_is_staff) refused: answer as the dependency does
        return not_found()
    refusal = _NICHE_REFUSALS.get(str(sqlstate))
    return None if refusal is None else ApiError(*refusal)


@router.post("/niches", status_code=201)
async def admin_add_niche(body: NicheCreate, staff: StaffAdmin, db: Db) -> AdminNicheOut:
    try:
        niche_id: UUID = (await db.execute(_ADD_NICHE, body.model_dump())).scalar_one()
    except DBAPIError as exc:
        refusal = niche_refusal(exc)
        if refusal is None:
            raise
        await db.rollback()
        raise refusal from None
    [niche] = await _admin_niches(db, niche_id)
    parent_id = await db.scalar(select(Niche.parent_id).where(Niche.id == niche_id))
    await audit(
        db,
        "directory.niche_added",
        actor_user_id=staff.live.user.id,
        actor_kind=AuditActor.STAFF,
        subject_type="niche",
        subject_id=niche_id,
        payload={"parent_id": None if parent_id is None else str(parent_id)},
    )
    await db.commit()
    return niche


@router.get("/moderation/cases")
async def moderation_queue(
    staff: StaffModerator, db: Db, decided: Annotated[bool, Query(description="Decided cases instead")] = False
) -> moderation.CaseList:
    return await moderation.list_cases(db, unresolved=not decided, staff_id=staff.live.user.id)


@router.post("/moderation/cases/{case_id}/decision")
async def decide_case(
    case_id: UUID, body: moderation.DecisionIn, staff: StaffModerator, db: Db
) -> moderation.DecisionOut:
    return await moderation.decide(
        db,
        staff_id=staff.live.user.id,
        case_id=case_id,
        decision=body.decision,
        subject_version_id=body.subject_version_id,
    )
