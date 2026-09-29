"""REQ-LLM-01 P7 (D-37): ``OpenAICompatibleAdapter``, a free provider slot over plain httpx.

Driven through respx only (no network: the egress guard stays, AC-SEC-5). Checks the wire mapping (Chat Completions
body, bearer key, response format per slot), the reply mapping (text, stop reasons, usage), and that every failure is
an ``LLMProviderError`` naming the slot and status only: never the key, the provider's body or a chained cause.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr

from bridge.config import FreeSlot, ResponseFormat
from bridge.llm.adapter import ModelRequest, TextBlock, WireMessage
from bridge.llm.errors import LLMConfigError, LLMProviderError, LLMUnavailable
from bridge.llm.openai_adapter import MAX_REPLY_BYTES, OpenAICompatibleAdapter, to_body
from bridge.llm.registry import free_model_key
from bridge.llm.types import TokenUsage

BASE = "https://free-one.example/v1"
URL = f"{BASE}/chat/completions"
KEY = "sk-free-one-key-not-real-0123456789"
SECRET_BODY = "provider-internal-detail-that-must-not-leak"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"injection_suspected": {"type": "boolean"}, "verdict": {"type": "string"}},
    "required": ["injection_suspected", "verdict"],
    "additionalProperties": False,
}


def slot(response_format: ResponseFormat = "json_object", number: int = 1) -> FreeSlot:
    return FreeSlot(number, BASE, SecretStr(KEY), "vendor/demo-model-8b", 20, response_format)


def request(model: str | None = None, **overrides: Any) -> ModelRequest:
    values: dict[str, Any] = {
        "model": model or free_model_key(slot()),
        "max_tokens": 256,
        "effort": None,
        "system": (TextBlock("You screen teasers.", cache=True), TextBlock("Nonce line.")),
        "messages": (
            WireMessage("user", (TextBlock("Screen this:"), TextBlock("<submission>text</submission>"))),
            WireMessage("assistant", (TextBlock("{}"),)),
            WireMessage("user", (TextBlock("Again."),)),
        ),
        "output_schema": SCHEMA,
        "native_format": False,
    }
    values.update(overrides)
    return ModelRequest(**values)


def reply(content: Any = '{"injection_suspected": false, "verdict": "clean"}', **choice: Any) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    message.update(choice.pop("message", {}))
    return {
        "id": "chatcmpl-provider-id",
        "object": "chat.completion",
        "model": "vendor/demo-model-8b-2026",
        "choices": [{"index": 0, "message": message, "finish_reason": choice.pop("finish_reason", "stop")}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 9, "prompt_tokens_details": {"cached_tokens": 20}},
    }


def adapter(response_format: ResponseFormat = "json_object") -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(slot(response_format), timeout_seconds=5.0)


def assert_quiet(error: BaseException) -> None:
    """No key, provider body or chained provider exception in an error (it may reach a log or the dead letters)."""
    for secret in (KEY, SECRET_BODY, "chatcmpl"):
        assert secret not in str(error)
        assert secret not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__ is True  # no provider exception in a traceback


async def create_expecting_error(response: httpx.Response | Exception) -> LLMProviderError:
    with respx.mock(assert_all_called=True) as router:
        if isinstance(response, Exception):
            router.post(URL).mock(side_effect=response)
        else:
            router.post(URL).mock(return_value=response)
        with pytest.raises(LLMProviderError) as info:
            await adapter().create(request())
    assert_quiet(info.value)
    assert "free1" in str(info.value)
    return info.value


# ------------------------------------------------------------------------------------------------------ the wire


async def test_a_call_posts_chat_completions_with_the_bearer_key_and_the_slot_model() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(URL).mock(return_value=httpx.Response(200, json=reply()))
        response = await adapter().create(request())
    sent = route.calls.last.request
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    assert sent.headers["content-type"] == "application/json"
    body = json.loads(sent.content)
    assert body == {
        "model": "vendor/demo-model-8b",  # the provider's id, not the ledger key
        "messages": [
            {"role": "system", "content": "You screen teasers.\n\nNonce line."},
            {"role": "user", "content": "Screen this:\n\n<submission>text</submission>"},
            {"role": "assistant", "content": "{}"},
            {"role": "user", "content": "Again."},
        ],
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
    }
    assert response.text == '{"injection_suspected": false, "verdict": "clean"}'
    assert response.stop_reason == "end_turn"
    assert response.model == free_model_key(slot())  # the ledger key, never the provider's echo
    assert response.usage == TokenUsage(input_tokens=100, output_tokens=9, cache_read_input_tokens=20)
    assert response.response_id is None  # no provider text is carried
    assert response.citations == ()


@pytest.mark.parametrize(
    ("response_format", "expected"),
    [
        ("json_object", {"type": "json_object"}),
        ("json_schema", {"type": "json_schema", "json_schema": {"name": "output", "schema": SCHEMA}}),
        ("none", None),
    ],
)
def test_the_response_format_follows_the_slot(response_format: ResponseFormat, expected: Any) -> None:
    body = to_body(request(), slot(response_format))
    assert body.get("response_format") == expected
    assert "tools" not in body
    assert "tool_choice" not in body  # never forced (docs/spec/08)


def test_an_empty_system_prompt_sends_no_system_message() -> None:
    body = to_body(request(system=()), slot())
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]


async def test_a_request_for_another_model_or_with_tools_is_a_routing_bug() -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.post(URL)
        with pytest.raises(LLMConfigError, match="another model"):
            await adapter().create(request(model="free2:vendor/demo-model-8b"))
        with pytest.raises(LLMConfigError, match="no tools"):
            await adapter().create(request(tools=({"type": "web_search_20260209"},)))
    assert not route.called


async def test_redirects_are_not_followed() -> None:
    """A redirect could carry the bearer key elsewhere: it is an error, never followed."""
    with respx.mock(assert_all_called=False) as router:
        first = router.post(URL).mock(
            return_value=httpx.Response(307, headers={"location": "https://elsewhere.example/x"})
        )
        other = router.post("https://elsewhere.example/x")
        with pytest.raises(LLMProviderError) as info:
            await adapter().create(request())
    assert first.called
    assert not other.called
    assert info.value.transient is False
    assert_quiet(info.value)


# --------------------------------------------------------------------------------------------------- the reply


@pytest.mark.parametrize(
    ("finish_reason", "stop"),
    [
        ("stop", "end_turn"),
        ("length", "max_tokens"),
        ("content_filter", "refusal"),
        ("tool_calls", "tool_use"),
        ("function_call", "tool_use"),
        (None, "unknown"),
        (f"weird {SECRET_BODY}", "unknown"),  # a provider's own text never passes through
    ],
)
async def test_finish_reasons_map_to_stop_reasons(finish_reason: str | None, stop: str) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(URL).mock(return_value=httpx.Response(200, json=reply(finish_reason=finish_reason)))
        assert (await adapter().create(request())).stop_reason == stop


async def test_a_refusal_field_is_a_refusal() -> None:
    body = reply(content=None, message={"refusal": f"I cannot help with that {SECRET_BODY}"})
    with respx.mock(assert_all_called=True) as router:
        router.post(URL).mock(return_value=httpx.Response(200, json=body))
        response = await adapter().create(request())
    assert (response.stop_reason, response.text) == ("refusal", "")
    assert response.refusal_category is None


async def test_content_parts_are_joined_and_missing_usage_counts_zero() -> None:
    body = reply(content=[{"type": "text", "text": '{"a": '}, {"type": "text", "text": "1}"}, {"type": "image"}])
    del body["usage"]
    with respx.mock(assert_all_called=True) as router:
        router.post(URL).mock(return_value=httpx.Response(200, json=body))
        response = await adapter().create(request())
    assert response.text == '{"a": 1}'
    assert response.usage == TokenUsage()


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": -5, "completion_tokens": "9"},
        {"prompt_tokens": True, "completion_tokens": None, "prompt_tokens_details": {"cached_tokens": 99}},
        {"prompt_tokens": 10**12, "completion_tokens": 10**12, "prompt_tokens_details": "x"},
    ],
)
async def test_implausible_usage_is_bounded(usage: dict[str, Any]) -> None:
    body = {**reply(), "usage": usage}
    with respx.mock(assert_all_called=True) as router:
        router.post(URL).mock(return_value=httpx.Response(200, json=body))
        got = (await adapter().create(request())).usage
    for count in (got.input_tokens, got.output_tokens, got.cache_read_input_tokens):
        assert 0 <= count <= 10_000_000


# ------------------------------------------------------------------------------------------------------ errors


@pytest.mark.parametrize(
    ("status", "transient"),
    [
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (408, True),
        (409, True),
        (429, True),
        (500, True),
        (503, True),
    ],
)
async def test_http_errors_carry_the_status_only(status: int, transient: bool) -> None:
    body = {"error": {"message": f"bad key {KEY} {SECRET_BODY}"}}
    error = await create_expecting_error(httpx.Response(status, json=body))
    assert (error.status_code, error.transient) == (status, transient)
    assert f"HTTP {status}" in str(error)


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError(f"cannot connect {SECRET_BODY}"),
        httpx.ReadTimeout(f"slow {SECRET_BODY}"),
        httpx.RemoteProtocolError(f"broken {SECRET_BODY}"),
    ],
)
async def test_transport_errors_are_transient(exc: Exception) -> None:
    error = await create_expecting_error(exc)
    assert error.transient is True
    assert error.status_code is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=f"not json {SECRET_BODY}".encode()),
        httpx.Response(200, json=[SECRET_BODY]),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": "x"}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": 7}, "finish_reason": "stop"}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": [SECRET_BODY]}, "finish_reason": "stop"}]}),
    ],
)
async def test_a_malformed_reply_is_a_quiet_provider_error(response: httpx.Response) -> None:
    error = await create_expecting_error(response)
    assert error.transient is False
    assert "malformed" in str(error)


async def test_an_oversized_reply_is_refused() -> None:
    big = httpx.Response(200, content=b"x" * (MAX_REPLY_BYTES + 1))
    error = await create_expecting_error(big)
    assert "oversized" in str(error)


# ------------------------------------------------------------------------------------------- key and batches


def test_the_key_never_shows() -> None:
    a = adapter()
    assert repr(a) == "OpenAICompatibleAdapter(slot=free1)"
    assert KEY not in repr(a)
    assert KEY not in str(a)
    assert KEY not in repr(slot())


async def test_free_slots_have_no_batch_api() -> None:
    a = adapter()
    with pytest.raises(LLMUnavailable, match="no batch API"):
        await a.batch_create({"a": request()})
    with pytest.raises(LLMUnavailable, match="no batch API"):
        await a.batch_state("b")
    with pytest.raises(LLMUnavailable, match="no batch API"):
        await a.batch_results("b")


async def test_an_injected_client_is_used() -> None:
    async with httpx.AsyncClient() as client:
        a = OpenAICompatibleAdapter(slot(), timeout_seconds=5.0, http_client=client)
        with respx.mock(assert_all_called=True) as router:
            route = router.post(URL).mock(return_value=httpx.Response(200, json=reply()))
            await a.create(request())
    assert route.called
