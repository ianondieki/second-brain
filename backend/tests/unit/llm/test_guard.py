"""AC-SEC-6 (unit half): the Tier-2 guard refuses Tier-2 fields for Tier-1-only purposes and without the exact live
consent; the full per-task assertion over the ledger and the transport is test_no_tier2_in_llm_calls.py, and the
per-session consent against PostgreSQL and RLS is tests/integration/llm/test_session_consent.py."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from bridge.auth import sessions as login_sessions
from bridge.llm.errors import ConsentRequired, Tier2NotAllowed
from bridge.llm.guard import (
    SessionConsentChecker,
    StaticConsents,
    check_tier2,
    grant_session_consent,
    session_consent_source,
    withdraw_session_consent,
)
from bridge.llm.types import InputField, Instruction, Message, Tier
from bridge.models.enums import ConsentPurpose
from bridge.profiles import consents
from tests.unit.llm.helpers import OTHER_OWNER, OTHER_SESSION, OWNER, SESSION, real_registry, settings
from tests.unit.llm.rig import registry_with

ASSISTANT = ConsentPurpose.TIER2_LLM_ASSISTANT
MODERATION = ConsentPurpose.TIER2_LLM_MODERATION


def tier2(name: str = "confidential.method", owner: UUID = OWNER) -> InputField:
    return InputField(name, "SECRET-METHOD", tier=Tier.TIER2, owner_id=owner)


def msgs(*fields: InputField) -> list[Message]:
    return [
        Message.system("You help."),
        Message.user(Instruction("Review:"), InputField("teaser.summary", "public"), *fields),
    ]


async def test_tier1_fields_always_pass() -> None:
    for task in real_registry().tasks.values():
        await check_tier2(task, msgs(), StaticConsents())


@pytest.mark.parametrize("task", ["moderation_prescreen", "over_disclosure_check", "originality_explainer"])
async def test_tier1_only_tasks_refuse_tier2_even_with_every_consent(task: str) -> None:
    consents = StaticConsents({(OWNER, p) for p in ConsentPurpose})
    with pytest.raises(Tier2NotAllowed) as info:
        await check_tier2(real_registry().task(task), msgs(tier2()), consents)
    assert info.value.fields == ("confidential.method",)
    assert "SECRET" not in str(info.value)


async def test_assistant_needs_the_owners_live_assistant_consent() -> None:
    task = real_registry().task("submission_assistant")
    consents = StaticConsents({(OWNER, ConsentPurpose.TIER2_LLM_MODERATION)})  # the other purpose does not count
    with pytest.raises(ConsentRequired) as info:
        await check_tier2(task, msgs(tier2()), consents)
    assert info.value.purpose is ASSISTANT
    consents.grant(OWNER, ASSISTANT, session_id=SESSION)
    await check_tier2(task, msgs(tier2()), consents, session_id=SESSION)
    for other in (OTHER_SESSION, None):  # per session (ADR-005 decision 4): another session or a job does not count
        with pytest.raises(ConsentRequired):
            await check_tier2(task, msgs(tier2()), consents, session_id=other)
    consents.withdraw(OWNER, ASSISTANT)
    with pytest.raises(ConsentRequired):
        await check_tier2(task, msgs(tier2()), consents, session_id=SESSION)


async def test_moderation_consent_is_persistent() -> None:
    task = registry_with(moderation_prescreen={"purpose": "tier2_llm_moderation"}).task("moderation_prescreen")
    consents = StaticConsents({(OWNER, ConsentPurpose.TIER2_LLM_MODERATION)})
    for session in (SESSION, None):
        await check_tier2(task, msgs(tier2()), consents, session_id=session)
    assert not await consents.has_live_consent(OWNER, ASSISTANT, session_id=SESSION)


async def test_every_owner_must_consent() -> None:
    task = real_registry().task("submission_assistant")
    consents = StaticConsents({(OWNER, ASSISTANT, SESSION)})
    with pytest.raises(ConsentRequired) as info:
        await check_tier2(task, msgs(tier2(), tier2("other.method", OTHER_OWNER)), consents, session_id=SESSION)
    assert info.value.fields == ("other.method",)


async def test_a_later_grant_in_another_session_replaces_the_first() -> None:
    consents = StaticConsents({(OWNER, ASSISTANT, SESSION)})
    consents.grant(OWNER, ASSISTANT, session_id=OTHER_SESSION)
    assert not await consents.has_live_consent(OWNER, ASSISTANT, session_id=SESSION)
    assert await consents.has_live_consent(OWNER, ASSISTANT, session_id=OTHER_SESSION)
    consents.grant(OWNER, ASSISTANT)  # a grant without a session (the settings page) is no per-use opt-in
    assert not await consents.has_live_consent(OWNER, ASSISTANT, session_id=OTHER_SESSION)


async def test_session_checker_reads_persistent_consents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persistent purposes go through bridge.profiles.consents; the SQL itself is covered by the integration test."""
    seen: list[tuple[Any, ...]] = []

    async def fake(db: Any, user_id: UUID, purpose: ConsentPurpose) -> bool:
        seen.append((db, user_id, purpose))
        return True

    monkeypatch.setattr(consents, "has_live_consent", fake)
    session = object()
    checker = SessionConsentChecker(session)  # type: ignore[arg-type]
    assert await checker.has_live_consent(OWNER, MODERATION, session_id=None)
    assert seen == [(session, OWNER, MODERATION)]
    assert not await checker.has_live_consent(OWNER, ASSISTANT, session_id=None)  # per session: no session, no consent


