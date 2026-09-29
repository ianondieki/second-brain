"""``LLMClient`` and its implementation ``LLMService`` (REQ-LLM-01; ADR-005; docs/spec/08 LLM layer).

Every call: the task comes from ``ai/models.yaml`` (model, effort, max_tokens, purpose); the kill switch; the Tier-2
guard (AC-SEC-6); the sanitiser and nonce framing; per attempt a pre-call budget check (global daily cap, the
subject's monthly cap), the adapter call and one ledger row. Retry rules (ADR-005 decision 3):

- ``stop_reason == "refusal"``: logged and sent to the human queue; at most one retry on the task's fallback model.
- ``max_tokens``: one retry at twice the budget (capped at the model's maximum output).
- the answer fails the output schema: one retry with the validation error appended.
- when a rule is spent, or on a stop reason the layer does not handle, the request is dead-lettered and a typed
  ``LLMCallFailed`` is raised. Provider errors (network, HTTP) are recorded and raised as ``LLMProviderError``;
  the job runner decides whether to retry those.

Nonce scope: one random nonce (64 bits) per ``LLMService`` instance, i.e. per request or job run, shared by
its calls and batch items. A per-call nonce would change every framed block, so a cached prefix holding framed
text (a scout's org profile) could never hit the prompt cache. The trade-off: within one run, text that learns
the nonce (a model answer echoing it, replayed as input) could name it; the sanitiser still strips every tag,
so a block cannot be closed or opened from inside, and the nonce is never shown to an author.

Batches (``batch_submit``/``batch_poll``) apply the same guard, framing, caps and ledger. Once the provider accepts a
batch, every item is reserved at its batch-price estimate (``batch_reserved`` rows), so both caps count a batch in
flight. A poll first asks the ledger whether the batch is the handle's tenant's (the tenant of its earliest
reservation; one provider account serves every tenant) and refuses any other before reading the batch's state or
results. A poll of the ended batch settles each item once, with the batch tenant's organisation and user: its final
row replaces the reservation in spend, and a repeat poll returns the same outcomes without writing, dead-lettering,
queueing or counting anything again. A failed item is dead-lettered and reported, not retried (the caller may
resubmit it). An item the provider's results lack stays reserved (the results may have been cut short and the item
billed) and is reported as a transient provider error by every poll until one finds it.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ValidationError

from bridge import clock
from bridge.config import Settings
from bridge.ids import uuid7
from bridge.llm.adapter import BatchItemError, BatchState, ModelAdapter, ModelRequest, ModelResponse
from bridge.llm.budget import BudgetGuard, BudgetListener, CapProvider, Snapshot
from bridge.llm.errors import (
    ConsentRequired,
    LLMBatchNotOwned,
    LLMBlocked,
    LLMCallFailed,
    LLMConfigError,
    LLMError,
    LLMKillSwitch,
    LLMProviderError,
    LLMRefused,
    LLMSchemaError,
    LLMTruncated,
    LLMUnavailable,
    LLMUnsupportedStop,
    Tier2NotAllowed,
)
from bridge.llm.guard import ConsentChecker, check_tier2
from bridge.llm.ledger import CallStatus, LedgerEntry, LedgerStore
from bridge.llm.prepare import (
    Prepared,
    check_breakpoints,
    check_messages,
    check_schema,
    check_tools,
    prepare,
    resolve_effort,
    unsent_inputs,
    with_feedback,
)
from bridge.llm.registry import Effort, Registry, TaskSpec
from bridge.llm.sanitiser import new_nonce
from bridge.llm.sinks import (
    DeadLetter,
    DeadLetterSink,
    HumanQueue,
    InMemoryDeadLetters,
    InMemoryHumanQueue,
    RefusalEvent,
)
from bridge.llm.types import CallContext, LLMOutput, Message, Result, TokenUsage
from bridge.logging import get_logger

log = get_logger("bridge.llm")
FINISHED = frozenset({"end_turn", "stop_sequence"})
MAX_FEEDBACK_ERRORS = 5
CUSTOM_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
BATCH_TRANSIENT = frozenset({"expired", "canceled", "api_error", "overloaded_error", "rate_limit_error"})
MISSING_ITEM = "batch item missing (the provider returned no result for it)"


@dataclass(frozen=True, slots=True)
class BatchItem:
    """One request of a batch; ``custom_id`` is 1-64 characters from A-Z a-z 0-9 _ -."""

    custom_id: str
    messages: Sequence[Message]


class BatchHandle(BaseModel):
    """What a job stores between ``batch_submit`` and ``batch_poll`` (JSON-serialisable)."""

    batch_id: str
    task: str
    model: str
    trace_id: str
    org_id: UUID | None
    user_id: UUID | None
    inputs: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class BatchPoll[OutputT: LLMOutput]:
    state: BatchState
    results: dict[str, Result[OutputT] | LLMError] = field(default_factory=dict)


class LLMClient(Protocol):
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
    ) -> Result[OutputT]: ...

    async def batch_submit(
        self, task: str, items: Sequence[BatchItem], schema: type[LLMOutput], *, ctx: CallContext
    ) -> BatchHandle: ...

    async def batch_poll[OutputT: LLMOutput](
        self, handle: BatchHandle, schema: type[OutputT]
    ) -> BatchPoll[OutputT]: ...


@dataclass(frozen=True, slots=True)
class _Call:
    spec: TaskSpec
    ctx: CallContext
    trace_id: str


@dataclass(frozen=True, slots=True)
class _Failure:
    """Why a batch item's message failed."""

    error: type[LLMCallFailed]
    status: CallStatus
    detail: str


