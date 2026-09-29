"""AC-SEC-6 (REQ-LLM-01; ADR-005 decision 4; docs/spec/06 §6.3): per-session Tier-2 consent against PostgreSQL, as
``bridge_app`` under Row-Level Security.

``tier2_llm_assistant`` is recorded per login session by ``grant_session_consent`` and is live only for that session
while it is the owner's latest decision and the session is a live login session of the owner (not revoked, not
expired, the owner active); ``tier2_llm_moderation`` is persistent. Every database session is RLS-bound with
``bind_tenant``, exactly as a request uses it, so another user's context reads no consent and fails closed.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import bridge.models.all  # noqa: F401  # registers every table (foreign keys resolve at flush)
from bridge.config import get_settings
from bridge.db import bind_tenant, create_session_factory
from bridge.ids import uuid7
from bridge.llm import registry
from bridge.llm.errors import ConsentRequired
from bridge.llm.guard import (
    SessionConsentChecker,
    check_tier2,
    grant_session_consent,
    session_consent_source,
    withdraw_session_consent,
)
from bridge.llm.types import InputField, Instruction, Message, Tier
from bridge.models.enums import ConsentPurpose
from bridge.profiles import consents
from bridge.profiles.models import Consent
from tests.integration.llm.helpers import login

ASSISTANT = ConsentPurpose.TIER2_LLM_ASSISTANT
MODERATION = ConsentPurpose.TIER2_LLM_MODERATION


@pytest.fixture(scope="module")
def factory(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(app_engine)


@pytest.fixture
async def user(owner_engine: AsyncEngine) -> UUID:
    """A fresh user per test (written as the owner role), so decisions never leak between tests."""
    user_id = uuid7()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Consent')"),
            {"id": user_id, "email": f"llm-consent-{user_id.hex[-12:]}@example.test"},
        )
    return user_id


@pytest.fixture
async def other_user(owner_engine: AsyncEngine) -> UUID:
    user_id = uuid7()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Other')"),
            {"id": user_id, "email": f"llm-other-{user_id.hex[-12:]}@example.test"},
        )
    return user_id


async def _grant(factory: async_sessionmaker[AsyncSession], user_id: UUID, session_id: UUID) -> None:
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        await grant_session_consent(db, get_settings(), user_id=user_id, session_id=session_id)
        await db.commit()


async def _withdraw(factory: async_sessionmaker[AsyncSession], user_id: UUID, session_id: UUID) -> None:
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        await withdraw_session_consent(db, get_settings(), user_id=user_id, session_id=session_id)
        await db.commit()


async def _record(
    factory: async_sessionmaker[AsyncSession], user_id: UUID, purpose: ConsentPurpose, granted: bool
) -> None:
    """A decision from the settings page (source ``settings``), not bound to any session."""
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        await consents.record_decisions(
            db, get_settings(), user_id=user_id, decisions={purpose: granted}, source="settings"
        )
        await db.commit()


async def _stored_before_the_refusals(
    factory: async_sessionmaker[AsyncSession], user_id: UUID, purpose: ConsentPurpose, granted: bool
) -> None:
    """A ``settings`` row on a per-session purpose, as stored before the settings API (P13), signup and
    ``record_decisions`` (P17) refused one: written directly, since ``record_decisions`` now refuses it."""
    shown = consents.load_texts(get_settings().consents_file)[purpose]
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        db.add(
            Consent(
                user_id=user_id,
                purpose=shown.purpose,
                granted=granted,
                text_version=shown.version,
                text_sha256=shown.sha256,
                source="settings",
            )
        )
        await db.commit()


async def _live(
    factory: async_sessionmaker[AsyncSession],
    owner: UUID,
    purpose: ConsentPurpose,
    session_id: UUID | None,
    *,
    as_user: UUID | None = None,
) -> bool:
    """Ask the checker as ``as_user`` (default: the owner); ``bind_tenant(None)`` means no tenant context at all."""
    async with factory() as db:
        await bind_tenant(db, user_id=owner if as_user is None else as_user)
        return await SessionConsentChecker(db).has_live_consent(owner, purpose, session_id=session_id)


def _assistant_call(owner: UUID) -> list[Message]:
    return [
        Message.system("You help."),
        Message.user(
            Instruction("Suggest a placement:"),
            InputField("confidential.method", "SECRET-METHOD", tier=Tier.TIER2, owner_id=owner),
        ),
    ]


async def test_a_grant_is_live_in_its_own_session_only(factory: async_sessionmaker[AsyncSession], user: UUID) -> None:
    session, other_session = await login(factory, user), await login(factory, user)  # two live logins of the owner
    await _grant(factory, user, session)

    assert await _live(factory, user, ASSISTANT, session)
    assert not await _live(factory, user, ASSISTANT, other_session)
    assert not await _live(factory, user, ASSISTANT, None)  # a job carries no session

    async with factory() as db:  # the stored decision: the session-bound source, the text version and its hash
        await bind_tenant(db, user_id=user)
        row = (await db.execute(select(Consent).where(Consent.user_id == user))).scalar_one()
    shown = consents.load_texts(get_settings().consents_file)[ASSISTANT]
    assert (row.purpose, row.granted, row.source) == (ASSISTANT, True, session_consent_source(session))
    assert (row.text_version, row.text_sha256) == (shown.version, shown.sha256)
    assert len(row.source) <= 32


async def test_the_guard_admits_tier2_in_the_granting_session_only(
    factory: async_sessionmaker[AsyncSession], user: UUID
) -> None:
    session, other_session = await login(factory, user), await login(factory, user)
    task = registry.load(get_settings().llm_models_file).task("submission_assistant")
    await _grant(factory, user, session)
    async with factory() as db:
        await bind_tenant(db, user_id=user)
        checker = SessionConsentChecker(db)
        await check_tier2(task, _assistant_call(user), checker, session_id=session)
        for other in (other_session, None):
            with pytest.raises(ConsentRequired) as info:
                await check_tier2(task, _assistant_call(user), checker, session_id=other)
            assert info.value.purpose is ASSISTANT


async def test_a_later_withdrawal_ends_it(factory: async_sessionmaker[AsyncSession], user: UUID) -> None:
    session = await login(factory, user)
    await _grant(factory, user, session)
    await _withdraw(factory, user, session)
    assert not await _live(factory, user, ASSISTANT, session)

    await _grant(factory, user, session)  # the latest decision wins: a fresh opt-in in the same session is live again
    assert await _live(factory, user, ASSISTANT, session)
    await _stored_before_the_refusals(factory, user, ASSISTANT, False)  # an older settings withdrawal ends it too
    assert not await _live(factory, user, ASSISTANT, session)


async def test_a_later_grant_in_another_session_replaces_it(
    factory: async_sessionmaker[AsyncSession], user: UUID
) -> None:
    session, next_session = await login(factory, user), await login(factory, user)
    await _grant(factory, user, session)
    await _grant(factory, user, next_session)
    assert not await _live(factory, user, ASSISTANT, session)
    assert await _live(factory, user, ASSISTANT, next_session)


async def test_a_grant_not_bound_to_a_session_is_never_live(
    factory: async_sessionmaker[AsyncSession], user: UUID
) -> None:
    """A ``tier2_llm_assistant`` grant from the settings page is not a per-use opt-in: it opens no session."""
    await _stored_before_the_refusals(factory, user, ASSISTANT, True)
    for session in (await login(factory, user), None):
        assert not await _live(factory, user, ASSISTANT, session)


async def test_moderation_consent_is_persistent_across_sessions(
    factory: async_sessionmaker[AsyncSession], user: UUID
) -> None:
    await _record(factory, user, MODERATION, True)
    for session in (uuid7(), uuid7(), None):
        assert await _live(factory, user, MODERATION, session)
    await _grant(factory, user, uuid7())  # the per-session assistant opt-in does not touch moderation
    assert await _live(factory, user, MODERATION, None)
    await _record(factory, user, MODERATION, False)
    assert not await _live(factory, user, MODERATION, None)


async def test_another_users_context_reads_nothing(
    factory: async_sessionmaker[AsyncSession], user: UUID, other_user: UUID
) -> None:
    """RLS scopes consents to app.user_id: a foreign context sees no decision and the check fails closed."""
    session = await login(factory, user)
    await _grant(factory, user, session)
    await _record(factory, user, MODERATION, True)
    assert await _live(factory, user, ASSISTANT, session)  # positive control in the owner's own context

    assert not await _live(factory, user, ASSISTANT, session, as_user=other_user)
    assert not await _live(factory, user, MODERATION, None, as_user=other_user)
    async with factory() as db:  # no tenant context at all
        checker = SessionConsentChecker(db)
        assert not await checker.has_live_consent(user, ASSISTANT, session_id=session)
        assert not await checker.has_live_consent(user, MODERATION, session_id=None)


async def test_a_grant_for_another_user_is_refused_by_rls(
    factory: async_sessionmaker[AsyncSession], user: UUID, other_user: UUID
) -> None:
    """The writer runs in the caller's RLS context: it cannot record a decision on someone else's behalf."""
    async with factory() as db:
        await bind_tenant(db, user_id=other_user)
        with pytest.raises(ProgrammingError, match="row-level security"):
            await grant_session_consent(db, get_settings(), user_id=user, session_id=uuid7())
        await db.rollback()
    async with factory() as db:
        await bind_tenant(db, user_id=user)
        assert (await db.execute(select(Consent).where(Consent.user_id == user))).all() == []


async def test_the_opt_in_lives_only_as_long_as_the_owners_login_session(
    factory: async_sessionmaker[AsyncSession], owner_engine: AsyncEngine, user: UUID, other_user: UUID
) -> None:
    """The call's session must be a live login session of the owner (the rule of ``bridge.auth.sessions.lookup``):
    an expired session, another user's session, a suspended owner, a login still waiting for its second factor or a
    revoked session ends the opt-in, although the grant is the owner's latest decision and names that very session."""
    expired = await login(factory, user, expires_in=-timedelta(minutes=1))
    await _grant(factory, user, expired)
    assert not await _live(factory, user, ASSISTANT, expired)

    theirs = await login(factory, other_user)  # a live session, but not the owner's
    await _grant(factory, user, theirs)
    assert not await _live(factory, user, ASSISTANT, theirs)

    session = await login(factory, user)
    await _grant(factory, user, session)
    assert await _live(factory, user, ASSISTANT, session)  # positive control: the owner's live session

    for status, live in (("suspended", False), ("active", True)):
        async with owner_engine.begin() as conn:
            suspend = text("UPDATE users SET status = CAST(:s AS user_status) WHERE id = :u")
            await conn.execute(suspend, {"s": status, "u": user})
        assert await _live(factory, user, ASSISTANT, session) is live

    async with factory() as db:  # a login waiting for its second factor is not live (security review 2026-09-29)
        await db.execute(text("UPDATE sessions SET mfa_pending = true WHERE id = :id"), {"id": session})
        await db.commit()
    assert not await _live(factory, user, ASSISTANT, session)
    async with factory() as db:
        await db.execute(text("UPDATE sessions SET mfa_pending = false WHERE id = :id"), {"id": session})
        await db.commit()
    assert await _live(factory, user, ASSISTANT, session)

    async with factory() as db:  # logout, as bridge.auth.sessions.revoke does
        await db.execute(text("UPDATE sessions SET revoked_at = now() WHERE id = :id"), {"id": session})
        await db.commit()
    assert not await _live(factory, user, ASSISTANT, session)
