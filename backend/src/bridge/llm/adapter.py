"""The provider seam (ADR-005 decision 1): ``ModelAdapter`` turns one provider-neutral ``ModelRequest`` into one
``ModelResponse``, and runs batches. ``LLMService`` owns every rule (registry, guard, sanitiser, caps, retries,
ledger); an adapter only speaks the provider's wire format. The single production adapter is
``bridge.llm.anthropic_adapter.AnthropicAdapter``; tests use ``bridge.llm.fakes.FakeAdapter`` or the real adapter
over synthetic cassettes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol

from bridge.llm.registry import Effort
from bridge.llm.types import Citation, TokenUsage


@dataclass(frozen=True, slots=True)
class TextBlock:
    """One text content block; ``cache`` puts a prompt-cache breakpoint after it."""

    text: str
    cache: bool = False


@dataclass(frozen=True, slots=True)
class WireMessage:
    role: Literal["user", "assistant"]
    blocks: tuple[TextBlock, ...]


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """``output_schema`` is the output model's JSON schema; the adapter converts it to the provider's strict form.
    ``effort`` is None only for a model without an effort parameter (the registry enforces it)."""

    model: str
    max_tokens: int
    effort: Effort | None
    system: tuple[TextBlock, ...]
    messages: tuple[WireMessage, ...]
    output_schema: Mapping[str, Any]
    tools: tuple[Mapping[str, Any], ...] = ()

    @property
    def text_chars(self) -> int:
        """Characters of prompt text (for the pre-call estimate)."""
        return sum(len(b.text) for b in self.system) + sum(len(b.text) for m in self.messages for b in m.blocks)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str
    stop_reason: str
    usage: TokenUsage
    model: str
    citations: tuple[Citation, ...] = ()
    refusal_category: str | None = None
    response_id: str | None = None


class BatchState(StrEnum):
    IN_PROGRESS = "in_progress"
    CANCELING = "canceling"
    ENDED = "ended"


@dataclass(frozen=True, slots=True)
class BatchItemError:
    """A batch request that produced no message (``errored``, ``canceled`` or ``expired``)."""

    kind: str
    detail: str


class ModelAdapter(Protocol):
    async def create(self, request: ModelRequest) -> ModelResponse: ...

    async def batch_create(self, requests: Mapping[str, ModelRequest]) -> str:
        """Submit requests keyed by custom id; returns the provider's batch id."""
        ...

    async def batch_state(self, batch_id: str) -> BatchState: ...

    async def batch_results(self, batch_id: str) -> dict[str, ModelResponse | BatchItemError]: ...
