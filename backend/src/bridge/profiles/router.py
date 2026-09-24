"""The caller's own profile, consents and plan limits: /api/me/* (REQ-CON-01, REQ-BIL-01)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from bridge.audit.service import record as audit
from bridge.auth.deps import CurrentSession, Db, SettingsDep
from bridge.billing import entitlements
from bridge.errors import not_found
from bridge.models.enums import ConsentPurpose, DevVerification, PlanSide
from bridge.profiles import consents
from bridge.profiles.models import DeveloperProfile

router = APIRouter(prefix="/api/me", tags=["me"])


class ProfileOut(BaseModel):
    handle: str
    verification_level: DevVerification
    headline: str | None
    bio: str | None
    county_code: str | None


class ProfileUpdate(BaseModel):
    headline: str | None = Field(default=None, max_length=160)
    bio: str | None = Field(default=None, max_length=4000)
    county_code: str | None = Field(default=None, pattern=r"^KE-\d{2}$")


class ConsentItem(BaseModel):
    purpose: ConsentPurpose
    granted: bool
    text: str
    version: str


class EntitlementsOut(BaseModel):
    plan: str
    side: PlanSide
    limits: dict[str, Any]


def _profile_out(p: DeveloperProfile) -> ProfileOut:
    return ProfileOut(
        handle=p.handle,
        verification_level=p.verification_level,
        headline=p.headline,
        bio=p.bio,
        county_code=p.county_code,
    )


@router.get("/profile")
async def get_profile(live: CurrentSession, db: Db) -> ProfileOut:
    profile = await db.get(DeveloperProfile, live.user.id)
    if profile is None:
        raise not_found("No developer profile.")
    return _profile_out(profile)


@router.patch("/profile")
async def update_profile(body: ProfileUpdate, live: CurrentSession, db: Db) -> ProfileOut:
    profile = await db.get(DeveloperProfile, live.user.id)
    if profile is None:
        raise not_found("No developer profile.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await db.commit()
    return _profile_out(profile)


@router.get("/consents")
async def get_consents(live: CurrentSession, db: Db, settings: SettingsDep) -> list[ConsentItem]:
    state = await consents.current(db, live.user.id)
    texts = consents.load_texts(settings.consents_file)
    return [
        ConsentItem(purpose=p, granted=state[p], text=texts[p].text, version=texts[p].version) for p in ConsentPurpose
    ]


@router.put("/consents")
async def set_consents(
    body: dict[ConsentPurpose, bool], live: CurrentSession, db: Db, settings: SettingsDep
) -> list[ConsentItem]:
    await consents.record_decisions(db, settings, user_id=live.user.id, decisions=body, source="settings")
    await audit(
        db,
        "consent.changed",
        actor_user_id=live.user.id,
        subject_type="user",
        subject_id=live.user.id,
        payload={p.value: g for p, g in body.items()},
    )
    await db.commit()
    return await get_consents(live, db, settings)


@router.get("/entitlements")
async def my_entitlements(live: CurrentSession, db: Db, settings: SettingsDep) -> EntitlementsOut:
    ent = await entitlements.for_subject(db, settings, user_id=live.user.id)
    return EntitlementsOut(plan=ent.plan_code, side=ent.side, limits=ent.limits)
