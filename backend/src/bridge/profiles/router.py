"""Own profile, consents and plan limits (/api/me); consent texts (/api/consents). REQ-CON-01, REQ-BIL-01."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from bridge.audit.service import record as audit
from bridge.auth.deps import CurrentSession, Db, SettingsDep
from bridge.billing import entitlements
from bridge.directory.models import Region
from bridge.errors import ERROR_RESPONSES, ApiError, not_found
from bridge.models.enums import ConsentPurpose, DevVerification, PlanSide, RegionKind
from bridge.profiles import consents
from bridge.profiles.models import DeveloperProfile

router = APIRouter(prefix="/api/me", tags=["me"], responses=ERROR_RESPONSES)
public_router = APIRouter(prefix="/api/consents", tags=["consents"], responses=ERROR_RESPONSES)


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


class ConsentText(BaseModel):
    purpose: ConsentPurpose
    text: str


class ConsentTexts(BaseModel):
    version: str
    purposes: list[ConsentText]


class ConsentDecision(BaseModel):
    granted: bool
    version: str  # the consents.yaml version whose text the person saw


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


@public_router.get("")
async def consent_texts(settings: SettingsDep) -> ConsentTexts:
    """The current consent wording and its version (shown on signup and settings; public)."""
    texts = consents.load_texts(settings.consents_file)
    return ConsentTexts(
        version=consents.consents_version(settings),
        purposes=[ConsentText(purpose=p, text=texts[p].text) for p in ConsentPurpose],
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
    changes = body.model_dump(exclude_unset=True)
    county = changes.get("county_code")
    if county is not None:
        found = await db.execute(select(Region.code).where(Region.code == county, Region.kind == RegionKind.COUNTY))
        if found.scalar_one_or_none() is None:
            raise ApiError(422, "unknown_county", "Choose one of Kenya's 47 counties.")
    for name, value in changes.items():
        setattr(profile, name, value)
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
    body: dict[ConsentPurpose, ConsentDecision], live: CurrentSession, db: Db, settings: SettingsDep
) -> list[ConsentItem]:
    """Record decisions; each names the text version it was made on (409 if the wording changed since)."""
    if body:
        current = consents.consents_version(settings)
        if any(d.version != current for d in body.values()):
            raise ApiError(409, "consent_text_changed", "The consent wording has changed. Reload and choose again.")
        decisions = {p: d.granted for p, d in body.items()}
        await consents.record_decisions(db, settings, user_id=live.user.id, decisions=decisions, source="settings")
        await audit(
            db,
            "consent.changed",
            actor_user_id=live.user.id,
            subject_type="user",
            subject_id=live.user.id,
            payload={p.value: g for p, g in decisions.items()},
        )
        await db.commit()
    return await get_consents(live, db, settings)


@router.get("/entitlements")
async def my_entitlements(live: CurrentSession, db: Db, settings: SettingsDep) -> EntitlementsOut:
    """A developer's plan limits. Organisation limits are at /api/orgs/{org_id}/entitlements."""
    if await db.get(DeveloperProfile, live.user.id) is None:
        raise not_found("No developer profile.")
    ent = await entitlements.for_subject(db, settings, user_id=live.user.id)
    return EntitlementsOut(plan=ent.plan_code, side=ent.side, limits=ent.limits)
