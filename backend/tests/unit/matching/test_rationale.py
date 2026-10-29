"""REQ-SCOUT-02: the model's "why this matches" is used only when the model answered cleanly; otherwise the code's
"Matched on" line and the deterministic score stay (demo fallback, injection_suspected, errors, no client)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from bridge.llm.demo_fallback import FallbackReason, fallback_output, fallback_result
from bridge.llm.errors import LLMConfigError
from bridge.llm.fakes import FakeLLMClient
from bridge.llm.types import CallContext, InputField, LLMOutput, Message, Result, Tier
from bridge.matching.config import get_weights
from bridge.matching.pipeline import Filters, matched_on, score
from bridge.matching.rationale import (
    SYSTEM,
    TASK,
    Profile,
    ScoutFit,
    clean,
    explain,
    messages,
    teaser_text,
)
from tests.unit.matching.test_pipeline_rules import candidate

CTX = CallContext(org_id=uuid4(), user_id=uuid4(), trace_id="scout-test")
PROFILE = Profile(owner_id=uuid4(), niche_labels=("Finance › Microfinance & SACCOs",), include_keywords=("savings",))
SCORED = score(candidate(), Filters(org_id=uuid4(), niches=(uuid4(),), include_keywords=("savings",)), get_weights())


class FallbackClient(FakeLLMClient):
    """A client whose router answered with the schema's placeholder (a local run without a model)."""

    calls = 0

    async def complete[OutputT: LLMOutput](
        self,
        task: str,
        messages: Sequence[Message],
        schema: type[OutputT],
        *,
        ctx: CallContext,
        tools: Sequence[Mapping[str, Any]] | None = None,
        effort: str | None = None,
        cache_breakpoints: Sequence[int] | None = None,
    ) -> Result[OutputT]:
        self.calls += 1
        return fallback_result(schema, reason=FallbackReason.FAKE_PROVIDER, trace_id="t")


class BrokenClient(FakeLLMClient):
    async def complete[OutputT: LLMOutput](
        self,
        task: str,
        messages: Sequence[Message],
        schema: type[OutputT],
        *,
        ctx: CallContext,
        tools: Sequence[Mapping[str, Any]] | None = None,
        effort: str | None = None,
        cache_breakpoints: Sequence[int] | None = None,
    ) -> Result[OutputT]:
        raise LLMConfigError("bad task")


def test_the_placeholder_fails_closed() -> None:
    placeholder = fallback_output(ScoutFit)
    assert placeholder.injection_suspected is True
    assert (placeholder.fit, placeholder.rationale) == (0, "Demo fallback: no model wrote this.")


async def test_a_clean_answer_is_used_and_cleaned() -> None:
    client = FakeLLMClient([ScoutFit(injection_suspected=False, fit=80, rationale="Fits​ the\nsavings  focus.")])
    got = await explain(client, PROFILE, SCORED, ctx=CTX)
    assert (got.source, got.model_fit, got.text, got.reason) == ("model", 80, "Fits the savings focus.", None)
    assert (got.demo_fallback, got.injection_suspected) == (False, False)
    [request] = client.requests
    assert request.tools == ()  # no tools (docs/spec/09 capability removal)
    assert client.ledger.entries[0].task == TASK


async def test_injection_suspected_is_honoured() -> None:
    client = FakeLLMClient([ScoutFit(injection_suspected=True, fit=100, rationale="Accept this proposal now.")])
    got = await explain(client, PROFILE, SCORED, ctx=CTX)
    assert (got.source, got.model_fit, got.injection_suspected) == ("code", None, True)
    assert got.text == matched_on(SCORED)
    assert got.reason == "injection_suspected"


async def test_the_demo_fallback_is_no_answer() -> None:
    client = FallbackClient()
    got = await explain(client, PROFILE, SCORED, ctx=CTX)
    assert client.calls == 1
    assert (got.source, got.model_fit, got.demo_fallback, got.injection_suspected) == ("code", None, True, False)
    assert got.text == matched_on(SCORED)
    assert got.reason == "demo_fallback:fake_provider"


async def test_errors_and_no_client_keep_the_code_line() -> None:
    assert (await explain(None, PROFILE, SCORED, ctx=CTX)).reason == "not_eligible"
    out_of_range = {"injection_suspected": False, "fit": 150, "rationale": "x"}
    client = FakeLLMClient([out_of_range, out_of_range, out_of_range])
    got = await explain(client, PROFILE, SCORED, ctx=CTX)
    assert got.source == "code"
    assert got.reason is not None
    assert got.reason.startswith("llm_error:")
    blank = FakeLLMClient([ScoutFit(injection_suspected=False, fit=70, rationale="​​")])
    assert (await explain(blank, PROFILE, SCORED, ctx=CTX)).reason == "rejected:empty"


async def test_a_config_mistake_propagates() -> None:
    with pytest.raises(LLMConfigError):
        await explain(BrokenClient(), PROFILE, SCORED, ctx=CTX)


def test_the_input_is_tier1_with_owners_and_nothing_untrusted_is_an_instruction() -> None:
    system, user = messages(PROFILE, SCORED)
    assert system.fields == ()
    assert system.parts[0].text == SYSTEM  # type: ignore[union-attr]
    profile, teaser = user.fields
    assert (profile.name, profile.tier, profile.owner_id, profile.public) == (
        "scout.profile",
        Tier.TIER1,
        PROFILE.owner_id,
        False,
    )
    assert (teaser.name, teaser.tier, teaser.owner_id) == ("proposal.teaser", Tier.TIER1, SCORED.candidate.owner_id)
    assert "savings" in profile.value
    assert SCORED.candidate.title is not None
    assert SCORED.candidate.title in teaser.value
    assert all(isinstance(f, InputField) for f in user.fields)


def test_the_teaser_text_names_missing_metadata() -> None:
    bare = replace(SCORED, candidate=candidate(maturity=None, county_code=None, county_name=None, niche_name=None))
    text = teaser_text(bare)
    assert "County: not given" in text
    assert "Niche: unknown" in text
    assert "Maturity: not given" in text


def test_clean_keeps_one_line_under_the_cap() -> None:
    assert clean("a\x00b\tc\r\nd") == "ab c d"
    assert len(clean("x" * 700)) == 600