def declared_fields(output_schema: Mapping[str, Any]) -> frozenset[str]:
    """Every property name the output schema declares (nested models included)."""
    names: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            properties = node.get("properties")
            if isinstance(properties, Mapping):
                names.update(str(key) for key in properties)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(output_schema)
    return frozenset(names)


def schema_errors(exc: ValidationError, output_schema: Mapping[str, Any]) -> str:
    """Why the output failed, built only from pydantic error types and field names the schema declares. Messages
    and unknown keys are dropped: both can echo the model's output (which may quote Tier-2 or injected text)."""
    declared = declared_fields(output_schema)
    errors = exc.errors(include_input=False, include_url=False, include_context=False)[:MAX_FEEDBACK_ERRORS]
    parts = []
    for error in errors:
        loc = ".".join(str(p) if isinstance(p, int) or p in declared else "(extra key)" for p in error["loc"])
        parts.append(f"{loc or '(root)'}: {error['type']}")
    return "; ".join(parts)


class LLMService:
    """The ``LLMClient`` implementation. Cheap to build per request or job (the adapter is the long-lived part)."""

    def __init__(
        self,
        *,
        adapter: ModelAdapter,
        registry: Registry,
        settings: Settings,
        ledger: LedgerStore,
        consents: ConsentChecker,
        caps: CapProvider,
        dead_letters: DeadLetterSink | None = None,
        human_queue: HumanQueue | None = None,
        budget_listener: BudgetListener | None = None,
        nonce: Callable[[], str] = new_nonce,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._adapter = adapter
        self._registry = registry
        self._ledger = ledger
        self._consents = consents
        self._dead_letters = dead_letters or InMemoryDeadLetters()
        self._human_queue = human_queue or InMemoryHumanQueue()
        self._nonce = nonce()  # one per service instance: see the module docstring
        self._now = now or (lambda: clock.utcnow())
        self._monotonic = monotonic
        self._budget = BudgetGuard(
            settings=settings,
            ledger=ledger,
            caps=caps,
            soft_cap_ratio=registry.budget.soft_cap_ratio,
            listener=budget_listener,
            now=self._now,
        )

    # ------------------------------------------------------------------------------------------------ recording

    def _entry(
        self,
        call: _Call,
        status: CallStatus,
        *,
        attempt: int,
        inputs: Mapping[str, Any],
        model: str,
        response: ModelResponse | None = None,
        cost: Decimal = Decimal(0),
        latency_ms: int = 0,
        output: Mapping[str, Any] | None = None,
        error: str | None = None,
        batch_id: str | None = None,
        custom_id: str | None = None,
    ) -> LedgerEntry:
        usage = response.usage if response is not None else TokenUsage()
        return LedgerEntry(
            id=uuid7(),
            created_at=self._now(),
            org_id=call.ctx.org_id,
            user_id=call.ctx.user_id,
            task=call.spec.name,
            purpose=call.spec.purpose.value,
            model=model,
            status=status,
            stop_reason=response.stop_reason if response is not None else None,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_input_tokens,
            cache_creation_tokens=usage.cache_creation_input_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            trace_id=call.trace_id,
            attempt=attempt,
            inputs=inputs,
            batch_id=batch_id,
            custom_id=custom_id,
            output=output,
            error=error,
        )

    @staticmethod
    def _log_call(entry: LedgerEntry) -> None:
        log.info(
            "llm.call",
            task=entry.task,
            model=entry.model,
            status=entry.status.value,
            attempt=entry.attempt,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            cost_usd=str(entry.cost_usd),
            latency_ms=entry.latency_ms,
            trace_id=entry.trace_id,
        )

    async def _record(self, call: _Call, status: CallStatus, **fields: Any) -> None:
        """One ledger row (``_entry``'s fields) of a synchronous call, a refused call or a refused batch."""
        entry = self._entry(call, status, **fields)
        await self._ledger.record(entry)
        self._log_call(entry)

    async def _settle(self, call: _Call, status: CallStatus, **fields: Any) -> bool:
        """A batch item's final row, written once: False, with nothing written or logged, when it had settled."""
        entry = self._entry(call, status, **fields)
        if not await self._ledger.settle(entry):
            return False
        self._log_call(entry)
        return True

    async def _fail(
        self,
        call: _Call,
        error: type[LLMCallFailed],
        reason: CallStatus,
        *,
        model: str,
        attempts: int,
        detail: str,
        inputs: Mapping[str, Any],
    ) -> LLMCallFailed:
        letter = DeadLetter(
            id=uuid7(),
            created_at=self._now(),
            task=call.spec.name,
            trace_id=call.trace_id,
            org_id=call.ctx.org_id,
            user_id=call.ctx.user_id,
            reason=reason.value,
            model=model,
            attempts=attempts,
            detail=detail,
            inputs=inputs,
        )
        await self._dead_letters.put(letter)
        return error(
            f"task {call.spec.name}: {detail}",
            task=call.spec.name,
            trace_id=call.trace_id,
            dead_letter_id=str(letter.id),
        )

    async def _refuse_early(self, call: _Call, messages: Sequence[Message]) -> None:
        """The ledger's subject check (a call it cannot record is refused unrecorded), then the kill switch and the
        Tier-2 guard: those refusals are recorded with names and lengths only, against the task's model."""
        await self._ledger.check_subject(org_id=call.ctx.org_id, user_id=call.ctx.user_id)
        try:
            self._budget.check_kill_switch()
            await check_tier2(call.spec, messages, self._consents, session_id=call.ctx.session_id)
        except (LLMKillSwitch, Tier2NotAllowed, ConsentRequired) as exc:
            status = (
                CallStatus.BLOCKED_KILL_SWITCH
                if isinstance(exc, LLMKillSwitch)
                else CallStatus.BLOCKED_TIER2
                if isinstance(exc, Tier2NotAllowed)
                else CallStatus.BLOCKED_CONSENT
            )
            inputs = unsent_inputs(messages)
            await self._record(call, status, attempt=0, inputs=inputs, model=call.spec.model, error=str(exc))
            raise

    async def _check_budget(
        self, call: _Call, estimate: Decimal, attempt: int, inputs: Mapping[str, Any], model: str
    ) -> Snapshot:
        try:
            return await self._budget.check(call.ctx, estimate)
        except LLMBlocked as exc:
            status = CallStatus.BLOCKED_KILL_SWITCH if isinstance(exc, LLMKillSwitch) else CallStatus.BLOCKED_BUDGET
            await self._record(call, status, attempt=attempt, inputs=inputs, model=model, error=str(exc))
            raise

    # ------------------------------------------------------------------------------------------------ complete

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
        spec = self._registry.task(task)
        output_schema = check_schema(schema)
        check_messages(messages)
        breakpoints = check_breakpoints(cache_breakpoints, len(messages))
        tool_defs = check_tools(spec, tools)
        first_effort = resolve_effort(spec, self._registry.model(spec.model), effort)
        call = _Call(spec, ctx, ctx.trace_id or uuid7().hex)
        await self._refuse_early(call, messages)
        prepared = prepare(
            spec,
            messages,
            policy=self._registry.sanitiser,
            nonce=self._nonce,
            breakpoints=breakpoints,
            schema_in_prompt=None if spec.json_schema_format else output_schema,
        )
        return await self._attempts(call, prepared, schema, output_schema, tool_defs, first_effort)

    async def _attempts[OutputT: LLMOutput](
        self,
        call: _Call,
        prepared: Prepared,
        schema: type[OutputT],
        output_schema: Mapping[str, Any],
        tools: tuple[Mapping[str, Any], ...],
        effort: Effort | None,
    ) -> Result[OutputT]:
        spec, inputs = call.spec, prepared.ledger_inputs
        model, max_tokens, conversation = spec.model, spec.max_tokens, prepared.messages
        retried_refusal = retried_max_tokens = retried_schema = False
        usage, cost_total, attempt = TokenUsage(), Decimal(0), 0
        while True:
            attempt += 1
            request = ModelRequest(
                model, max_tokens, effort, prepared.system, conversation, output_schema, tools, spec.json_schema_format
            )
            estimate = self._registry.estimate_usd(
                model,
                input_chars=request.text_chars,
                max_tokens=max_tokens,
                cache_writes=request.cache_writes,
                tool_fees_usd=self._registry.tool_fees_usd(tools),
            )
            snapshot = await self._check_budget(call, estimate, attempt, inputs, model)
            started = self._monotonic()
            try:
                response = await self._adapter.create(request)
            except (LLMProviderError, LLMUnavailable) as exc:
                await self._record(
                    call, CallStatus.PROVIDER_ERROR, attempt=attempt, inputs=inputs, model=model, error=str(exc)
                )
                raise
            latency_ms = int((self._monotonic() - started) * 1000)
            cost = self._registry.cost_usd(model, response.usage)
            usage, cost_total = usage + response.usage, cost_total + cost
            budget = await self._budget.after(call.ctx, snapshot, cost)
            recorded: dict[str, Any] = {
                "attempt": attempt,
                "inputs": inputs,
                "model": model,
                "response": response,
                "cost": cost,
                "latency_ms": latency_ms,
            }

            if response.stop_reason == "refusal":
                await self._record(call, CallStatus.REFUSAL, **recorded)
                fallback = spec.fallback_model if not retried_refusal else None
                await self._human_queue.refusal(
                    RefusalEvent(
                        spec.name,
                        call.trace_id,
                        call.ctx.org_id,
                        call.ctx.user_id,
                        model,
                        response.refusal_category,
                        fallback,
                    )
                )
                if fallback is None:
                    raise await self._fail(
                        call,
                        LLMRefused,
                        CallStatus.REFUSAL,
                        model=model,
                        attempts=attempt,
                        detail="the model refused",
                        inputs=inputs,
                    )
                retried_refusal, model, effort = True, fallback, spec.fallback_effort
                max_tokens = min(max_tokens, self._registry.model(model).max_output_tokens)
                continue

            if response.stop_reason == "max_tokens":
                await self._record(call, CallStatus.MAX_TOKENS, **recorded)
                doubled = min(max_tokens * 2, self._registry.model(model).max_output_tokens)
                if retried_max_tokens or doubled == max_tokens:
                    raise await self._fail(
                        call,
                        LLMTruncated,
                        CallStatus.MAX_TOKENS,
                        model=model,
                        attempts=attempt,
                        detail=f"output cut at max_tokens={max_tokens}",
                        inputs=inputs,
                    )
                retried_max_tokens, max_tokens = True, doubled
                continue

            if response.stop_reason not in FINISHED:
                await self._record(call, CallStatus.UNSUPPORTED_STOP, **recorded)
                raise await self._fail(
                    call,
                    LLMUnsupportedStop,
                    CallStatus.UNSUPPORTED_STOP,
                    model=model,
                    attempts=attempt,
                    detail=f"unsupported stop reason {response.stop_reason}",
                    inputs=inputs,
                )

            try:
                parsed = schema.model_validate_json(response.text)
            except ValidationError as exc:
                problems = schema_errors(exc, output_schema)
                await self._record(call, CallStatus.SCHEMA_ERROR, error=problems, **recorded)
                if retried_schema:
                    raise await self._fail(
                        call,
                        LLMSchemaError,
                        CallStatus.SCHEMA_ERROR,
                        model=model,
                        attempts=attempt,
                        detail=f"output failed the schema: {problems}",
                        inputs=inputs,
                    ) from None  # the ValidationError quotes the model's output
                retried_schema = True
                conversation = with_feedback(
                    conversation,
                    f"Your previous answer did not match the required JSON schema ({problems}). "
                    "Answer again with JSON only, matching the schema exactly.",
                )
                continue

            output = None if spec.confidential else parsed.model_dump(mode="json")
            await self._record(call, CallStatus.OK, output=output, **recorded)
            return Result(
                parsed=parsed,
                stop_reason=response.stop_reason,
                usage=usage,
                citations=response.citations,
                model=model,
                cost_usd=cost_total,
                attempts=attempt,
                trace_id=call.trace_id,
                budget=budget,
            )

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
        """Submit ``items`` of one task and one tenant to the Batch API (only ``batchable`` tasks)."""
        spec = self._registry.task(task)
        if not spec.batchable:
            raise LLMConfigError(f"task {task} is not batchable (ai/models.yaml)")
        output_schema = check_schema(schema)
        ids = [item.custom_id for item in items]
        if not ids or len(set(ids)) != len(ids) or not all(CUSTOM_ID.fullmatch(i) for i in ids):
            raise LLMConfigError("a batch needs items with unique custom ids of 1-64 characters from A-Z a-z 0-9 _ -")
        points: dict[str, frozenset[int]] = {}
        for item in items:
            check_messages(item.messages)
            points[item.custom_id] = check_breakpoints(cache_breakpoints, len(item.messages))
        call = _Call(spec, ctx, ctx.trace_id or uuid7().hex)
        await self._refuse_early(call, [m for item in items for m in item.messages])
        requests: dict[str, ModelRequest] = {}
        inputs: dict[str, dict[str, Any]] = {}
        for item in items:
            prepared = prepare(
                spec,
                item.messages,
                policy=self._registry.sanitiser,
                nonce=self._nonce,
                breakpoints=points[item.custom_id],
                schema_in_prompt=None if spec.json_schema_format else output_schema,
            )
            requests[item.custom_id] = ModelRequest(
                spec.model,
                spec.max_tokens,
                spec.effort,
                prepared.system,
                prepared.messages,
                output_schema,
                native_format=spec.json_schema_format,
            )
            inputs[item.custom_id] = prepared.ledger_inputs
        estimates = {
            custom_id: self._registry.estimate_usd(
                spec.model, input_chars=r.text_chars, max_tokens=r.max_tokens, batch=True, cache_writes=r.cache_writes
            )
            for custom_id, r in requests.items()
        }
        await self._check_budget(call, sum(estimates.values(), Decimal(0)), 0, {"batch_items": inputs}, spec.model)
        try:
            batch_id = await self._adapter.batch_create(requests)
        except (LLMProviderError, LLMUnavailable) as exc:
            await self._record(
                call,
                CallStatus.PROVIDER_ERROR,
                attempt=0,
                inputs={"batch_items": inputs},
                model=spec.model,
                error=str(exc),
            )
            raise
        await self._reserve(call, batch_id, estimates, inputs)
        log.info("llm.batch_submitted", task=task, batch_id=batch_id, items=len(requests), trace_id=call.trace_id)
        return BatchHandle(
            batch_id=batch_id,
            task=task,
            model=spec.model,
            trace_id=call.trace_id,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            inputs=inputs,
        )

    async def _reserve(
        self, call: _Call, batch_id: str, estimates: Mapping[str, Decimal], inputs: Mapping[str, Mapping[str, Any]]
    ) -> None:
        """Reserve every item of an accepted batch at its estimate: both caps count it until its items settle."""
        holds = [
            self._entry(
                call,
                CallStatus.BATCH_RESERVED,
                attempt=1,
                inputs=inputs[custom_id],
                model=call.spec.model,
                cost=estimate,
                batch_id=batch_id,
                custom_id=custom_id,
            )
            for custom_id, estimate in estimates.items()
        ]
        try:
            await self._ledger.reserve(holds)
        except Exception:
            # The provider runs the batch unseen by the caps and the caller gets no handle: name it for an operator.
            log.error("llm.batch_unreserved", task=call.spec.name, batch_id=batch_id, trace_id=call.trace_id)
            raise

    async def batch_poll[OutputT: LLMOutput](self, handle: BatchHandle, schema: type[OutputT]) -> BatchPoll[OutputT]:
        """The batch's state; once it has ended, one outcome per item. Each item settles once, at the batch price; a
        repeat poll returns the same outcomes and counts nothing again."""
        spec = self._registry.task(handle.task)
        check_schema(schema)
        ctx = CallContext(org_id=handle.org_id, user_id=handle.user_id, trace_id=handle.trace_id)
        call = _Call(spec, ctx, handle.trace_id)
        # Before the batch's state or results are read: one provider account serves every tenant, so a handle naming
        # another tenant's batch (or one with no reservation) is refused here, never fetched.
        await self._ledger.check_subject(org_id=ctx.org_id, user_id=ctx.user_id)
        if not await self._ledger.batch_owned(handle.batch_id, org_id=ctx.org_id, user_id=ctx.user_id):
            log.warning("llm.batch_not_owned", task=spec.name, batch_id=handle.batch_id, trace_id=call.trace_id)
            raise LLMBatchNotOwned(handle.batch_id)
        state = await self._adapter.batch_state(handle.batch_id)
        if state is not BatchState.ENDED:
            return BatchPoll(state)
        raw = await self._adapter.batch_results(handle.batch_id)
        outcomes: dict[str, Result[OutputT] | LLMError] = {}
        settled_usd = Decimal(0)
        for custom_id in [*handle.inputs, *(k for k in raw if k not in handle.inputs)]:
            item = raw.get(custom_id)
            if item is None:  # not settled: its reservation keeps counting (fail closed)
                log.warning(
                    "llm.batch_item_missing", batch_id=handle.batch_id, custom_id=custom_id, trace_id=call.trace_id
                )
                outcomes[custom_id] = LLMProviderError(MISSING_ITEM, transient=True)
                continue
            outcome, cost = await self._settle_item(call, handle, custom_id, item, schema)
            outcomes[custom_id], settled_usd = outcome, settled_usd + cost
        # Read after settling (the settled rows count, their reservations no longer do); the soft cap hears only what
        # this poll settled, so a repeat poll adds nothing.
        now = await self._budget.snapshot(ctx)
        before = replace(now, spent_usd=now.spent_usd - settled_usd) if now.spent_usd is not None else now
        budget = await self._budget.after(ctx, before, settled_usd)
        final = {k: replace(v, budget=budget) if isinstance(v, Result) else v for k, v in outcomes.items()}
        return BatchPoll(state, final)

    async def _settle_item[OutputT: LLMOutput](
        self,
        call: _Call,
        handle: BatchHandle,
        custom_id: str,
        item: ModelResponse | BatchItemError,
        schema: type[OutputT],
    ) -> tuple[Result[OutputT] | LLMError, Decimal]:
        """Settle one item once. Returns its outcome and the cost this poll settled; an item an earlier poll settled
        returns the same outcome at no cost, with no row, dead letter or refusal event (and no dead letter id)."""
        model, inputs = handle.model, handle.inputs.get(custom_id, {})
        fields: dict[str, Any] = {
            "attempt": 1,
            "inputs": inputs,
            "model": model,
            "batch_id": handle.batch_id,
            "custom_id": custom_id,
        }
        if isinstance(item, BatchItemError):  # not billed: settled at no cost
            detail = f"batch item {item.kind} ({item.detail})"
            await self._settle(call, CallStatus.PROVIDER_ERROR, error=detail, **fields)
            transient = item.kind in BATCH_TRANSIENT or item.detail in BATCH_TRANSIENT
            return LLMProviderError(detail, transient=transient), Decimal(0)
        cost = self._registry.cost_usd(model, item.usage, batch=True)
        judged = self._judge(item, schema)
        if isinstance(judged, _Failure):
            fresh = await self._settle(call, judged.status, response=item, cost=cost, error=judged.detail, **fields)
            if not fresh:
                message = f"task {call.spec.name}: {judged.detail}"
                return judged.error(message, task=call.spec.name, trace_id=call.trace_id), Decimal(0)
            if judged.status is CallStatus.REFUSAL:
                event = RefusalEvent(
                    call.spec.name, call.trace_id, call.ctx.org_id, call.ctx.user_id, model, item.refusal_category, None
                )
                await self._human_queue.refusal(event)
            failed = await self._fail(
                call, judged.error, judged.status, model=model, attempts=1, detail=judged.detail, inputs=inputs
            )
            return failed, cost
        output = None if call.spec.confidential else judged.model_dump(mode="json")
        fresh = await self._settle(call, CallStatus.OK, response=item, cost=cost, output=output, **fields)
        result = Result(
            parsed=judged,
            stop_reason=item.stop_reason,
            usage=item.usage,
            citations=item.citations,
            model=model,
            cost_usd=cost,
            attempts=1,
            trace_id=call.trace_id,
        )
        return result, cost if fresh else Decimal(0)

    @staticmethod
    def _judge[OutputT: LLMOutput](response: ModelResponse, schema: type[OutputT]) -> OutputT | _Failure:
        """A batch item's parsed output, or why it failed (batch items are not retried)."""
        if response.stop_reason == "refusal":
            return _Failure(LLMRefused, CallStatus.REFUSAL, "the model refused")
        if response.stop_reason == "max_tokens":
            return _Failure(LLMTruncated, CallStatus.MAX_TOKENS, "output cut at max_tokens")
        if response.stop_reason not in FINISHED:
            detail = f"unsupported stop reason {response.stop_reason}"
            return _Failure(LLMUnsupportedStop, CallStatus.UNSUPPORTED_STOP, detail)
        try:
            return schema.model_validate_json(response.text)
        except ValidationError as exc:
            problems = schema_errors(exc, schema.model_json_schema())
            return _Failure(LLMSchemaError, CallStatus.SCHEMA_ERROR, f"output failed the schema: {problems}")
