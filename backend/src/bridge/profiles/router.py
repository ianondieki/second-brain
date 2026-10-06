"""Own profile, consents, plan limits and D1 phone verification (/api/me); consent texts (/api/consents).
REQ-CON-01, REQ-BIL-01, REQ-PROV-04.

The profile carries the peers switch (REQ-DEV-03, D-58: ``peers_visible``, off until the developer turns it on; the
time it turned on is the database's and never shown) and the county's name. A change of the county counts toward
``teams.profile_changes_per_day`` with the liked niches' (429 ``too_many_profile_changes``; the 0011 security review's
MINOR 5: the peers set cannot be harvested by rotating the county); the same county sent again is no change."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from bridge.audit.service import record as audit
from bridge.auth.deps import CurrentSession, Db, SettingsDep, client_ip
from bridge.billing import entitlements
from bridge.directory.models import Region
from bridge.errors import ERROR_RESPONSES, ApiError, ApiErrorBody, not_found
from bridge.models.enums import ConsentPurpose, DevVerification, PlanSide, RegionKind
from bridge.profiles import consents, verification
from bridge.profiles.models import DeveloperProfile
from bridge.profiles.verification import SmsDep
from bridge.teams import limits as team_limits

router = APIRouter(prefix="/api/me", tags=["me"], responses=ERROR_RESPONSES)
public_router = APIRouter(prefix="/api/consents", tags=["consents"], responses=ERROR_RESPONSES)


class ProfileOut(BaseModel):
    handle: str
    verification_level: DevVerification
    headline: str | None
    bio: str | None
    county_code: str | None
    county_name: str | None = Field(description="The county's name, when the profile names one")
    peers_visible: bool = Field(
        description="Peers is on: developers in your county or niches see your handle, headline and shared niches"
    )


class ProfileUpdate(BaseModel):
    headline: str | None = Field(default=None, max_length=160)
    bio: str | None = Field(default=None, max_length=4000)
    county_code: str | None = Field(default=None, pattern=r"^KE-\d{2}$")
    peers_visible: bool | None = Field(default=None, description="Turn Peers on or off (null: unchanged)")


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


class PhoneCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=9, max_length=32, description="A Kenyan mobile number: 07.., 01.., 254.. or +254..")


class PhoneCodeSent(BaseModel):
    verification_id: UUID
    expires_at: datetime
    phone_masked: str  # "+254******678"
    attempts_allowed: int


class PhoneCodeConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=12, description="The 6-digit code from the SMS (spaces allowed)")


class VerificationLevelOut(BaseModel):
    verification_level: DevVerification


def _profile_out(p: DeveloperProfile, county_name: str | None) -> ProfileOut:
    return ProfileOut(
        handle=p.handle,
        verification_level=p.verification_level,
        headline=p.headline,
        bio=p.bio,
        county_code=p.county_code,
        county_name=county_name,
        peers_visible=p.peers_visible,
    )


async def _county_name(db: Db, code: str | None) -> str | None:
    if code is None:
        return None
    name: str | None = await db.scalar(select(Region.name).where(Region.code == code))
    return name


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
    return _profile_out(profile, await _county_name(db, profile.county_code))


@router.patch("/profile")
async def update_profile(body: ProfileUpdate, live: CurrentSession, db: Db, settings: SettingsDep) -> ProfileOut:
    """Change your headline, bio, county or the Peers switch (only the fields sent)."""
    profile = await db.get(DeveloperProfile, live.user.id)
    if profile is None:
        raise not_found("No developer profile.")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("peers_visible", False) is None:
        del changes["peers_visible"]  # null leaves the switch as it is
    county = changes.get("county_code")
    if county is not None:
        found = await db.execute(select(Region.code).where(Region.code == county, Region.kind == RegionKind.COUNTY))
        if found.scalar_one_or_none() is None:
            raise ApiError(422, "unknown_county", "Choose one of Kenya's 47 counties.")
    if "county_code" in changes and changes["county_code"] != profile.county_code:
        await team_limits.spend_profile_change(db, settings, live.user.id)
    for name, value in changes.items():
        setattr(profile, name, value)
    await db.commit()
    return _profile_out(profile, await _county_name(db, profile.county_code))


@router.get("/consents")
async def get_consents(live: CurrentSession, db: Db, settings: SettingsDep) -> list[ConsentItem]:
    """Your decision on each purpose the settings page offers. The writing assistant's opt-in
    (``tier2_llm_assistant``) is not listed: it lasts one sign-in and is given in the proposal editor."""
    state = await consents.current(db, live.user.id)
    texts = consents.load_texts(settings.consents_file)
    return [
        ConsentItem(purpose=p, granted=state[p], text=texts[p].text, version=texts[p].version)
        for p in consents.SETTINGS_PURPOSES
    ]


@router.put("/consents")
async def set_consents(
    body: dict[ConsentPurpose, ConsentDecision], live: CurrentSession, db: Db, settings: SettingsDep
) -> list[ConsentItem]:
    """Record decisions; each names the text version it was made on (409 if the wording changed since). A purpose
    decided per sign-in (``tier2_llm_assistant``) is refused with 422 ``consent_session_only``."""
    if any(p in consents.SESSION_ONLY for p in body):
        raise ApiError(422, "consent_session_only", consents.SESSION_ONLY_MESSAGE)
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


@router.post("/verification/phone", status_code=status.HTTP_201_CREATED, responses={503: {"model": ApiErrorBody}})
async def request_phone_code(
    body: PhoneCodeRequest, request: Request, live: CurrentSession, db: Db, settings: SettingsDep, sms: SmsDep
) -> PhoneCodeSent:
    """D1, step 1: text a 6-digit code to a Kenyan mobile number (valid 10 minutes, 5 attempts). Sends are limited
    per account, number and network: 429 ``resend_too_soon`` or ``too_many_codes``; 503 ``sms_unavailable`` when the
    SMS could not be sent (ask again after a minute)."""
    try:
        sent = await verification.request_code(
            db, settings, sms, user=live.user, phone=body.phone, ip=client_ip(request)
        )
    except verification.VerificationError as exc:
        await db.rollback()
        raise exc.api_error() from exc
    return PhoneCodeSent(
        verification_id=sent.verification_id,
        expires_at=sent.expires_at,
        phone_masked=sent.phone_masked,
        attempts_allowed=verification.OTP_MAX_ATTEMPTS,
    )


@router.post("/verification/phone/{verification_id}/confirm")
async def confirm_phone_code(
    verification_id: UUID, body: PhoneCodeConfirm, live: CurrentSession, db: Db, settings: SettingsDep
) -> VerificationLevelOut:
    """D1, step 2: the code from the SMS raises the developer profile to D1. A wrong code is 400 ``invalid_code``
    with ``attempts_left``; the fifth wrong code locks it (429 ``code_locked``); 400 ``code_expired`` after 10
    minutes."""
    try:
        level = await verification.confirm_code(
            db, settings, user=live.user, verification_id=verification_id, code=body.code
        )
    except verification.VerificationError as exc:
        raise exc.api_error() from exc
    return VerificationLevelOut(verification_level=level)
