"""The deterministic fake behind the "demo fallback" label (D-37; REQ-LLM-01 P7).

When a local run cannot or may not reach a model (the fake provider, no free slot or key, unverified prices, data that
is not seeded demo data, a hit cap, the kill switch, a failed or refused call), the router answers with
``fallback_result``: the schema's own ``demo_fallback()`` classmethod when it defines one, else a value built from its
JSON schema (``false``, the first enum member, the lowest allowed number, the fewest items, a short fixed text). It
reads no input, so it can leak nothing, and it is the same every time. The result carries ``demo_fallback=True`` and
the reason; API responses that return LLM output embed ``DemoFallbackFlag`` so the UI shows a small "demo fallback"
label. The demo fallback runs in dev and test only (``Settings.llm_demo_fallback``); staging and production raise.

A fallback answer is a placeholder, never a judgement. Code that decides on a model's output (plain code decides, the
model only words or scores) treats ``demo_fallback`` as "no answer", or gives its schema a ``demo_fallback()`` that
returns the safe answer (a classifier: hold for a human).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from bridge.llm.errors import LLMConfigError
from bridge.llm.types import LLMOutput, Result, TokenUsage

DEMO_TEXT = "Demo fallback: no model wrote this."  # [[COPY-REVIEW]]
DEMO_FALLBACK_MODEL = "demo-fallback"  # Result.model of a fallback answer (not a provider's model)
DEMO_STOP_REASON = "demo_fallback"
MAX_DEPTH = 16  # nested schemas deeper than this get null (a recursive model would never end)


class FallbackReason(StrEnum):
    """Why an answer is the fallback (``Result.fallback_reason``; logged as ``llm.demo_fallback``)."""

    FAKE_PROVIDER = "fake_provider"  # LLM_PROVIDER=fake, or unset with no free slot
    NO_FREE_SLOT = "no_free_slot"  # the task lists no configured free slot
    NO_KEY = "no_key"  # LLM_PROVIDER=anthropic without ANTHROPIC_API_KEY
    PRICES_UNVERIFIED = "prices_unverified"  # ai/models.yaml prices are not marked verified
    NOT_DEMO_DATA = "not_demo_data"  # D-37: only seeded demo data goes to a free provider
    REQUEST_CAP = "request_cap"  # every slot the task lists has used today's requests
    BUDGET = "budget"  # a spend cap (daily, prototype total or the subject's month)
    KILL_SWITCH = "kill_switch"
    UNAVAILABLE = "unavailable"  # the provider cannot serve the call
    PROVIDER_ERROR = "provider_error"  # network, HTTP or a malformed reply
    CALL_FAILED = "call_failed"  # refused, truncated, schema failure or an unsupported stop, retries spent
    TOOLS_UNSUPPORTED = "tools_unsupported"  # free providers take no tools
    NO_BATCH_API = "no_batch_api"  # free providers and the fake have no batch API


class DemoFallbackFlag(BaseModel):
    """Base of API responses that return LLM output: the UI shows a small "demo fallback" label when true."""

    demo_fallback: bool = Field(default=False, description="True when no model wrote this (a local demo fallback).")

    @classmethod
    def of(cls, result: Result[Any]) -> dict[str, bool]:
        """The flag of ``result``, to pass into a response model (``Response(**DemoFallbackFlag.of(result), ...)``)."""
        return {"demo_fallback": result.demo_fallback}


def _ref(node: Mapping[str, Any], defs: Mapping[str, Any]) -> Mapping[str, Any]:
    name = str(node["$ref"]).rsplit("/", 1)[-1]
    target = defs.get(name)
    return target if isinstance(target, Mapping) else {}


def _number(node: Mapping[str, Any], integer: bool) -> int | float:
    step: int | float = 1 if integer else 0.001
    value: int | float = 0
    if "minimum" in node:
        value = node["minimum"]
    elif "exclusiveMinimum" in node:
        value = node["exclusiveMinimum"] + step
    if "maximum" in node and value > node["maximum"]:
        value = node["maximum"]
    elif "exclusiveMaximum" in node and value >= node["exclusiveMaximum"]:
        value = node["exclusiveMaximum"] - step
    return int(value) if integer else float(value)


def _text(node: Mapping[str, Any]) -> str:
    text = DEMO_TEXT
    shortest = node.get("minLength", 0)
    while len(text) < shortest:
        text = f"{text} {DEMO_TEXT}"
    longest = node.get("maxLength")
    return text[:longest] if isinstance(longest, int) else text


def _value(node: Mapping[str, Any], defs: Mapping[str, Any], depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        return None
    if "$ref" in node:
        return _value(_ref(node, defs), defs, depth + 1)
    if "const" in node:
        return node["const"]
    if node.get("enum"):
        return node["enum"][0]
    for key in ("anyOf", "oneOf"):
        branches = [b for b in node.get(key, ()) if isinstance(b, Mapping)]
        if branches:
            if any(b.get("type") == "null" for b in branches):
                return None
            return _value(branches[0], defs, depth + 1)
    if node.get("allOf"):
        return _value(node["allOf"][0], defs, depth + 1)
    kind = node.get("type")
    if kind == "boolean":
        return False
    if kind in ("integer", "number"):
        return _number(node, kind == "integer")
    if kind == "string":
        return _text(node)
    if kind == "array":
        found = node.get("items")
        items: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
        return [_value(items, defs, depth + 1) for _ in range(int(node.get("minItems", 0)))]
    if kind == "object":
        properties = node.get("properties") or {}
        required = node.get("required", [])
        return {name: _value(properties[name], defs, depth + 1) for name in required if name in properties}
    return None


def fallback_output[OutputT: LLMOutput](schema: type[OutputT]) -> OutputT:
    """The fallback answer for ``schema``; ``LLMConfigError`` when neither its hook nor the generic value fits (a code
    bug: give the schema a ``demo_fallback()`` classmethod)."""
    hook = getattr(schema, "demo_fallback", None)
    if callable(hook):
        output = hook()
        if not isinstance(output, schema):
            raise LLMConfigError(f"{schema.__name__}.demo_fallback() must return a {schema.__name__}")
        return output
    raw = schema.model_json_schema()
    try:
        return schema.model_validate(_value(raw, raw.get("$defs", {})))
    except ValidationError:
        raise LLMConfigError(
            f"{schema.__name__} needs a demo_fallback() classmethod: the generic fallback does not fit its schema"
        ) from None


def fallback_result[OutputT: LLMOutput](
    schema: type[OutputT], *, reason: FallbackReason, trace_id: str
) -> Result[OutputT]:
    """A ``Result`` holding the fallback answer, flagged and costing nothing."""
    return Result(
        parsed=fallback_output(schema),
        stop_reason=DEMO_STOP_REASON,
        usage=TokenUsage(),
        citations=(),
        model=DEMO_FALLBACK_MODEL,
        cost_usd=Decimal(0),
        attempts=0,
        trace_id=trace_id,
        demo_fallback=True,
        fallback_reason=reason.value,
    )
