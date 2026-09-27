"""Fakes for callers' unit tests (D-18: no paid calls; AC-SEC-5: no network).

``FakeAdapter`` is a scripted ``ModelAdapter``: each call pops the next reply (an ``LLMOutput``, a dict, raw text, a
full ``ModelResponse``, a ``BatchItemError`` for batch items, or an exception to raise). ``FakeLLMClient`` is the
real ``LLMService`` over that adapter with in-memory ledger, sinks, consents and caps, so a caller's test still goes
through the registry, the Tier-2 guard, the sanitiser, the retry rules and the ledger; inspect ``requests``,
``ledger.entries``, ``dead_letters.letters`` and ``human_queue.events``.
"""

from __future__ import annotations

import json
import math
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from typing import Any

from bridge.config import Settings, get_settings
from bridge.llm import registry as registry_module
from bridge.llm.adapter import BatchItemError, BatchState, ModelRequest, ModelResponse
from bridge.llm.budget import CapProvider, RecordingBudgetListener, StaticCaps
from bridge.llm.client import LLMService
from bridge.llm.guard import StaticConsents
from bridge.llm.ledger import InMemoryLedger
from bridge.llm.registry import Registry
from bridge.llm.sanitiser import new_nonce
from bridge.llm.sinks import InMemoryDeadLetters, InMemoryHumanQueue
from bridge.llm.types import LLMOutput, TokenUsage

Reply = LLMOutput | Mapping[str, Any] | str | ModelResponse | BatchItemError | BaseException
FAKE_CHARS_PER_TOKEN = 4
# The fake's own global cap, so callers' tests are not refused by a dev or test LLM_GLOBAL_DAILY_CAP_USD of 0.
FAKE_GLOBAL_DAILY_CAP_USD = Decimal(1000)


class FakeAdapter:
    name = "fake"

    def __init__(self, replies: Iterable[Reply] = ()) -> None:
        self._replies: deque[Reply] = deque(replies)
        self.requests: list[ModelRequest] = []
        self.batch_states: deque[BatchState] = deque()
        self._batches: dict[str, dict[str, ModelRequest]] = {}

    def queue(self, *replies: Reply) -> None:
        self._replies.extend(replies)

    def _next(self, request: ModelRequest) -> ModelResponse | BatchItemError:
        if not self._replies:
            raise AssertionError(f"FakeAdapter has no scripted reply for {request.model}")
        reply = self._replies.popleft()
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, ModelResponse | BatchItemError):
            return reply
        if isinstance(reply, LLMOutput):
            text = reply.model_dump_json()
        elif isinstance(reply, str):
            text = reply
        else:
            text = json.dumps(reply)
        usage = TokenUsage(
            input_tokens=math.ceil(request.text_chars / FAKE_CHARS_PER_TOKEN),
            output_tokens=max(1, math.ceil(len(text) / FAKE_CHARS_PER_TOKEN)),
        )
        return ModelResponse(text=text, stop_reason="end_turn", usage=usage, model=request.model)

    async def create(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        reply = self._next(request)
        if isinstance(reply, BatchItemError):
            raise AssertionError("a BatchItemError is a batch reply")
        return reply

    async def batch_create(self, requests: Mapping[str, ModelRequest]) -> str:
        batch_id = f"fake-batch-{len(self._batches) + 1}"
        self._batches[batch_id] = dict(requests)
        self.requests.extend(requests.values())
        return batch_id

    async def batch_state(self, batch_id: str) -> BatchState:
        return self.batch_states.popleft() if self.batch_states else BatchState.ENDED

    async def batch_results(self, batch_id: str) -> dict[str, ModelResponse | BatchItemError]:
        return {custom_id: self._next(request) for custom_id, request in self._batches[batch_id].items()}


class FakeLLMClient(LLMService):
    """The real ``LLMService`` over ``FakeAdapter`` and in-memory stores. Caps are unlimited unless ``caps`` says
    otherwise; the registry is ``ai/models.yaml`` unless ``registry`` is given."""

    def __init__(
        self,
        replies: Iterable[Reply] = (),
        *,
        registry: Registry | None = None,
        settings: Settings | None = None,
        consents: StaticConsents | None = None,
        caps: CapProvider | None = None,
        nonce: Callable[[], str] = new_nonce,
    ) -> None:
        cfg = settings or get_settings().model_copy(update={"llm_global_daily_cap_usd": FAKE_GLOBAL_DAILY_CAP_USD})
        self.adapter = FakeAdapter(replies)
        self.ledger = InMemoryLedger()
        self.dead_letters = InMemoryDeadLetters()
        self.human_queue = InMemoryHumanQueue()
        self.consents = consents or StaticConsents()
        self.budget_events = RecordingBudgetListener()
        super().__init__(
            adapter=self.adapter,
            registry=registry or registry_module.load(cfg.llm_models_file),
            settings=cfg,
            ledger=self.ledger,
            consents=self.consents,
            caps=caps or StaticCaps(),
            dead_letters=self.dead_letters,
            human_queue=self.human_queue,
            budget_listener=self.budget_events,
            nonce=nonce,
        )

    def queue(self, *replies: Reply) -> None:
        self.adapter.queue(*replies)

    @property
    def requests(self) -> list[ModelRequest]:
        return self.adapter.requests