@pytest.mark.parametrize(
    ("latest", "live"),
    [
        (None, False),  # never decided
        ({"granted": True, "source": "session"}, True),  # granted in this session (placeholder resolved below)
        ({"granted": False, "source": "session"}, False),  # withdrawn in this session
        ({"granted": True, "source": "other"}, False),  # granted in another session
        ({"granted": True, "source": "settings"}, False),  # granted on the settings page: no per-use opt-in
    ],
)
async def test_session_checker_compares_the_latest_decisions_source(
    monkeypatch: pytest.MonkeyPatch, latest: dict[str, Any] | None, live: bool
) -> None:
    sources = {"session": session_consent_source(SESSION), "other": session_consent_source(OTHER_SESSION)}
    seen: list[tuple[Any, ...]] = []

    async def fake(db: Any, user_id: UUID, purpose: ConsentPurpose) -> Any:
        seen.append((db, user_id, purpose))
        if latest is None:
            return None
        return SimpleNamespace(granted=latest["granted"], source=sources.get(latest["source"], latest["source"]))

    async def session_live(db: Any, session_id: UUID, *, user_id: UUID) -> bool:
        return True

    monkeypatch.setattr(consents, "latest", fake)
    monkeypatch.setattr(login_sessions, "is_live", session_live)
    db = object()
    assert await SessionConsentChecker(db).has_live_consent(OWNER, ASSISTANT, session_id=SESSION) is live  # type: ignore[arg-type]
    assert seen == [(db, OWNER, ASSISTANT)]


async def test_session_checker_needs_a_live_login_session_of_the_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """A grant naming the call's session is dead unless that session is a live login session of the owner (the SQL,
    revoked, expired and foreign sessions, is covered by the integration test)."""
    asked: list[tuple[Any, ...]] = []

    async def session_live(db: Any, session_id: UUID, *, user_id: UUID) -> bool:
        asked.append((db, session_id, user_id))
        return False

    async def latest(db: Any, user_id: UUID, purpose: ConsentPurpose) -> Any:
        return SimpleNamespace(granted=True, source=session_consent_source(SESSION))

    monkeypatch.setattr(login_sessions, "is_live", session_live)
    monkeypatch.setattr(consents, "latest", latest)
    db = object()
    assert not await SessionConsentChecker(db).has_live_consent(OWNER, ASSISTANT, session_id=SESSION)  # type: ignore[arg-type]
    assert asked == [(db, SESSION, OWNER)]


@pytest.mark.parametrize(("writer", "granted"), [(grant_session_consent, True), (withdraw_session_consent, False)])
async def test_session_writers_record_one_session_bound_decision(
    monkeypatch: pytest.MonkeyPatch, writer: Any, granted: bool
) -> None:
    recorded: list[dict[str, Any]] = []

    async def fake(db: Any, cfg: Any, **kwargs: Any) -> None:
        recorded.append({"db": db, "settings": cfg, **kwargs})

    monkeypatch.setattr(consents, "record_decisions", fake)
    db, cfg = object(), settings()
    await writer(db, cfg, user_id=OWNER, session_id=SESSION)
    assert recorded == [
        {
            "db": db,
            "settings": cfg,
            "user_id": OWNER,
            "decisions": {ASSISTANT: granted},
            "source": session_consent_source(SESSION),
        }
    ]


def test_session_consent_source_fits_the_column() -> None:
    source = session_consent_source(SESSION)
    assert source.startswith("session:")
    assert len(source) <= 32  # consents.source is String(32)
    assert source != session_consent_source(OTHER_SESSION)


def test_input_field_validation() -> None:
    with pytest.raises(ValueError, match="owner_id"):
        InputField("x", "y", tier=Tier.TIER2)
    with pytest.raises(ValueError, match="field name"):
        InputField("Bad Name", "y")
    with pytest.raises(ValueError, match="max_chars"):
        InputField("x", "y", max_chars=0)
    assert "SECRET" not in repr(tier2())


def test_messages_keep_untrusted_fields_in_user_turns() -> None:
    with pytest.raises(ValueError, match="system turn"):
        Message("system", (InputField("x", "y"),))
    with pytest.raises(ValueError, match="at least one part"):
        Message("user", ())
    with pytest.raises(ValueError, match="needs text"):
        Instruction("  ")
    for role in ("user", "assistant"):
        with pytest.raises(TypeError, match="never bare strings"):
            Message(role, ("untrusted text passed as a plain string",))  # type: ignore[arg-type]
    assert Message.system("You help.").parts == (Instruction("You help."),)
    assert Message.user(Instruction("a"), InputField("x", "y")).fields == (InputField("x", "y"),)
    replay = InputField("history.answer", "earlier answer", tier=Tier.TIER2, owner_id=OWNER)
    assert Message.assistant(replay).fields == (replay,)  # untrusted replays are fields, never instructions
