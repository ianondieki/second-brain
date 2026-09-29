"""REQ-LLM-01 P7 (D-37): the answer behind the "demo fallback" label fails closed.

Security review P7, MAJOR 2: a fallback built from the schema alone fabricated a permissive verdict (the first enum
member, ``injection_suspected=False``) for refusals, content-filter stops, schema failures, provider errors and hit
caps. The layer now invents nothing: the answer is the schema's own ``demo_fallback()`` placeholder (its author
chooses the safe answer, e.g. "hold"), which must say ``injection_suspected=True``; a schema without one is refused
with ``LLMConfigError``. The result says it is a fallback so the API and the UI can label it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar, Literal, Self

import pytest

from bridge.llm.demo_fallback import (
    DEMO_FALLBACK_MODEL,
    DEMO_TEXT,
    DemoFallbackFlag,
    FallbackReason,
    check_fallback,
    fallback_output,
    fallback_result,
)
from bridge.llm.errors import LLMConfigError
from bridge.llm.types import BudgetStatus, LLMOutput, TokenUsage
from tests.unit.llm.schemas import Verdict


class NoHook(LLMOutput):
    verdict: Literal["clean", "hold"]
    reason: str


class Hooked(LLMOutput):
    verdict: Literal["clean", "hold"]

    @classmethod
    def demo_fallback(cls) -> Self:
        return cls(injection_suspected=True, verdict="hold")  # a classifier's safe answer: hold for a human


class WrongType(LLMOutput):
    verdict: str

    @classmethod
    def demo_fallback(cls) -> Verdict:
        return Verdict(injection_suspected=True, verdict="hold", reason="x")


class Permissive(LLMOutput):
    verdict: Literal["clean", "hold"]

    @classmethod
    def demo_fallback(cls) -> Self:
        return cls(injection_suspected=False, verdict="clean")


class NotCallable(LLMOutput):
    verdict: str
    demo_fallback: ClassVar[str] = "hold"


def test_a_schema_without_its_own_placeholder_is_refused() -> None:
    """Nothing is fabricated: no first enum member, no ``injection_suspected=False``."""
    with pytest.raises(LLMConfigError, match=r"NoHook needs a demo_fallback\(\) classmethod"):
        fallback_output(NoHook)
    with pytest.raises(LLMConfigError, match="NotCallable needs"):
        check_fallback(NotCallable)


def test_the_schemas_own_placeholder_is_the_answer() -> None:
    assert fallback_output(Hooked) == Hooked(injection_suspected=True, verdict="hold")
    assert fallback_output(Hooked) == fallback_output(Hooked)  # deterministic


def test_a_placeholder_must_be_its_own_schema() -> None:
    with pytest.raises(LLMConfigError, match=r"WrongType\.demo_fallback\(\) must return a WrongType"):
        fallback_output(WrongType)


def test_a_placeholder_must_flag_injection_suspected() -> None:
    """A fallback is never a clean verdict: code that holds on ``injection_suspected`` holds it."""
    with pytest.raises(LLMConfigError, match="injection_suspected=True"):
        fallback_output(Permissive)


def test_the_test_verdict_schema_holds() -> None:
    out = fallback_output(Verdict)
    assert (out.injection_suspected, out.verdict, out.reason) == (True, "hold", DEMO_TEXT)


def test_the_fallback_result_says_what_it_is() -> None:
    result = fallback_result(Verdict, reason=FallbackReason.PROVIDER_ERROR, trace_id="tr-1")
    assert result.demo_fallback is True
    assert result.fallback_reason == "provider_error"
    assert (result.model, result.cost_usd, result.attempts, result.usage) == (
        DEMO_FALLBACK_MODEL,
        Decimal(0),
        0,
        TokenUsage(),
    )
    assert (result.stop_reason, result.citations, result.trace_id, result.budget) == (
        "demo_fallback",
        (),
        "tr-1",
        BudgetStatus(),
    )
    assert result.parsed == fallback_output(Verdict)


def test_api_responses_carry_the_flag() -> None:
    class Suggestion(DemoFallbackFlag):
        text: str

    real = fallback_result(Verdict, reason=FallbackReason.KILL_SWITCH, trace_id="t")
    assert Suggestion(text="x", **DemoFallbackFlag.of(real)).model_dump() == {"demo_fallback": True, "text": "x"}
    assert Suggestion(text="y").demo_fallback is False
    assert "demo_fallback" in Suggestion.model_json_schema()["properties"]
