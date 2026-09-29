"""Demo seed steps for accounts and organisations (``bridge.seed.demo``): developers, fixture organisations and their
seats, the owner-role facts staff would set, TOTP on the fixed demo secrets, D1 through the phone flow, D2, and the
signatory's Master Enterprise Terms."""

from __future__ import annotations

import re
from typing import Final
from uuid import UUID

from cryptography.exceptions import InvalidTag
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge import clock
from bridge.auth import passwords
from bridge.auth.crypto import decode_key, decrypt, encrypt
from bridge.auth.models import User
from bridge.auth.schemas import OrgSignup
from bridge.auth.service import NewAccount, create_account, lock_user
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.ids import uuid7
from bridge.integrations.sms import FakeSmsProvider, SmsProvider
from bridge.legal.models import LegalAcceptance
from bridge.models.enums import ConsentPurpose, DevVerification, MembershipStatus, OrgRole, OrgVerification
from bridge.profiles.consents import record_decisions
from bridge.seed.demo.data import DEMO_PASSWORD, ORGS, DemoDeveloper, DemoOrg, DemoSeat, totp_secret
from bridge.seed.demo.runtime import (
    SEED_METHOD,
    Actors,
    DemoReport,
    DemoSeedError,
    execute,
    one,
    signed_in,
    totp_code,
    user_id_of,
)
from bridge.tenancy.models import Membership

_CODE: Final = re.compile(r"\b(\d{6})\b")


# ---------------------------------------------------------------------------------------------------------- accounts


async def _create_account(
    factory: async_sessionmaker[AsyncSession], settings: Settings, email: str, name: str, org: DemoOrg | None
) -> UUID:
    """What signup does once the address is verified: the user, a developer profile (or the organisation it owns),
    the free plan, the consent decisions (reminders granted) and the ``auth.signup`` audit event."""
    password_hash = await passwords.hash_password_async(DEMO_PASSWORD)
    account = NewAccount(
        email=email,
        display_name=name,
        locale="en",
        side="org" if org else "developer",
        org=OrgSignup(legal_name=org.legal_name, kind=org.kind) if org else None,
        consents={ConsentPurpose.REMINDERS: True},
        method=SEED_METHOD,
    )
    async with factory() as db:
        user = await create_account(db, settings, account, password_hash=password_hash, verified_at=clock.utcnow())
        if user is None:
            raise DemoSeedError(f"{email} was taken while seeding")
        await db.commit()
        return user.id


async def ensure_developer(
    owner: AsyncEngine,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    dev: DemoDeveloper,
    report: DemoReport,
) -> None:
    user_id = await user_id_of(owner, dev.email)
    if user_id is None:
        user_id = await _create_account(factory, settings, dev.email, dev.display_name, None)
        report.did(f"developer {dev.email}")
    report.users[dev.email] = user_id


async def _org_of(owner: AsyncEngine, org: DemoOrg, owner_id: UUID | None) -> UUID | None:
    if owner_id is None:
        row = await one(owner, "SELECT id FROM organizations WHERE slug = :slug", slug=org.slug)
    else:
        row = await one(
            owner,
            "SELECT o.id FROM organizations o JOIN memberships m ON m.org_id = o.id"
            " WHERE m.user_id = :user AND o.legal_name = :name AND 'owner' = ANY (m.roles)",
            user=owner_id,
            name=org.legal_name,
        )
    return None if row is None else UUID(str(row.id))


async def ensure_org(
    owner: AsyncEngine, factory: async_sessionmaker[AsyncSession], settings: Settings, org: DemoOrg, report: DemoReport
) -> None:
    if org.owner is None:  # E0: listed from "public information", as the provisional directory rows are
        org_id = await _org_of(owner, org, None)
        if org_id is None:
            org_id = uuid7()
            await execute(
                owner,
                "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, county_code)"
                " VALUES (:id, CAST(:kind AS org_kind), :name, :slug, 'admin', 'unclaimed', :county)",
                id=org_id,
                kind=org.kind.value,
                name=org.legal_name,
                slug=org.slug,
                county=org.county,
            )
            report.did(f"organisation {org.legal_name}")
        report.orgs[org.legal_name] = org_id
        return
    owner_id = await user_id_of(owner, org.owner.email)
    if owner_id is None:
        owner_id = await _create_account(factory, settings, org.owner.email, org.owner.display_name, org)
        report.did(f"organisation {org.legal_name} signed up by {org.owner.email}")
    report.users[org.owner.email] = owner_id
    org_id = await _org_of(owner, org, owner_id)
    if org_id is None:
        raise DemoSeedError(f"{org.owner.email} exists but owns no organisation named {org.legal_name}")
    report.orgs[org.legal_name] = org_id
    for seat in org.seats:
        await _ensure_seat(owner, factory, settings, org_id, owner_id, seat, report)


