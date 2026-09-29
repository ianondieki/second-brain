"""The answer behind the "demo fallback" label (D-37; REQ-LLM-01 P7): it fails closed.

When a local run cannot or may not reach a model (the fake provider, no free slot or key, unverified prices, data that
is not seeded demo data, a hit cap, the kill switch, a failed or refused call), the router answers with
``fallback_result``: the output schema's own ``demo_fallback()`` classmethod, a fixed placeholder its author chose as
the safe answer (a classifier holds for a human; a writer returns ``DEMO_TEXT``). The layer invents nothing (security
review P7, MAJOR 2: a value built from the schema picked the first enum member and ``injection_suspected=False``, a
permissive verdict for refusals, content-filter stops, schema failures, provider errors and hit caps): a schema
without the classmethod is refused with ``LLMConfigError`` (the router checks it before routing on local runs), and
the placeholder must say ``injection_suspected=True``. It reads no input, so it can leak nothing, and it is the same
every time. The result carries ``demo_fallback=True`` and the reason; API responses that return LLM output embed
``DemoFallbackFlag`` so the UI shows a small "demo fallback" label. The fallback runs in dev and test only
(``Settings.llm_demo_fallback``); staging and production raise the typed error instead.

A fallback answer is a placeholder, never a judgement: code that decides on a model's output treats
``demo_fallback`` as "no answer".
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from bridge.llm.errors import LLMConfigError
from bridge.llm.types import LLMOutput, Result, TokenUsage

DEMO_TEXT = "Demo fallback: no model wrote this."  # [[COPY-REVIEW]] for placeholders' text fields
DEMO_FALLBACK_MODEL = "demo-fallback"  # Result.model of a fallback answer (not a provider's model)
DEMO_STOP_REASON = "demo_fallback"


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


def check_fallback(schema: type[LLMOutput]) -> None:
    """``LLMConfigError`` unless ``schema`` brings its own ``demo_fallback()`` placeholder (a code mistake)."""
    if not callable(getattr(schema, "demo_fallback", None)):
        raise LLMConfigError(
            f"{schema.__name__} needs a demo_fallback() classmethod returning a safe placeholder with"
            " injection_suspected=True (local runs answer a failed call with it; the layer invents no verdict)"
        )


def fallback_output[OutputT: LLMOutput](schema: type[OutputT]) -> OutputT:
    """The schema's own placeholder; ``LLMConfigError`` when it has none, returns another type, or does not flag
    ``injection_suspected``."""
    check_fallback(schema)
    output = schema.demo_fallback()  # type: ignore[attr-defined]
    if not isinstance(output, schema):
        raise LLMConfigError(f"{schema.__name__}.demo_fallback() must return a {schema.__name__}")
    if output.injection_suspected is not True:
        raise LLMConfigError(f"{schema.__name__}.demo_fallback() must set injection_suspected=True (fail closed)")
    return output


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
