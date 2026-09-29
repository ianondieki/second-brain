"""REQ-LLM-01 P7 (D-37): a free slot's daily request cap is checked before every attempt, retries included, from the
ledger (not memory), and a refused attempt is a ``blocked_budget`` row that never reaches the provider."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from bridge.config import FreeSlot
from bridge.llm.errors import LLMRequestCapReached
from bridge.llm.fakes import FakeAdapter
from bridge.llm.ledger import CallStatus
from bridge.llm.registry import free_model_key
from bridge.llm.types import CallContext
from tests.unit.llm.helpers import USER, real_registry, settings
from tests.unit.llm.rig import rig, screen
from tests.unit.llm.schemas import Verdict

TASK = "moderation_prescreen"
OK = {"injection_suspected": False, "verdict": "clean", "reason": "fine"}


def free(requests: int) -> FreeSlot:
    return FreeSlot(1, "https://free.example/v1", SecretStr("k"), "vendor/m", requests, "json_object")


async def test_the_third_call_of_a_two_request_slot_is_refused_before_sending() -> None:
    slot = free(2)
    adapter = FakeAdapter([OK, OK, OK])
    r = rig(adapter, reg=real_registry().for_free_slot(slot), cfg=settings(llm_global_daily_cap_usd=0))
    ctx = CallContext(user_id=USER)
    for _ in range(2):
        result = await r.service.complete(TASK, screen(), Verdict, ctx=ctx)
        assert result.model == free_model_key(slot)
        assert result.cost_usd == 0
    with pytest.raises(LLMRequestCapReached):
        await r.service.complete(TASK, screen(), Verdict, ctx=ctx)
    assert len(adapter.requests) == 2
    assert [e.status for e in r.ledger.entries] == [CallStatus.OK, CallStatus.OK, CallStatus.BLOCKED_BUDGET]
    assert {e.model for e in r.ledger.entries} == {free_model_key(slot)}


async def test_a_retry_is_an_attempt_and_counts_against_the_cap() -> None:
    adapter = FakeAdapter(["not json", OK])
    r = rig(adapter, reg=real_registry().for_free_slot(free(1)))
    with pytest.raises(LLMRequestCapReached):
        await r.service.complete(TASK, screen(), Verdict, ctx=CallContext(user_id=USER))
    assert len(adapter.requests) == 1
    assert [e.status for e in r.ledger.entries] == [CallStatus.SCHEMA_ERROR, CallStatus.BLOCKED_BUDGET]
