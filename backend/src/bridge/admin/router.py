"""Admin console API (REQ-ADM-01): /api/admin/*, staff only (``bridge.admin.deps``; 404 for everyone else).

- ``GET /me``: the caller's staff role (the console shell checks access with it).
- ``GET /niches``: the whole niche taxonomy, inactive niches included, for directory editing (staff admin).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import aliased

from bridge.admin.deps import StaffAdmin, StaffMember
from bridge.auth.deps import Db
from bridge.directory.models import Niche
from bridge.directory.service import niche_label
from bridge.errors import ERROR_RESPONSES
from bridge.models.enums import StaffRole

router = APIRouter(prefix="/api/admin", tags=["admin"], responses=ERROR_RESPONSES)


class StaffMeOut(BaseModel):
    role: StaffRole


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


@router.get("/niches")
async def admin_list_niches(staff: StaffAdmin, db: Db) -> list[AdminNicheOut]:
    parent = aliased(Niche)
    rows = (
        await db.execute(select(Niche, parent.slug, parent.name_en).outerjoin(parent, parent.id == Niche.parent_id))
    ).all()
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
        for niche, parent_slug, parent_name in rows
    ]
    return sorted(out, key=lambda n: n.label.casefold())
