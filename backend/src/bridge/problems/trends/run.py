"""Draft one week's technology trends, without touching the database (REQ-DEV-02; D-60; P22 card B, default (5)).

``draft_trends(deps, week_start)`` makes the ``trend_synthesis`` call through ``bridge.llm`` (``TrendsDeps.client``: in
the job, the routed client of an unbound, platform-scope session, so the call has no user or organisation and the
global daily cap, the prototype total and the kill switch apply; the budget checks run before the call and every
attempt writes an ``llm_calls`` row) and runs the checks in code on the answer (``bridge.problems.trends.checks``).
The caller stores what it returns (``app_create_trend_candidate(p_card, p_sources)`` per ``TrendCandidate``, from
``p_card()`` and ``p_sources()`` as JSON); nothing here reads or writes a table.

- The week's excerpts (``synthesis.select_excerpts`` on ``week_start``: at most ``trends.max_excerpts``, not archived,
  spread over the topics, leaving out ``exclude_refs``: the excerpts stored cards already cite) are sent with the
  week; none refuses the week without a call (``no_saved_excerpts``).
- An answer the checks refuse (``injection_suspected``, ``no_trends``, or every draft discarded) is retried until
  ``trends.draft_attempts`` calls (2: one retry) are spent, the retry carrying the refusal's reason code; then the
  week is ``Refused`` with the last reason. An answer with at least one kept draft is ``Accepted`` with the kept ones.
- A typed LLM error (the kill switch, a spent cap, a provider error, a call the layer gave up on after ADR-005's
  retries and dead-lettered) refuses the week at once with the error's code: nothing is retried here that the layer
  already retried or that would be refused again. A caller's mistake (``LLMConfigError``) propagates.
- A local run's demo fallback (no model answered, D-37) refuses the week with ``demo_fallback``.

Each attempt has its own trace id, ``trends:<week_start>:<attempt>`` (``llm_calls.trace_id``); each kept card carries
the trace id of the call that wrote it (``trend_cards.llm_trace_id``). One log line per refused answer
(``trends.draft_refused_attempt``) and one per week (``trends.drafted`` or ``trends.draft_refused``), with the
week's Monday as ``day`` and reviewed fields only (``tests/unit/test_log_fields.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

from bridge.llm.client import LLMClient
from bridge.llm.errors import LLMConfigError, LLMError
from bridge.llm.types import CallContext
from bridge.logging import get_logger
from bridge.problems.research.policy import ResearchPolicy, get_research_policy
from bridge.problems.research.sources import TECH, Catalogue, CatalogueKind, get_catalogue
from bridge.problems.trends import synthesis
from bridge.problems.trends.checks import KeptTrend, Reason, check_answer
from bridge.problems.trends.policy import TrendsPolicy, get_trends_policy

DEMO_FALLBACK: Final = "demo_fallback"
NO_SAVED_EXCERPTS: Final = "no_saved_excerpts"
log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TrendsDeps:
    """What a draft needs: the LLM client (the caller's tenancy decides the ledger rows' subject), the TECH catalogue,
    the trends policy and the research policy (its confidence weights and quality tiers)."""

    client: LLMClient
    catalogue: Catalogue
    policy: TrendsPolicy
    research: ResearchPolicy

    @classmethod
    def default(cls, client: LLMClient) -> TrendsDeps:
        """The process-wide catalogue and policies with ``client``."""
        return cls(client, get_catalogue(CatalogueKind.TRENDS), get_trends_policy(), get_research_policy())


@dataclass(frozen=True, slots=True)
class TrendSource:
    """One cited source as ``app_create_trend_candidate`` takes it in ``p_sources`` (dates ISO 8601), copied from the
    saved excerpt; ``support`` is the phrase the citation was verified by."""

    url: str
    publisher: str
    published_date: str
    retrieved_at: str
    quote: str
    excerpt_ref: str
    support: str

    def as_json(self) -> dict[str, str]:
        return {
            "url": self.url,
            "publisher": self.publisher,
            "published_date": self.published_date,
            "retrieved_at": self.retrieved_at,
            "quote": self.quote,
            "excerpt_ref": self.excerpt_ref,
            "support": self.support,
        }


@dataclass(frozen=True, slots=True)
class TrendCandidate:
    """One kept trend, ready for ``app_create_trend_candidate(p_card jsonb, p_sources jsonb)``."""

    title: str
    summary: str
    topic_slug: str
    confidence: Decimal
    named_orgs: tuple[str, ...]
    llm_trace_id: str
    sources: tuple[TrendSource, ...]

    def p_card(self) -> dict[str, str | list[str]]:
        """``p_card``: confidence as a decimal string (``numeric(4,3)``), named organisations as a list."""
        return {
            "title": self.title,
            "summary": self.summary,
            "topic_slug": self.topic_slug,
            "confidence": str(self.confidence),
            "named_orgs": list(self.named_orgs),
            "llm_trace_id": self.llm_trace_id,
        }

    def p_sources(self) -> list[dict[str, str]]:
        return [source.as_json() for source in self.sources]


@dataclass(frozen=True, slots=True)
class Accepted:
    """At least one kept trend: the candidates in the model's order, the model and trace id of the call that wrote
    them, the calls made (``attempts``), their total cost and the reasons of every draft discarded on the way."""

    week_start: date
    cards: tuple[TrendCandidate, ...]
    model: str
    trace_id: str
    attempts: int
    cost_usd: Decimal
    discarded: tuple[Reason, ...] = ()


@dataclass(frozen=True, slots=True)
class Refused:
    """No candidate this week: ``reason`` is the last refusal (a ``Reason`` value), an LLM error's code (such as
    ``llm_kill_switch`` or ``llm_budget``), ``demo_fallback`` or ``no_saved_excerpts``; ``discarded`` the reasons of
    every discarded draft."""

    week_start: date
    reason: str
    attempts: int
    cost_usd: Decimal
    discarded: tuple[Reason, ...] = ()


def trace_id(week_start: date, attempt: int) -> str:
    return f"trends:{week_start.isoformat()}:{attempt}"


def candidate(kept: KeptTrend, llm_trace_id: str) -> TrendCandidate:
    """A kept trend with its sources copied from the saved excerpts (never from the model, except the verified
    support) and the call's trace id."""
    sources = tuple(
        TrendSource(
            url=s.excerpt.url,
            publisher=s.excerpt.publisher,
            published_date=s.excerpt.published_date.isoformat(),
            retrieved_at=s.excerpt.retrieved_at.isoformat(),
            quote=s.excerpt.quote,
            excerpt_ref=s.excerpt.id,
            support=s.support,
        )
        for s in kept.sources
    )
    return TrendCandidate(
        kept.title, kept.summary, kept.topic_slug, kept.confidence, kept.named_orgs, llm_trace_id, sources
    )


