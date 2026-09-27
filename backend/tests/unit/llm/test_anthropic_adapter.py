"""REQ-LLM-01: AnthropicAdapter over synthetic cassettes (the real SDK parses; nothing leaves the machine; D-18).

Wire rules checked here: native JSON-schema output (strict), explicit effort, cache breakpoints as cache_control,
never a tool_choice, no key -> LLMUnavailable at call time (never at import or start-up).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import SecretStr

from bridge.llm.adapter import BatchItemError, BatchState, ModelRequest, ModelResponse, TextBlock, WireMessage
from bridge.llm.anthropic_adapter import AnthropicAdapter, adapter_from_settings
from bridge.llm.cassettes import CassetteError, CassettePlayer, load
from bridge.llm.errors import LLMProviderError, LLMUnavailable
from bridge.llm.types import Citation, TokenUsage
from tests.unit.llm.helpers import real_registry, settings
from tests.unit.llm.schemas import CASSETTES, Verdict, player


def request(**overrides: Any) -> ModelRequest:
    values: dict[str, Any] = {
        "model": "claude-haiku-4-5",
        "max_tokens": 1024,
        "effort": None,
        "system": (TextBlock("You classify teasers.", cache=True), TextBlock("The nonce for this request is abc.")),
        "messages": (WireMessage("user", (TextBlock("Classify:"), TextBlock("<submission ...>"))),),
        "output_schema": Verdict.model_json_schema(),
    }
    values.update(overrides)
    return ModelRequest(**values)


def test_every_cassette_is_synthetic() -> None:
    paths = sorted(CASSETTES.glob("*.json"))
    assert paths
    for path in paths:
        assert json.loads(path.read_text(encoding="utf-8"))["synthetic"] is True, path.name
        assert load(path)


def test_a_cassette_not_marked_synthetic_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "recorded.json"
    path.write_text(json.dumps({"interactions": []}), encoding="utf-8")
    with pytest.raises(CassetteError, match="synthetic"):
        load(path)


async def test_request_uses_json_schema_output_and_never_tool_choice() -> None:
    tape = player("messages_verdict_ok")
    await tape.adapter().create(request())
    body = tape.requests[0].json()
    assert tape.requests[0].path == "/v1/messages"
    assert body["model"] == "claude-haiku-4-5"
    assert body["max_tokens"] == 1024
    assert body["system"][0] == {
        "type": "text",
        "text": "You classify teasers.",
        "cache_control": {"type": "ephemeral"},
    }
    assert "cache_control" not in body["system"][1]
    assert body["messages"][0]["role"] == "user"
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert "injection_suspected" in fmt["schema"]["required"]
    assert fmt["schema"]["properties"]["injection_suspected"]["type"] == "boolean"
    assert "effort" not in body["output_config"]  # this model has no effort parameter
    assert "tool_choice" not in body
    assert "tools" not in body
    assert tape.exhausted


async def test_effort_and_tools_are_sent_when_given() -> None:
    tape = player("messages_verdict_ok")
    tool = {"type": "web_search_20260209", "name": "web_search", "allowed_domains": ["example.org"]}
    await tape.adapter().create(request(model="claude-sonnet-5", effort="medium", tools=(tool,)))
    body = tape.requests[0].json()
    assert body["output_config"]["effort"] == "medium"
    assert body["tools"] == [tool]
    assert "tool_choice" not in body


async def test_response_is_parsed_with_cache_usage() -> None:
    response = await player("messages_verdict_ok").adapter().create(request())
    assert response.stop_reason == "end_turn"
    assert response.model == "claude-haiku-4-5"
    assert response.response_id == "msg_syn_ok_01"
    assert Verdict.model_validate_json(response.text).verdict == "clean"
    assert response.usage == TokenUsage(812, 31, 600, 300, 100)
    assert response.refusal_category is None


async def test_refusal_carries_its_category() -> None:
    response = await player("messages_refusal_twice").adapter().create(request())
    assert response.stop_reason == "refusal"
    assert response.refusal_category == "cyber"
    assert response.text == ""


async def test_citations_are_collected() -> None:
    response = await player("messages_with_citations").adapter().create(request())
    assert response.citations == (
        Citation("char_location", "Kenya grid data", "Grid report"),
        Citation("web_search_result_location", "tariffs rose", "https://example.org/t"),
    )
    assert Verdict.model_validate_json(response.text).reason == "Cited."


@pytest.mark.parametrize(
    ("name", "status", "transient"), [("messages_overloaded", 529, True), ("messages_bad_request", 400, False)]
)
async def test_http_errors_become_provider_errors(name: str, status: int, transient: bool) -> None:
    with pytest.raises(LLMProviderError) as info:
        await player(name).adapter().create(request())
    assert info.value.status_code == status
    assert info.value.transient is transient
    assert "provider detail" not in str(info.value)  # provider bodies are not copied


async def test_connection_errors_are_transient() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(refuse))
    adapter = AnthropicAdapter(api_key=SecretStr("k"), timeout_seconds=1, max_retries=0, http_client=client)
    with pytest.raises(LLMProviderError) as info:
        await adapter.create(request())
    assert info.value.transient
    assert info.value.status_code is None


async def test_other_sdk_errors_are_permanent(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = player().adapter()

    async def boom(**_: Any) -> None:
        raise anthropic.AnthropicError("local problem")

    monkeypatch.setattr(adapter._client().messages, "create", boom)
    with pytest.raises(LLMProviderError, match="client error") as info:
        await adapter.create(request())
    assert not info.value.transient


async def test_cassette_mismatch_and_exhaustion_fail_loudly() -> None:
    tape = player("batch_nightly")  # expects POST /v1/messages/batches first
    with pytest.raises(LLMProviderError) as info:
        await tape.adapter().create(request())
    assert isinstance(info.value.__cause__, anthropic.APIConnectionError)
    assert isinstance(info.value.__cause__.__cause__, CassetteError)
    empty = CassettePlayer([])
    with pytest.raises(LLMProviderError):
        await empty.adapter().create(request())
    assert empty.exhausted


async def test_no_key_fails_closed_at_call_time() -> None:
    adapter = adapter_from_settings(settings(anthropic_api_key=None), real_registry())
    assert "configured=False" in repr(adapter)
    for call in (
        adapter.create(request()),
        adapter.batch_create({"a": request()}),
        adapter.batch_state("b"),
        adapter.batch_results("b"),
    ):
        with pytest.raises(LLMUnavailable):
            await call
    blank = AnthropicAdapter(api_key=SecretStr("  "), timeout_seconds=1, max_retries=0)
    with pytest.raises(LLMUnavailable):
        await blank.create(request())


async def test_batch_submit_poll_and_results() -> None:
    tape = player("batch_nightly")
    adapter = tape.adapter()
    batch_id = await adapter.batch_create({"item-ok": request(), "item-refused": request()})
    assert batch_id == "msgbatch_syn_01"
    body = tape.requests[0].json()
    assert [item["custom_id"] for item in body["requests"]] == ["item-ok", "item-refused"]
    assert body["requests"][0]["params"]["output_config"]["format"]["type"] == "json_schema"
    assert await adapter.batch_state(batch_id) is BatchState.IN_PROGRESS
    assert await adapter.batch_state(batch_id) is BatchState.ENDED
    results = await adapter.batch_results(batch_id)
    ok = results["item-ok"]
    assert isinstance(ok, ModelResponse)
    assert ok.stop_reason == "end_turn"
    refused = results["item-refused"]
    assert isinstance(refused, ModelResponse)
    assert refused.refusal_category == "cyber"
    assert results["item-errored"] == BatchItemError("errored", "invalid_request_error")
    assert results["item-expired"] == BatchItemError("expired", "expired")
    assert tape.exhausted


@pytest.mark.parametrize("method", ["batch_create", "batch_state", "batch_results"])
async def test_batch_http_errors_become_provider_errors(method: str) -> None:
    adapter = player("messages_overloaded").adapter()  # every batch path mismatches -> connection error
    args: dict[str, Any] = {"batch_create": ({"a": request()},), "batch_state": ("b",), "batch_results": ("b",)}
    with pytest.raises(LLMProviderError):
        await getattr(adapter, method)(*args[method])


def test_request_counts_prompt_characters() -> None:
    assert request().text_chars == len("You classify teasers.") + len("The nonce for this request is abc.") + len(
        "Classify:"
    ) + len("<submission ...>")
