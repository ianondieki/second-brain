"""``RoutedLLMClient``: which provider answers each call on a local prototype run (D-37; REQ-LLM-01 P7).

``LLM_PROVIDER`` (``Settings.llm_effective_provider``) picks the family; ``ai/models.yaml`` picks the provider per task:

- ``fake``: every call is answered by the deterministic fake (``bridge.llm.demo_fallback``), labelled.
- ``free``: the first free slot the task lists (``free_slots``) that is configured and under today's request cap,
  through an ``LLMService`` over that slot's registry (zero prices, request cap) and ``OpenAICompatibleAdapter``, with
  the D-37 data rule (``bridge.llm.demo_data``: only seeded demo data; another account's Tier-2 text is refused).
- ``anthropic``: the task's Anthropic model through the T2.2 service (its rules unchanged: consent guard, caps
  including ``LLM_PROTOTYPE_TOTAL_CAP_USD``), only when ``ai/models.yaml`` marks the prices verified (fail closed).

The demo fallback (dev and test only, ``Settings.llm_demo_fallback``): no free slot, no key, unverified prices, data
that is not demo data, a hit cap, the kill switch, an unavailable provider, a provider error or a failed call (refused,
truncated, schema failure) answer with the output schema's own safe placeholder (``demo_fallback()``, which flags
``injection_suspected``; the layer invents no verdict, and a schema without one is refused before routing), flagged
``demo_fallback`` with its reason and logged as ``llm.demo_fallback``, so the demo never errors because of a model. A
rule refusal is never faked: the Tier-2 consent guard (``Tier2NotAllowed``, ``ConsentRequired``), the D-37 Tier-2
refusal (``Tier2DemoOnly``, also when every slot is capped), a caller's mistake (``LLMConfigError``) and
``LLMBatchNotOwned`` propagate; the fallback runs the consent guard itself when the service did not get that far (the
fake provider, a route with no provider, the kill switch). In staging and production nothing is faked: the typed error
propagates (T2.2 behaviour), and the fake provider or unverified prices raise ``LLMUnavailable``.

Batches: free providers and the fake have no batch API, so a batch outside the Anthropic route (or its fallback) gets a
``demo_fallback`` handle holding only the custom ids, and polling it returns the fake answer for each (stateless, safe
across restarts, reads nothing). A real batch handle is polled through the Anthropic service as ever.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from bridge import clock
from bridge.config import FreeSlot, LLMProvider
from bridge.ids import uuid7
from bridge.llm.adapter import BatchState, ModelAdapter
from bridge.llm.budget import day_start
from bridge.llm.client import CUSTOM_ID, BatchHandle, BatchItem, BatchPoll, LLMService
from bridge.llm.demo_data import DataRule
from bridge.llm.demo_fallback import DEMO_FALLBACK_MODEL, FallbackReason, check_fallback, fallback_result
from bridge.llm.errors import (
    LLMBudgetExceeded,
    LLMCallFailed,
    LLMConfigError,
    LLMError,
    LLMKillSwitch,
    LLMProviderError,
    LLMRequestCapReached,
    LLMUnavailable,
    NotDemoData,
)
from bridge.llm.guard import ConsentChecker, check_tier2
from bridge.llm.ledger import LedgerStore
from bridge.llm.prepare import check_breakpoints, check_messages, check_schema, check_tools, resolve_effort
from bridge.llm.registry import Registry, TaskSpec, free_model_key
from bridge.llm.types import CallContext, LLMOutput, Message, Result
from bridge.logging import get_logger

log = get_logger("bridge.llm")
FALLBACK_ERRORS = (
    NotDemoData,
    LLMKillSwitch,
    LLMBudgetExceeded,
    LLMRequestCapReached,
    LLMUnavailable,
    LLMProviderError,
    LLMCallFailed,
)
ServiceFactory = Callable[[Registry, ModelAdapter, DataRule | None], LLMService]


@dataclass(frozen=True, slots=True)
class FreeRoute:
    slot: FreeSlot
    registry: Registry  # Registry.for_free_slot(slot)
    adapter: ModelAdapter


@dataclass(frozen=True)
class LLMRuntime:
    """The long-lived part, built once at startup (``bridge.llm.deps.build_runtime``)."""

    registry: Registry
    anthropic: ModelAdapter
    anthropic_configured: bool  # ANTHROPIC_API_KEY is set
    provider: LLMProvider  # Settings.llm_effective_provider
    demo_fallback: bool  # Settings.llm_demo_fallback
    free: tuple[FreeRoute, ...] = ()

    def free_route(self, number: int) -> FreeRoute | None:
        return next((route for route in self.free if route.slot.number == number), None)

    async def aclose(self) -> None:
        """Close every adapter's HTTP client (the app's lifespan, at shutdown)."""
        for adapter in (self.anthropic, *(route.adapter for route in self.free)):
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()


def reason_of(exc: LLMError) -> FallbackReason:
    if isinstance(exc, NotDemoData):
        return FallbackReason.NOT_DEMO_DATA
    if isinstance(exc, LLMKillSwitch):
        return FallbackReason.KILL_SWITCH
    if isinstance(exc, LLMRequestCapReached):
        return FallbackReason.REQUEST_CAP
    if isinstance(exc, LLMBudgetExceeded):
        return FallbackReason.BUDGET
    if isinstance(exc, LLMUnavailable):
        return FallbackReason.UNAVAILABLE
    if isinstance(exc, LLMProviderError):
        return FallbackReason.PROVIDER_ERROR
    return FallbackReason.CALL_FAILED


@dataclass(frozen=True, slots=True)
class _Service:
    service: LLMService
    free: bool


class RoutedLLMClient:
    """The ``LLMClient`` of a request or a job run. ``services`` builds an ``LLMService`` for a route (one each, built
    on first use); ``ledger`` counts a free slot's requests today; ``consents`` and ``data_rule`` guard the fallback
    path as the services guard theirs."""

    def __init__(
        self,
        *,
        runtime: LLMRuntime,
        services: ServiceFactory,
        ledger: LedgerStore,
        consents: ConsentChecker,
        data_rule: DataRule,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._runtime = runtime
        self._build = services
        self._ledger = ledger
        self._consents = consents
        self._data_rule = data_rule
        self._now = now or (lambda: clock.utcnow())
        self._services: dict[str, LLMService] = {}

    def _service(self, name: str, registry: Registry, adapter: ModelAdapter, rule: DataRule | None) -> LLMService:
        if name not in self._services:
            self._services[name] = self._build(registry, adapter, rule)
        return self._services[name]

    def _anthropic(self) -> LLMService:
        return self._service("anthropic", self._runtime.registry, self._runtime.anthropic, None)

    async def _route(self, spec: TaskSpec, *, tools: bool) -> _Service | FallbackReason:
        runtime = self._runtime
        if runtime.provider == "fake":
            return FallbackReason.FAKE_PROVIDER
        if runtime.provider == "anthropic":
            if not runtime.registry.prices_verified:
                return FallbackReason.PRICES_UNVERIFIED
            if not runtime.anthropic_configured and runtime.demo_fallback:
                return FallbackReason.NO_KEY
            return _Service(self._anthropic(), free=False)
        if tools:
            return FallbackReason.TOOLS_UNSUPPORTED
        routes = [route for n in spec.free_slots if (route := runtime.free_route(n)) is not None]
        if not routes:
            return FallbackReason.NO_FREE_SLOT
        today = day_start(self._now())
        for route in routes:
            if (
                await self._ledger.calls_since(model=free_model_key(route.slot), since=today)
                < route.slot.daily_requests
            ):
                return _Service(self._service(route.slot.name, route.registry, route.adapter, self._data_rule), True)
        return FallbackReason.REQUEST_CAP

    async def _guard(self, spec: TaskSpec, messages: Sequence[Message], ctx: CallContext) -> None:
        """The rules a fallback keeps: the Tier-2 consent guard and, on the free route, the D-37 Tier-2 refusal."""
        await check_tier2(spec, messages, self._consents, session_id=ctx.session_id)
        if self._runtime.provider == "free":
            with suppress(NotDemoData):  # answered by the fake anyway; only another account's Tier-2 text is refused
                await self._data_rule.check_call(spec.name, messages, ctx)

    def _unavailable(self, spec: TaskSpec, reason: FallbackReason) -> LLMUnavailable:
        return LLMUnavailable(f"no provider can serve task {spec.name} ({reason.value})")

    async def _fallback[OutputT: LLMOutput](
        self,
        spec: TaskSpec,
        messages: Sequence[Message],
        schema: type[OutputT],
        ctx: CallContext,
        reason: FallbackReason,
        *,
        guarded: bool,
    ) -> Result[OutputT]:
        if not self._runtime.demo_fallback:
            raise self._unavailable(spec, reason)
        if not guarded:
            await self._guard(spec, messages, ctx)
        result = fallback_result(schema, reason=reason, trace_id=str(ctx.trace_id))
        log.info("llm.demo_fallback", task=spec.name, reason=reason.value, trace_id=ctx.trace_id)
        return result

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
        spec = self._runtime.registry.task(task)
        # A caller's mistake is refused on every route as the Anthropic service refuses it (tests on the fake see it).
        check_schema(schema)
        if self._runtime.demo_fallback:  # a local run may answer with the schema's own placeholder: it must have one
            check_fallback(schema)
        check_messages(messages)
        check_breakpoints(cache_breakpoints, len(messages))
        check_tools(spec, tools)
        resolve_effort(spec, self._runtime.registry.model(spec.model), effort)
        ctx = replace(ctx, trace_id=ctx.trace_id or uuid7().hex)  # the service and a fallback share one trace
        route = await self._route(spec, tools=bool(tools))
        if isinstance(route, FallbackReason):
            return await self._fallback(spec, messages, schema, ctx, route, guarded=False)
        try:
            return await route.service.complete(
                task,
                messages,
                schema,
                ctx=ctx,
                tools=tools,
                effort=None if route.free else effort,  # free models have no effort parameter
                cache_breakpoints=cache_breakpoints,
            )
        except FALLBACK_ERRORS as exc:
            if not self._runtime.demo_fallback:
                raise
            # The kill switch refuses before the consent guard runs; every other error comes after it.
            guarded = not isinstance(exc, LLMKillSwitch)
            return await self._fallback(spec, messages, schema, ctx, reason_of(exc), guarded=guarded)

    # ------------------------------------------------------------------------------------------------- batches

    async def batch_submit(
        self,
        task: str,
        items: Sequence[BatchItem],
        schema: type[LLMOutput],
        *,
        ctx: CallContext,
        cache_breakpoints: Sequence[int] | None = None,
    ) -> BatchHandle:
        spec = self._runtime.registry.task(task)
        check_schema(schema)
        if self._runtime.demo_fallback:
            check_fallback(schema)
        ctx = replace(ctx, trace_id=ctx.trace_id or uuid7().hex)
        route = await self._route(spec, tools=False)
        if isinstance(route, _Service) and not route.free:
            try:
                return await route.service.batch_submit(
                    task, items, schema, ctx=ctx, cache_breakpoints=cache_breakpoints
                )
            except FALLBACK_ERRORS as exc:
                if not self._runtime.demo_fallback:
                    raise
                reason, guarded = reason_of(exc), not isinstance(exc, LLMKillSwitch)
        else:
            reason = route if isinstance(route, FallbackReason) else FallbackReason.NO_BATCH_API
            guarded = False
        if not self._runtime.demo_fallback:
            raise self._unavailable(spec, reason)
        return await self._fallback_batch(spec, items, schema, ctx, reason, guarded=guarded)

    async def _fallback_batch(
        self,
        spec: TaskSpec,
        items: Sequence[BatchItem],
        schema: type[LLMOutput],
        ctx: CallContext,
        reason: FallbackReason,
        *,
        guarded: bool,
    ) -> BatchHandle:
        """A handle the fake answers: the custom ids only (no inputs are kept), checked as a real batch is."""
        if not spec.batchable:
            raise LLMConfigError(f"task {spec.name} is not batchable (ai/models.yaml)")
        check_schema(schema)
        ids = [item.custom_id for item in items]
        if not ids or len(set(ids)) != len(ids) or not all(CUSTOM_ID.fullmatch(i) for i in ids):
            raise LLMConfigError("a batch needs items with unique custom ids of 1-64 characters from A-Z a-z 0-9 _ -")
        if not guarded:
            for item in items:
                check_messages(item.messages)
            await self._guard(spec, [m for item in items for m in item.messages], ctx)
        log.info("llm.demo_fallback", task=spec.name, reason=reason.value, trace_id=ctx.trace_id, items=len(ids))
        return BatchHandle(
            batch_id=f"demo-fallback-{uuid7().hex}",
            task=spec.name,
            model=DEMO_FALLBACK_MODEL,
            trace_id=str(ctx.trace_id),
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            inputs={custom_id: {} for custom_id in ids},
            demo_fallback=True,
            fallback_reason=reason.value,
        )

    async def batch_poll[OutputT: LLMOutput](self, handle: BatchHandle, schema: type[OutputT]) -> BatchPoll[OutputT]:
        if not handle.demo_fallback:
            return await self._anthropic().batch_poll(handle, schema)
        spec = self._runtime.registry.task(handle.task)
        check_schema(schema)
        known = {member.value for member in FallbackReason}
        reason = FallbackReason(handle.fallback_reason if handle.fallback_reason in known else "no_batch_api")
        results: dict[str, Result[OutputT] | LLMError] = {
            custom_id: fallback_result(schema, reason=reason, trace_id=handle.trace_id) for custom_id in handle.inputs
        }
        log.info("llm.demo_fallback_poll", task=spec.name, trace_id=handle.trace_id, items=len(results))
        return BatchPoll(BatchState.ENDED, results)