async def draft_trends(
    deps: TrendsDeps, week_start: date, *, exclude_refs: frozenset[str] = frozenset()
) -> Accepted | Refused:
    """Draft the trends of the week starting ``week_start`` (see the module docstring). ``exclude_refs`` are the
    excerpt ids a stored card already cites: they are not sent, so a draft citing one is ``unknown_excerpt``."""
    policy = deps.policy
    scoring = policy.scoring(deps.research)
    allowlist = deps.catalogue.allowlists.get(TECH)
    excerpts = synthesis.select_excerpts(
        deps.catalogue, week_start, scoring, policy.max_excerpts, exclude_refs=exclude_refs
    )
    if allowlist is None or not excerpts:
        return _refused(week_start, NO_SAVED_EXCERPTS, 0, Decimal(0), [])
    sent = {excerpt.id: excerpt for excerpt in excerpts}
    discarded: list[Reason] = []
    last: Reason | None = None
    cost, attempts = Decimal(0), 0
    while attempts < policy.draft_attempts:
        attempts += 1
        messages = synthesis.messages(
            week_start,
            excerpts,
            max_cards=policy.max_cards_per_run,
            min_support_words=policy.min_support_words,
            refused=last,
        )
        ctx = CallContext(trace_id=trace_id(week_start, attempts))
        try:
            result = await deps.client.complete(synthesis.TASK, messages, synthesis.TrendSynthesis, ctx=ctx)
        except LLMConfigError:
            raise
        except LLMError as exc:
            return _refused(week_start, exc.code, attempts, cost, discarded)
        cost += result.cost_usd
        if result.demo_fallback:
            return _refused(week_start, DEMO_FALLBACK, attempts, cost, discarded)
        verdict = check_answer(
            result.parsed.draft(), sent, allowlist, scoring, week_start, max_cards=policy.max_cards_per_run
        )
        discarded += verdict.discarded
        if verdict.refused is not None:
            last = verdict.refused
            log.info(
                "trends.draft_refused_attempt",
                day=week_start.isoformat(),
                attempt=attempts,
                reason=last.value,
                discarded=[r.value for r in verdict.discarded],
            )
            continue
        cards = tuple(candidate(kept, result.trace_id) for kept in verdict.kept)
        log.info(
            "trends.drafted",
            day=week_start.isoformat(),
            attempts=attempts,
            count=len(cards),
            discarded=[r.value for r in discarded],
            cost_usd=str(cost),
        )
        return Accepted(week_start, cards, result.model, result.trace_id, attempts, cost, tuple(discarded))
    final = last or Reason.NO_TRENDS  # always set: the loop runs (draft_attempts >= 2) and continues only on a refusal
    return _refused(week_start, final.value, attempts, cost, discarded)


def _refused(week_start: date, reason: str, attempts: int, cost: Decimal, discarded: list[Reason]) -> Refused:
    log.warning(
        "trends.draft_refused",
        day=week_start.isoformat(),
        reason=reason,
        attempts=attempts,
        cost_usd=str(cost),
    )
    return Refused(week_start, reason, attempts, cost, tuple(discarded))
