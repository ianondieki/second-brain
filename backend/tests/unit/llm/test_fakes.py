"""REQ-LLM-01: FakeLLMClient (the real service over a scripted adapter) for callers' unit tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bridge.llm.adapter import BatchItemError
from bridge.llm.budget import StaticCaps
from bridge.llm.client import BatchItem
from bridge.llm.errors import LLMBudgetExceeded, LLMProviderError, Tier2NotAllowed
from bridge.llm.fakes import FakeAdapter, FakeLLMClient
from bridge.llm.ledger import CallStatus
from bridge.llm.types import CallContext, InputField, Instruction, Message, Result, Tier
from tests.unit.llm.helpers import ORG, OWNER, settings
from tests.unit.llm.rig import registry_with, screen
from tests.unit.llm.schemas import Verdict

TASK = "moderation_prescreen"
CTX = CallContext(org_id=ORG)
OK = Verdict(injection_suspected=False, verdict="clean", reason="fine")


async def test_scripted_replies_in_every_form() -> None:
    fake = FakeLLMClient([OK, {"injection_suspected": True, "verdict": "hold", "reason": "r"}])
    first = await fake.complete(TASK, screen(), Verdict, ctx=CTX)
    second = await fake.complete(TASK, screen(), Verdict, ctx=CTX)
    assert first.parsed == OK
    assert second.parsed.injection_suspected
    assert len(fake.requests) == 2
    assert [e.status for e in fake.ledger.entries] == [CallStatus.OK, CallStatus.OK]
    assert all(e.cost_usd > 0 for e in fake.ledger.entries)


async def test_raw_text_goes_through_the_schema_retry() -> None:
    fake = FakeLLMClient(["not json"])
    fake.queue(OK)
    result = await fake.complete(TASK, screen(), Verdict, ctx=CTX)
    assert result.attempts == 2
    assert "did not match" in fake.requests[1].messages[-1].blocks[-1].text


async def test_scripted_exceptions_and_exhaustion() -> None:
    fake = FakeLLMClient([LLMProviderError("down", transient=True)])
    with pytest.raises(LLMProviderError):
        await fake.complete(TASK, screen(), Verdict, ctx=CTX)
    with pytest.raises(AssertionError, match="no scripted reply"):
        await fake.complete(TASK, screen(), Verdict, ctx=CTX)
    with pytest.raises(AssertionError, match="batch reply"):
        await FakeAdapter([BatchItemError("expired", "expired")]).create(fake.requests[0])


async def test_the_fake_still_guards_tier2_and_caps() -> None:
    fake = FakeLLMClient([OK])
    secret = InputField("confidential.method", "SECRET", tier=Tier.TIER2, owner_id=OWNER)
    with pytest.raises(Tier2NotAllowed):
        await fake.complete(TASK, [Message.user(Instruction("x"), secret)], Verdict, ctx=CTX)
    capped = FakeLLMClient([OK], caps=StaticCaps(default=Decimal(0)), settings=settings())
    with pytest.raises(LLMBudgetExceeded):
        await capped.complete(TASK, screen(), Verdict, ctx=CTX)


async def test_fake_batches() -> None:
    fake = FakeLLMClient(
        [OK, BatchItemError("errored", "invalid_request_error")],
        registry=registry_with(moderation_prescreen={"batchable": True}),
    )
    handle = await fake.batch_submit(TASK, [BatchItem("a", screen()), BatchItem("b", screen())], Verdict, ctx=CTX)
    poll = await fake.batch_poll(handle, Verdict)
    assert isinstance(poll.results["a"], Result)
    assert isinstance(poll.results["b"], LLMProviderError)
    assert len(fake.requests) == 2
