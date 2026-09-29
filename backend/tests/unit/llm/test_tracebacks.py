"""REQ-LLM-01: errors are raised ``from None``, so a formatted traceback never carries the model's output or the
provider's body (either may quote Tier-2 text or injected content)."""

from __future__ import annotations

import json
import traceback

import pytest

from bridge.llm.cassettes import CassettePlayer, Interaction
from bridge.llm.errors import LLMProviderError, LLMSchemaError
from bridge.llm.fakes import FakeAdapter
from bridge.llm.types import CallContext
from tests.unit.llm.rig import rig, screen
from tests.unit.llm.schemas import Verdict

CANARY = "CANARY-TRACEBACK-51e0"
TASK = "moderation_prescreen"


def formatted(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))


async def test_schema_failure_traceback_has_no_model_output() -> None:
    bad = json.dumps({"injection_suspected": False, "verdict": CANARY, "reason": CANARY})
    r = rig(FakeAdapter([bad, bad]))
    with pytest.raises(LLMSchemaError) as info:
        await r.service.complete(TASK, screen(), Verdict, ctx=CallContext())
    assert info.value.__cause__ is None
    assert CANARY not in formatted(info.value)


async def test_provider_error_traceback_has_no_provider_body() -> None:
    body = json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": f"bad {CANARY}"}})
    tape = CassettePlayer([Interaction("POST", "/v1/messages", 400, body.encode(), "application/json")])
    with pytest.raises(LLMProviderError) as info:
        await rig(tape.adapter()).service.complete(TASK, screen(), Verdict, ctx=CallContext())
    assert info.value.status_code == 400
    assert CANARY not in formatted(info.value)
