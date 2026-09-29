"""REQ-LLM-01 P7 (D-37): the deterministic fake behind the "demo fallback" label.

The fallback answer is built from the output schema alone (it reads no input, so it can leak nothing): the schema's
own ``demo_fallback()`` when it has one, else a value from its JSON schema. It is deterministic, always valid, and the
result says it is a fallback so the API and the UI can label it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

import pytest
from pydantic import BaseModel, Field

from bridge.llm import demo_fallback
from bridge.llm.demo_fallback import (
    DEMO_FALLBACK_MODEL,
    DEMO_TEXT,
    DemoFallbackFlag,
    FallbackReason,
    fallback_output,
    fallback_result,
)
from bridge.llm.errors import LLMConfigError
from bridge.llm.types import BudgetStatus, LLMOutput, TokenUsage
from tests.unit.llm.schemas import Verdict


class Point(BaseModel):
    x: int = Field(ge=3)
    label: str = Field(max_length=4)


class Rich(LLMOutput):
    kind: Literal["idea", "problem"]
    score: float = Field(ge=0.5, le=0.9)
    count: int = Field(gt=0)
    note: str | None
    points: list[Point] = Field(min_length=2)
    tags: list[str]
    words: str = Field(min_length=60)
    optional: str = "kept"


class Hooked(LLMOutput):
    verdict: Literal["clean", "hold"]

    @classmethod
    def demo_fallback(cls) -> Self:
        return cls(injection_suspected=False, verdict="hold")  # a classifier's safe answer: hold for a human


class WrongHook(LLMOutput):
    verdict: str

    @classmethod
    def demo_fallback(cls) -> Verdict:
        return Verdict(injection_suspected=False, verdict="clean", reason="x")


class Unfit(LLMOutput):
    code: str = Field(pattern=r"^[A-Z]{3}-\d{4}$")


def test_a_simple_schema_gets_false_the_first_member_and_the_demo_text() -> None:
    out = fallback_output(Verdict)
    assert out == Verdict(injection_suspected=False, verdict="clean", reason=DEMO_TEXT)


def test_nested_models_lists_bounds_and_optional_fields_are_filled_validly() -> None:
    out = fallback_output(Rich)
    assert out.injection_suspected is False
    assert (out.kind, out.score, out.count, out.note, out.tags, out.optional) == ("idea", 0.5, 1, None, [], "kept")
    assert out.points == [Point(x=3, label=DEMO_TEXT[:4])] * 2
    assert len(out.words) >= 60
    assert out.words.startswith(DEMO_TEXT)


def test_the_fallback_is_deterministic() -> None:
    assert fallback_output(Rich) == fallback_output(Rich)


def test_a_schema_hook_decides_its_own_fallback() -> None:
    assert fallback_output(Hooked).verdict == "hold"


def test_a_hook_must_return_its_own_schema() -> None:
    with pytest.raises(LLMConfigError, match=r"WrongHook\.demo_fallback"):
        fallback_output(WrongHook)


def test_a_schema_the_generic_value_does_not_fit_asks_for_a_hook() -> None:
    with pytest.raises(LLMConfigError, match=r"Unfit needs a demo_fallback\(\) classmethod"):
        fallback_output(Unfit)


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


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ({"const": "fixed"}, "fixed"),
        ({"allOf": [{"type": "integer", "minimum": 2}]}, 2),
        ({"oneOf": [{"type": "boolean"}, {"type": "string"}]}, False),
        ({"type": "integer", "exclusiveMaximum": 0}, -1),
        ({"type": "number", "minimum": 5, "maximum": 3}, 3.0),
        ({"type": "number", "exclusiveMinimum": 1}, 1.001),
        ({"type": "array", "minItems": 1, "items": {"type": "boolean"}}, [False]),
        ({"type": "array", "minItems": 1}, [None]),
        ({"type": ["string", "null"]}, None),
        ({"$ref": "#/$defs/Missing"}, None),
    ],
)
def test_generic_values_for_other_schema_shapes(node: dict[str, object], expected: object) -> None:
    assert demo_fallback._value(node, {}) == expected


def test_a_recursive_schema_ends_in_null() -> None:
    defs = {"Node": {"type": "object", "properties": {"next": {"$ref": "#/$defs/Node"}}, "required": ["next"]}}
    value = demo_fallback._value({"$ref": "#/$defs/Node"}, defs)
    depth = 0
    while isinstance(value, dict):
        value, depth = value["next"], depth + 1
    assert value is None
    assert depth <= demo_fallback.MAX_DEPTH
