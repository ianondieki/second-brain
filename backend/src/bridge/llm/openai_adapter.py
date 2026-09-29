"""``OpenAICompatibleAdapter``: one free provider slot over plain ``httpx``, no SDK (D-37; REQ-LLM-01 P7).

Wire (the Chat Completions shape most free providers serve): ``POST {base_url}/chat/completions`` with
``Authorization: Bearer <key>``; the system blocks as one system message and each turn's text blocks joined; the
request's ``max_tokens``; and the slot's ``response_format`` (``json_object`` by default, ``json_schema`` with the
output schema, or ``none``). The schema is always in the system prompt as well (a slot's registry sets
``json_schema_format: false``), and the service validates the reply as for every provider. No effort, no tools, no
prompt caching (breakpoints are dropped) and no batch API: ``batch_*`` raise ``LLMUnavailable`` (the router answers a
batch with the deterministic fake, ``bridge.llm.routing``).

Reply: ``choices[0].message.content`` (a string or text parts); ``finish_reason`` ``stop`` is ``end_turn``,
``length`` is ``max_tokens``, ``content_filter`` or a ``message.refusal`` is ``refusal``, a tool call is ``tool_use``
and anything else is ``unknown`` (the service treats the last two as unsupported stops), so no provider text becomes
a stop reason. Usage: ``prompt_tokens`` less its cached part are input tokens, the cached part cache reads,
``completion_tokens`` output tokens, each bounded (free slots cost 0; the counts only reach the ledger).

Fail closed and quiet: a transport error, a non-2xx status (a redirect included: never followed, it could carry the
key elsewhere), an oversized or a malformed body each raise ``LLMProviderError`` naming the slot and the status only,
``from None``. The provider's body and the key never reach a log line, an error or a traceback; ``repr`` names the
slot only; slot URLs carry no credentials or query (``bridge.config.free_slot_url_problem``). No retries: one attempt
is one request and one ledger row, counted against the slot's daily cap.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from bridge.config import FreeSlot
from bridge.llm.adapter import BatchItemError, BatchState, ModelRequest, ModelResponse, TextBlock
from bridge.llm.errors import LLMConfigError, LLMProviderError, LLMUnavailable
from bridge.llm.registry import free_model_key
from bridge.llm.types import TokenUsage

CHAT_PATH = "/chat/completions"
MAX_REPLY_BYTES = 2_000_000  # a reply is a few KB; anything this large is refused unread past the bound
MAX_TOKEN_COUNT = 10_000_000  # usage counts are bounded before they reach the ledger's integer columns
TRANSIENT_STATUSES = frozenset({408, 409, 425, 429})
STOP_REASONS = {
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "refusal",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
}


class _Malformed(Exception):
    """The reply is not the Chat Completions shape (never carries the body)."""


def _joined(blocks: Sequence[TextBlock]) -> str:
    return "\n\n".join(block.text for block in blocks)


def to_body(request: ModelRequest, slot: FreeSlot) -> dict[str, Any]:
    """The Chat Completions body of ``request`` for ``slot`` (its provider model id, its response format)."""
    messages: list[dict[str, str]] = []
    if request.system:
        messages.append({"role": "system", "content": _joined(request.system)})
    messages.extend({"role": m.role, "content": _joined(m.blocks)} for m in request.messages)
    body: dict[str, Any] = {"model": slot.model, "messages": messages, "max_tokens": request.max_tokens}
    if slot.response_format == "json_object":
        body["response_format"] = {"type": "json_object"}
    elif slot.response_format == "json_schema":
        schema = {"name": "output", "schema": dict(request.output_schema)}
        body["response_format"] = {"type": "json_schema", "json_schema": schema}
    return body


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return min(max(value, 0), MAX_TOKEN_COUNT)


def _usage(raw: Any) -> TokenUsage:
    usage = raw if isinstance(raw, Mapping) else {}
    details = usage.get("prompt_tokens_details")
    prompt = _count(usage.get("prompt_tokens"))
    cached = min(_count(details.get("cached_tokens")) if isinstance(details, Mapping) else 0, prompt)
    return TokenUsage(
        input_tokens=prompt - cached,
        output_tokens=_count(usage.get("completion_tokens")),
        cache_read_input_tokens=cached,
    )


def _content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts = []
        for part in value:
            if not isinstance(part, Mapping):
                raise _Malformed
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
        return "".join(texts)
    raise _Malformed


def from_reply(data: Any, model_key: str) -> ModelResponse:
    """The ``ModelResponse`` of a Chat Completions reply; raises ``_Malformed`` for any other shape."""
    if not isinstance(data, Mapping):
        raise _Malformed
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise _Malformed
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise _Malformed
    text = _content(message.get("content"))
    refusal = message.get("refusal")
    finish = choices[0].get("finish_reason")
    if isinstance(refusal, str) and refusal.strip():
        stop = "refusal"
    else:
        stop = STOP_REASONS.get(finish, "unknown") if isinstance(finish, str) else "unknown"
    return ModelResponse(text=text, stop_reason=stop, usage=_usage(data.get("usage")), model=model_key)


class OpenAICompatibleAdapter:
    """``ModelAdapter`` for one free slot. ``http_client`` is for tests (respx); the default client never follows
    redirects and times out after ``timeout_seconds``."""

    name = "openai_compatible"

    def __init__(self, slot: FreeSlot, *, timeout_seconds: float, http_client: httpx.AsyncClient | None = None) -> None:
        self._slot = slot
        self._key = free_model_key(slot)
        self._url = slot.base_url.rstrip("/") + CHAT_PATH
        self._timeout = timeout_seconds
        self._http = http_client

    def __repr__(self) -> str:
        return f"OpenAICompatibleAdapter(slot={self._slot.name})"

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
        return self._http

    def _error(self, what: str, *, transient: bool, status: int | None = None) -> LLMProviderError:
        return LLMProviderError(f"free provider {self._slot.name} {what}", transient=transient, status_code=status)

    async def create(self, request: ModelRequest) -> ModelResponse:
        if request.model != self._key:
            raise LLMConfigError(f"a request for another model reached free slot {self._slot.name}")
        if request.tools:
            raise LLMConfigError("free provider slots take no tools")
        body = to_body(request, self._slot)
        headers = {"Authorization": f"Bearer {self._slot.api_key.get_secret_value()}"}
        try:
            raw = await self._post(body, headers)
        except LLMProviderError:
            raise
        except httpx.TimeoutException:
            raise self._error("timed out", transient=True) from None
        except httpx.HTTPError as exc:
            raise self._error(f"unreachable ({type(exc).__name__})", transient=True) from None
        try:
            return from_reply(json.loads(raw), self._key)
        except (_Malformed, ValueError, RecursionError):  # RecursionError: nesting deeper than the parser's limit
            raise self._error("sent a malformed reply", transient=False) from None

    async def _post(self, body: Mapping[str, Any], headers: Mapping[str, str]) -> bytes:
        async with self._client().stream("POST", self._url, json=body, headers=headers) as response:
            status = response.status_code
            if not 200 <= status < 300:  # the body is never read: it may quote the request or the key
                transient = status in TRANSIENT_STATUSES or status >= 500
                raise self._error(f"answered HTTP {status}", transient=transient, status=status)
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_REPLY_BYTES:
                    raise self._error("sent an oversized reply", transient=False, status=status)
                chunks.append(chunk)
        return b"".join(chunks)

    async def batch_create(self, requests: Mapping[str, ModelRequest]) -> str:
        raise LLMUnavailable("free providers have no batch API")

    async def batch_state(self, batch_id: str) -> BatchState:
        raise LLMUnavailable("free providers have no batch API")

    async def batch_results(self, batch_id: str) -> dict[str, ModelResponse | BatchItemError]:
        raise LLMUnavailable("free providers have no batch API")