async def _ensure_seat(
    owner: AsyncEngine,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    org_id: UUID,
    owner_id: UUID,
    seat: DemoSeat,
    report: DemoReport,
) -> None:
    """A member added by the organisation's owner (the invitation flow is not built): the account, its consent to
    reminders, and the membership inserted under the owner's Row-Level Security (owners grant protected roles)."""
    user_id = await user_id_of(owner, seat.email)
    async with factory() as db:
        if user_id is None:
            user_id = uuid7()
            db.add(
                User(
                    id=user_id,
                    email=seat.email,
                    password_hash=await passwords.hash_password_async(DEMO_PASSWORD),
                    display_name=seat.display_name,
                    locale="en",
                    email_verified_at=clock.utcnow(),
                )
            )
            await db.flush()
            await bind_tenant(db, user_id=user_id)
            await record_decisions(
                db, settings, user_id=user_id, decisions={ConsentPurpose.REMINDERS: True}, source=SEED_METHOD
            )
            report.did(f"account {seat.email}")
        member = await one(
            owner, "SELECT id FROM memberships WHERE org_id = :org AND user_id = :user", org=org_id, user=user_id
        )
        if member is None:
            await bind_tenant(db, user_id=owner_id, org_id=org_id)
            db.add(
                Membership(
                    id=uuid7(),
                    org_id=org_id,
                    user_id=user_id,
                    roles=sorted(seat.roles),
                    status=MembershipStatus.ACTIVE,
                )
            )
            report.did(f"membership {seat.email} ({'+'.join(r.value for r in seat.roles)})")
        await db.commit()
    report.users[seat.email] = user_id


# ---------------------------------------------------------------------------------------------- owner-role facts


async def owner_facts(owner: AsyncEngine, niches: dict[str, UUID], report: DemoReport) -> None:
    """What staff decide and no application path writes yet: the D-37 demo flag, D2, and each fixture organisation's
    verification level, verified domain, county and niche."""
    emails = sorted(report.users)
    flagged = await execute(
        owner, "UPDATE users SET demo_account = true WHERE email = ANY(:emails) AND NOT demo_account", emails=emails
    )
    if flagged:
        report.did("demo_account flags")
    for org in ORGS:
        org_id = report.orgs[org.legal_name]
        changed = await execute(
            owner,
            "UPDATE organizations SET verification = CAST(:level AS org_verification), verified_domain = :domain,"
            " official_domains = CAST(:domains AS citext[]), county_code = :county,"
            " e2_verified_at = CASE WHEN :level = 'e2' THEN coalesce(e2_verified_at, now()) END, updated_at = now()"
            " WHERE id = :id AND (verification <> CAST(:level AS org_verification)"
            " OR verified_domain IS DISTINCT FROM :domain OR county_code IS DISTINCT FROM :county)",
            id=org_id,
            level=org.verification.value,
            domain=org.domain,
            domains=[org.domain] if org.domain else [],
            county=org.county,
        )
        if changed:
            report.did(f"{org.legal_name} verified {org.verification.value}")
        added = await execute(
            owner,
            "INSERT INTO org_niches (org_id, niche_id) VALUES (:org, :niche) ON CONFLICT DO NOTHING",
            org=org_id,
            niche=niches[org.niche],
        )
        if added:
            report.did(f"{org.legal_name} niche {org.niche}")


async def raise_to_d2(owner: AsyncEngine, dev: DemoDeveloper, report: DemoReport) -> None:
    """D2 (KYC review) has no application path yet: set as staff would, only once D1 is done."""
    if dev.level != DevVerification.D2:
        return
    changed = await execute(
        owner,
        "UPDATE developer_profiles SET verification_level = 'd2', updated_at = now()"
        " WHERE user_id = :user AND verification_level = 'd1'",
        user=report.users[dev.email],
    )
    if changed:
        report.did(f"{dev.email} D2")


