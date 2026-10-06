"""Draft one Nairobi day's set of Today's five, without touching the database (REQ-DEV-01; D-59; P22 card A).

``draft_set(deps, day)`` makes the ``quiz_generation`` call through ``bridge.llm`` (``QuizDeps.client``: in the job, the
routed client of an unbound, platform-scope session, so the call has no user or organisation and the global daily cap,
the prototype total and the kill switch apply; the budget checks run before the call and every attempt writes an
``llm_calls`` row) and runs the checks in code on the answer (``bridge.quiz.checks``). The caller stores what it
returns; nothing here reads or writes a quiz table.

- The day's sample of the curated list (``sample_for_day``, ``policy.yaml`` ``quiz.sources_per_prompt``) is sent with
  the day; a retry sends the same sample with the reason code of the discarded draft.
- A draft the checks discard is retried until ``quiz.draft_attempts`` calls (2: one retry) are spent, then the day is
  ``Refused`` with the last reason. ``recent_hashes`` are the prompt hashes of the last ``quiz.no_repeat_days`` days,
  which the caller reads from its table (``repeated_prompt``).
- A typed LLM error (the kill switch, a spent cap, a provider error, a call the layer gave up on after ADR-005's
  retries) refuses the day at once with the error's code: nothing is retried here that the layer already retried or
  that would be refused again. A caller's mistake (``LLMConfigError``) propagates.
- A local run's demo fallback (no model answered, D-37) refuses the day with ``demo_fallback``: a placeholder is never
  a set.

Each attempt has its own trace id, ``quiz:<day>:<attempt>`` (``llm_calls.trace_id``): ``Accepted.trace_id`` names the
ledger rows of the call whose draft passed, for ``quiz_sets.llm_call_id``. One log line per discarded draft
(``quiz.draft_discarded``) and one per day (``quiz.drafted`` or ``quiz.draft_refused``).
"""

from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

from bridge.llm.client import LLMClient
from bridge.llm.errors import LLMConfigError, LLMError
from bridge.llm.types import CallContext
from bridge.logging import get_logger
from bridge.quiz import generate
from bridge.quiz.checks import AcceptedQuestion, Discarded, Reason, check_draft
from bridge.quiz.policy import QuizPolicy
from bridge.quiz.sources import SourceList, sample_for_day

DEMO_FALLBACK: Final = "demo_fallback"
log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class QuizDeps:
    """What a draft needs: the LLM client (the caller's tenancy decides the ledger rows' subject), the curated list and
    the policy."""

    client: LLMClient
    sources: SourceList
    policy: QuizPolicy


@dataclass(frozen=True, slots=True)
class Accepted:
    """A draft that passed every check: the five questions in order, the model and trace id of the call that wrote
    them, the calls made (``attempts``), their total cost and the reasons of the drafts discarded before it."""

    day: date
    questions: tuple[AcceptedQuestion, ...]
    model: str
    trace_id: str
    attempts: int
    cost_usd: Decimal
    discarded: tuple[Reason, ...] = ()


@dataclass(frozen=True, slots=True)
class Refused:
    """No set for the day: ``reason`` is the last discard reason (a ``Reason`` value), an LLM error's code (such as
    ``llm_kill_switch`` or ``llm_budget``) or ``demo_fallback``; ``discarded`` the reasons of every discarded draft."""

    day: date
    reason: str
    attempts: int
    cost_usd: Decimal
    discarded: tuple[Reason, ...] = ()


def trace_id(day: date, attempt: int) -> str:
    return f"quiz:{day.isoformat()}:{attempt}"


async def draft_set(deps: QuizDeps, day: date, *, recent_hashes: Set[str] = frozenset()) -> Accepted | Refused:
    """Draft the set for the Nairobi day ``day`` (see the module docstring)."""
    sample = sample_for_day(deps.sources, day, deps.policy.sources_per_prompt)
    sent = {source.id: source for source in sample}
    discarded: list[Reason] = []
    cost, attempts = Decimal(0), 0
    while attempts < deps.policy.draft_attempts:
        attempts += 1
        messages = generate.messages(day, sample, discarded=discarded[-1] if discarded else None)
        ctx = CallContext(trace_id=trace_id(day, attempts))
        try:
            result = await deps.client.complete(generate.TASK, messages, generate.QuizAnswer, ctx=ctx)
        except LLMConfigError:
            raise
        except LLMError as exc:
            return _refused(day, exc.code, attempts, cost, discarded)
        cost += result.cost_usd
        if result.demo_fallback:
            return _refused(day, DEMO_FALLBACK, attempts, cost, discarded)
        verdict = check_draft(result.parsed.draft(), sent, recent_hashes)
        if isinstance(verdict, Discarded):
            discarded.append(verdict.reason)
            log.info(
                "quiz.draft_discarded",
                day=day.isoformat(),
                attempt=attempts,
                reason=verdict.reason.value,
                position=verdict.position,
            )
            continue
        log.info("quiz.drafted", day=day.isoformat(), attempts=attempts, cost_usd=str(cost))
        return Accepted(day, verdict, result.model, result.trace_id, attempts, cost, tuple(discarded))
    return _refused(day, discarded[-1].value, attempts, cost, discarded)


def _refused(day: date, reason: str, attempts: int, cost: Decimal, discarded: list[Reason]) -> Refused:
    log.warning("quiz.draft_refused", day=day.isoformat(), reason=reason, attempts=attempts, cost_usd=str(cost))
    return Refused(day, reason, attempts, cost, tuple(discarded))
