"""AC-SEC-6 (unit half): the Tier-2 guard refuses Tier-2 fields for Tier-1-only purposes and without the exact live
consent; the full per-task assertion over the ledger and the transport is test_no_tier2_in_llm_calls.py."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from bridge.llm.errors import ConsentRequired, Tier2NotAllowed
from bridge.llm.guard import SessionConsentChecker, StaticConsents, check_tier2
from bridge.llm.types import InputField, Instruction, Message, Tier
from bridge.models.enums import ConsentPurpose
from bridge.profiles import consents
from tests.unit.llm.helpers import OTHER_OWNER, OWNER, real_registry

ASSISTANT = ConsentPurpose.TIER2_LLM_ASSISTANT


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
    consents.grant(OWNER, ASSISTANT)
    await check_tier2(task, msgs(tier2()), consents)
    consents.withdraw(OWNER, ASSISTANT)
    with pytest.raises(ConsentRequired):
        await check_tier2(task, msgs(tier2()), consents)


async def test_every_owner_must_consent() -> None:
    task = real_registry().task("submission_assistant")
    consents = StaticConsents({(OWNER, ASSISTANT)})
    with pytest.raises(ConsentRequired) as info:
        await check_tier2(task, msgs(tier2(), tier2("other.method", OTHER_OWNER)), consents)
    assert info.value.fields == ("other.method",)


async def test_session_checker_reads_consents(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[Any, ...]] = []

    async def fake(db: Any, user_id: UUID, purpose: ConsentPurpose) -> bool:
        seen.append((db, user_id, purpose))
        return True

    monkeypatch.setattr(consents, "has_live_consent", fake)
    session = object()
    assert await SessionConsentChecker(session).has_live_consent(OWNER, ASSISTANT)  # type: ignore[arg-type]
    assert seen == [(session, OWNER, ASSISTANT)]


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