async def accept_master_terms(
    owner: AsyncEngine, factory: async_sessionmaker[AsyncSession], org: DemoOrg, report: DemoReport
) -> None:
    """The signatory accepts the current Master Enterprise Terms for an E2 fixture (under RLS; no route yet)."""
    signatory = next((seat for seat in org.seats if OrgRole.SIGNATORY in seat.roles), None)
    if org.verification != OrgVerification.E2 or signatory is None:
        return
    org_id, user_id = report.orgs[org.legal_name], report.users[signatory.email]
    current = await one(
        owner,
        "SELECT id, sha256 FROM legal_templates WHERE id = app_current_legal_template('master_enterprise_terms')",
    )
    if current is None:
        raise DemoSeedError("no Master Enterprise Terms template: run the reference seed first")
    accepted = await one(
        owner,
        "SELECT 1 FROM legal_acceptances WHERE org_id = :org AND user_id = :user AND legal_template_id = :template",
        org=org_id,
        user=user_id,
        template=current.id,
    )
    if accepted is not None:
        return
    async with factory() as db:
        await bind_tenant(db, user_id=user_id, org_id=org_id)
        db.add(
            LegalAcceptance(
                id=uuid7(), org_id=org_id, user_id=user_id, legal_template_id=current.id, template_sha256=current.sha256
            )
        )
        await db.commit()
    report.did(f"{org.legal_name} Master Enterprise Terms accepted by {signatory.email}")


# ---------------------------------------------------------------------------------------------------------- TOTP


async def enrol_totp(
    app: FastAPI,
    owner: AsyncEngine,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    email: str,
    report: DemoReport,
) -> None:
    """Enrol the account's fixed demo secret: the pending secret is sealed as ``begin_totp_enrolment`` seals its random
    one, then the user signs in with the demo password and ``POST /api/auth/totp/confirm`` confirms it with the current
    code (recovery codes, audit, notice email). An enrolled secret that does not open under this
    ``DATA_ENCRYPTION_KEY`` means that other keys seeded the database."""
    secret = totp_secret(email)
    key = decode_key(settings.data_encryption_key.get_secret_value())
    user_id = report.users[email]
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        user = await lock_user(db, user_id)
        if user.totp_secret_enc is not None:
            try:
                stored = decrypt(key, user.totp_secret_enc, user.id.bytes).decode("ascii")
            except InvalidTag as exc:
                raise DemoSeedError(
                    f"{email}'s TOTP secret does not open with this DATA_ENCRYPTION_KEY: the demo database was"
                    " seeded with other keys; run make demo-reset"
                ) from exc
            if stored != secret:
                raise DemoSeedError(f"{email} has a TOTP secret that is not the demo one; run make demo-reset")
            return
        user.totp_pending_enc = encrypt(key, secret.encode("ascii"), user.id.bytes)
        await db.commit()
    async with signed_in(app, owner, email) as actor:
        await actor.call("POST", "/api/auth/totp/confirm", json={"code": totp_code(email)})
    report.did(f"TOTP {email}")


# ------------------------------------------------------------------------------------------------------------- D1


async def verify_phone(
    owner: AsyncEngine, actors: Actors, dev: DemoDeveloper, sms: SmsProvider, report: DemoReport
) -> None:
    """D1 through the phone-code routes; the fake SMS provider keeps the code in memory, where the seed reads it."""
    level = await one(
        owner,
        "SELECT verification_level::text AS level FROM developer_profiles WHERE user_id = :u",
        u=report.users[dev.email],
    )
    if level is not None and level.level != DevVerification.D0.value:
        return
    if not isinstance(sms, FakeSmsProvider):
        raise DemoSeedError("the demo seed verifies phones through the fake SMS provider (SMS_PROVIDER=fake)")
    actor = await actors.get(dev.email)
    sent = await actor.call("POST", "/api/me/verification/phone", json={"phone": dev.phone}, expect=(201,))
    message = next((m for m in reversed(sms.outbox) if m.to == dev.phone), None)
    found = _CODE.search(message.text) if message else None
    if found is None:
        raise DemoSeedError(f"no code was texted to {dev.email}'s demo number")
    verification_id = sent.json()["verification_id"]
    await actor.call("POST", f"/api/me/verification/phone/{verification_id}/confirm", json={"code": found.group(1)})
    report.did(f"{dev.email} D1")
