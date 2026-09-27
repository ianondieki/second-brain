"""``AnthropicAdapter``: the single runtime adapter, on the official ``anthropic`` SDK (ADR-005 decision 1).

Wire rules (docs/spec/08 LLM layer): structured output through the native JSON-schema format
(``output_config.format``, strict schema from ``anthropic.transform_schema``); effort sent explicitly in
``output_config.effort`` whenever the model has one; ``tool_choice`` is never set (the API default is ``auto``; a
forced ``tool_choice`` is refused by newer models); prompt-cache breakpoints as ``cache_control`` on text blocks.

Fail closed: without ``ANTHROPIC_API_KEY`` the adapter still builds (the app starts in dev and test), and every call
raises ``LLMUnavailable`` before any client exists. The key is passed explicitly, so the SDK never falls back to
environment or profile credentials; the base URL is fixed. Tests inject an ``httpx2`` client over a synthetic
cassette (``bridge.llm.cassettes``); the egress guard stops anything else (AC-SEC-5; D-18: no paid calls).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import anthropic
import httpx2
from anthropic.types import Message as SdkMessage
from pydantic import SecretStr

from bridge.config import Settings
from bridge.llm.adapter import BatchItemError, BatchState, ModelRequest, ModelResponse, TextBlock
from bridge.llm.errors import LLMProviderError, LLMUnavailable
from bridge.llm.registry import Registry
from bridge.llm.types import Citation, TokenUsage

ANTHROPIC_API_URL = "https://api.anthropic.com"
TRANSIENT_STATUSES = frozenset({408, 409, 429})


def _block(block: TextBlock) -> dict[str, Any]:
    param: dict[str, Any] = {"type": "text", "text": block.text}
    if block.cache:
        param["cache_control"] = {"type": "ephemeral"}
    return param


def to_params(request: ModelRequest) -> dict[str, Any]:
    """The Messages API body for ``request`` (also the ``params`` of a batch item)."""
    output_config: dict[str, Any] = {
        "format": {"type": "json_schema", "schema": anthropic.transform_schema(dict(request.output_schema))}
    }
    if request.effort is not None:
        output_config["effort"] = request.effort
    params: dict[str, Any] = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "system": [_block(b) for b in request.system],
        "messages": [{"role": m.role, "content": [_block(b) for b in m.blocks]} for m in request.messages],
        "output_config": output_config,
    }
    if request.tools:
        params["tools"] = [dict(tool) for tool in request.tools]
    return params


def _citations(message: SdkMessage) -> tuple[Citation, ...]:
    found: list[Citation] = []
    for block in message.content:
        if block.type != "text" or not block.citations:
            continue
        for cite in block.citations:
            source = getattr(cite, "url", None) or getattr(cite, "document_title", None) or getattr(cite, "title", None)
            found.append(Citation(kind=cite.type, cited_text=cite.cited_text, source=source))
    return tuple(found)


def from_message(message: SdkMessage) -> ModelResponse:
    usage = message.usage
    one_hour = usage.cache_creation.ephemeral_1h_input_tokens if usage.cache_creation is not None else 0
    return ModelResponse(
        text="".join(block.text for block in message.content if block.type == "text"),
        stop_reason=message.stop_reason or "unknown",
        usage=TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens or 0,
            cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
            cache_creation_1h_input_tokens=one_hour,
        ),
        model=message.model,
        citations=_citations(message),
        refusal_category=message.stop_details.category if message.stop_details is not None else None,
        response_id=message.id,
    )


def _provider_error(exc: anthropic.AnthropicError) -> LLMProviderError:
    """Status and error type only: provider bodies are never copied into logs or the ledger."""
    if isinstance(exc, anthropic.APIStatusError):
        status = exc.status_code
        return LLMProviderError(
            f"Anthropic HTTP {status} ({type(exc).__name__})",
            transient=status in TRANSIENT_STATUSES or status >= 500,
            status_code=status,
        )
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMProviderError(f"Anthropic unreachable ({type(exc).__name__})", transient=True)
    return LLMProviderError(f"Anthropic client error ({type(exc).__name__})", transient=False)


class AnthropicAdapter:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        timeout_seconds: float,
        max_retries: int,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._key = api_key if api_key is not None and api_key.get_secret_value().strip() else None
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._http_client = http_client
        self._sdk: anthropic.AsyncAnthropic | None = None

    def __repr__(self) -> str:
        return f"AnthropicAdapter(configured={self._key is not None})"

    def _client(self) -> anthropic.AsyncAnthropic:
        if self._key is None:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set: LLM calls are off in this environment")
        if self._sdk is None:
            self._sdk = anthropic.AsyncAnthropic(
                api_key=self._key.get_secret_value(),
                base_url=ANTHROPIC_API_URL,
                timeout=self._timeout,
                max_retries=self._max_retries,
                http_client=self._http_client,
            )
        return self._sdk

    async def create(self, request: ModelRequest) -> ModelResponse:
        client = self._client()
        try:
            message = await client.messages.create(**to_params(request))
        except anthropic.AnthropicError as exc:
            raise _provider_error(exc) from exc
        return from_message(message)

    async def batch_create(self, requests: Mapping[str, ModelRequest]) -> str:
        client = self._client()
        items = [{"custom_id": custom_id, "params": to_params(req)} for custom_id, req in requests.items()]
        try:
            batch = await client.messages.batches.create(requests=cast(Any, items))
        except anthropic.AnthropicError as exc:
            raise _provider_error(exc) from exc
        return batch.id

    async def batch_state(self, batch_id: str) -> BatchState:
        client = self._client()
        try:
            batch = await client.messages.batches.retrieve(batch_id)
        except anthropic.AnthropicError as exc:
            raise _provider_error(exc) from exc
        return BatchState(batch.processing_status)

    async def batch_results(self, batch_id: str) -> dict[str, ModelResponse | BatchItemError]:
        client = self._client()
        results: dict[str, ModelResponse | BatchItemError] = {}
        try:
            async for line in await client.messages.batches.results(batch_id):
                outcome = line.result
                if outcome.type == "succeeded":
                    results[line.custom_id] = from_message(outcome.message)
                elif outcome.type == "errored":
                    results[line.custom_id] = BatchItemError("errored", outcome.error.error.type)
                else:
                    results[line.custom_id] = BatchItemError(outcome.type, outcome.type)
        except anthropic.AnthropicError as exc:
            raise _provider_error(exc) from exc
        return results


def adapter_from_settings(settings: Settings, registry: Registry) -> AnthropicAdapter:
    """The runtime adapter. Builds without a key (dev, test); calls then raise ``LLMUnavailable``."""
    return AnthropicAdapter(
        api_key=settings.anthropic_api_key,
        timeout_seconds=registry.transport.timeout_seconds,
        max_retries=registry.transport.max_retries,
    )
