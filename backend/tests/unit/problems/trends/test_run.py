"""REQ-DEV-02 (D-60; P22 card B test B6, the drafting part): ``draft_trends`` makes one ``trend_synthesis`` call
through ``bridge.llm``, retries a refused answer once and then refuses the week; the kill switch and the daily cap
refuse without a call; a demo fallback is never a card; a kept card carries its sources copied from the saved
excerpts and the call's trace id, in the shape ``app_create_trend_candidate(p_card, p_sources)`` takes. No database
is touched; the synthetic cassette replays through the real SDK."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from bridge.llm.cassettes import CassettePlayer, load
from bridge.llm.demo_fallback import FallbackReason, fallback_result
from bridge.llm.errors import LLMConfigError
from bridge.llm.ledger import CallStatus
from bridge.llm.types import CallContext, LLMOutput, Message, Result
from bridge.problems.research.sources import CatalogueKind, get_catalogue
from bridge.problems.trends import fakes, synthesis
from bridge.problems.trends.checks import Reason
from bridge.problems.trends.run import Accepted, Refused, TrendsDeps, draft_trends
from tests.unit.llm.helpers import settings
from tests.unit.llm.rig import rig

WEEK: Final = date(2026, 10, 5)
CASSETTE: Final = Path(__file__).resolve().parents[3] / "fixtures" / "cassettes" / "trend_synthesis_eval.json"
CARD_KEYS: Final = {"title", "summary", "topic_slug", "confidence", "named_orgs", "llm_trace_id"}
SOURCE_KEYS: Final = {"url", "publisher", "published_date", "retrieved_at", "quote", "excerpt_ref", "support"}


def deps(client: Any) -> TrendsDeps:
    return TrendsDeps.default(client)


async def test_a_clean_answer_is_accepted_in_one_call_in_the_storing_shape() -> None:
    client = fakes.FakeTrendsClient("valid")
    outcome = await draft_trends(deps(client), WEEK)
    assert isinstance(outcome, Accepted)
    assert (outcome.week_start, outcome.attempts, outcome.discarded) == (WEEK, 1, ())
    assert outcome.trace_id == "trends:2026-10-05:1"
    assert outcome.cost_usd > 0
    assert [c.topic_slug for c in outcome.cards] == ["security", "databases", "kenya-ict"]
    card = outcome.cards[0]
    assert card.p_card() == {
        "title": fakes.SECURITY.title,
        "summary": fakes.SECURITY.summary,
        "topic_slug": "security",
        "confidence": "0.833",
        "named_orgs": ["GitHub"],
        "llm_trace_id": "trends:2026-10-05:1",
    }
    excerpt = get_catalogue(CatalogueKind.TRENDS).get("tr-sec-001")
    assert excerpt is not None
    assert card.p_sources() == [
        {
            "url": excerpt.url,
            "publisher": "GitHub",
            "published_date": "2026-10-02",
            "retrieved_at": "2026-10-06",
            "quote": excerpt.quote,
            "excerpt_ref": "tr-sec-001",
            "support": "now expire 48 hours after creation",
        }
    ]
    for c in outcome.cards:  # the storing part only serialises
        assert set(json.loads(json.dumps(c.p_card()))) == CARD_KEYS
        assert all(set(s) == SOURCE_KEYS for s in json.loads(json.dumps(c.p_sources())))
        assert 1 <= len(c.sources) <= 5
    [entry] = client.ledger.entries
    assert (entry.task, entry.status, entry.trace_id) == (synthesis.TASK, CallStatus.OK, outcome.trace_id)
    assert (entry.user_id, entry.org_id) == (None, None)  # a platform job's call: the global caps apply


async def test_a_partly_valid_answer_is_accepted_with_its_discards() -> None:
    outcome = await draft_trends(deps(fakes.FakeTrendsClient("partly_valid")), WEEK)
    assert isinstance(outcome, Accepted)
    assert (len(outcome.cards), outcome.attempts, outcome.discarded) == (2, 1, (Reason.UNKNOWN_EXCERPT,))


async def test_a_refused_answer_is_retried_once_with_its_reason() -> None:
    client = fakes.FakeTrendsClient("injection_suspected", "valid")
    outcome = await draft_trends(deps(client), WEEK)
    assert isinstance(outcome, Accepted)
    assert (outcome.attempts, outcome.trace_id) == (2, "trends:2026-10-05:2")
    assert outcome.discarded == (Reason.INJECTION_SUSPECTED,) * 3
    assert {c.llm_trace_id for c in outcome.cards} == {"trends:2026-10-05:2"}
    first, second = client.requests
    assert not any("refused by the checks" in b.text for m in first.messages for b in m.blocks)
    assert any("refused by the checks (injection_suspected)" in b.text for m in second.messages for b in m.blocks)
    assert outcome.cost_usd == sum((e.cost_usd for e in client.ledger.entries), Decimal(0))


async def test_two_refused_answers_refuse_the_week() -> None:
    client = fakes.FakeTrendsClient("unknown_excerpt", "no_trends", "valid")
    outcome = await draft_trends(deps(client), WEEK)
    assert outcome == Refused(WEEK, "no_trends", 2, outcome.cost_usd, (Reason.UNKNOWN_EXCERPT,))
    assert len(client.requests) == 2  # the third scripted answer is never asked for


async def test_the_kill_switch_refuses_without_a_call() -> None:
    client = fakes.FakeTrendsClient("valid", settings=settings(llm_kill_switch=True))
    outcome = await draft_trends(deps(client), WEEK)
    assert outcome == Refused(WEEK, "llm_kill_switch", 1, Decimal(0))
    assert client.requests == []
    assert [e.status for e in client.ledger.entries] == [CallStatus.BLOCKED_KILL_SWITCH]


@pytest.mark.parametrize("cap", [Decimal(0), Decimal("0.01")])
async def test_the_daily_cap_refuses_without_a_call(cap: Decimal) -> None:
    """The pre-call estimate counts every requested output token (2048 at Sonnet's 10 USD per million: 0.02 USD)."""
    client = fakes.FakeTrendsClient("valid", settings=settings(llm_global_daily_cap_usd=cap))
    outcome = await draft_trends(deps(client), WEEK)
    assert outcome == Refused(WEEK, "llm_budget", 1, Decimal(0))
    assert client.requests == []
    assert [e.status for e in client.ledger.entries] == [CallStatus.BLOCKED_BUDGET]


async def test_no_saved_excerpts_refuses_without_a_call() -> None:
    client = fakes.FakeTrendsClient("valid")
    outcome = await draft_trends(deps(client), date(2028, 1, 3))  # every saved excerpt archived by then
    assert outcome == Refused(date(2028, 1, 3), "no_saved_excerpts", 0, Decimal(0))
    empty = dataclasses.replace(deps(client), catalogue=get_catalogue())  # the research catalogue has no TECH
    assert (await draft_trends(empty, WEEK)) == Refused(WEEK, "no_saved_excerpts", 0, Decimal(0))
    assert client.requests == []


class FallbackClient:
    """A local run's router when no model may answer: the schema's placeholder (D-37)."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete[OutputT: LLMOutput](
        self, task: str, messages: Sequence[Message], schema: type[OutputT], *, ctx: CallContext, **_: Any
    ) -> Result[OutputT]:
        self.calls += 1
        return fallback_result(schema, reason=FallbackReason.FAKE_PROVIDER, trace_id=ctx.trace_id or "t")


async def test_a_demo_fallback_is_never_a_card_and_not_retried() -> None:
    client = FallbackClient()
    outcome = await draft_trends(deps(client), WEEK)
    assert outcome == Refused(WEEK, "demo_fallback", 1, Decimal(0))
    assert client.calls == 1


class MisconfiguredClient(FallbackClient):
    async def complete[OutputT: LLMOutput](
        self, task: str, messages: Sequence[Message], schema: type[OutputT], *, ctx: CallContext, **_: Any
    ) -> Result[OutputT]:
        raise LLMConfigError("unknown task")


async def test_a_callers_mistake_propagates() -> None:
    with pytest.raises(LLMConfigError):
        await draft_trends(deps(MisconfiguredClient()), WEEK)


async def test_the_cassette_replays_a_retry_through_the_real_sdk() -> None:
    """Interactions 1 and 2 of the eval cassette: an answer flagging an injection, then three clean trends."""
    tape = CassettePlayer(load(CASSETTE)[:2])
    r = rig(tape.adapter())
    outcome = await draft_trends(deps(r.service), WEEK)
    assert tape.exhausted
    assert tape.errors == []
    assert isinstance(outcome, Accepted)
    assert (outcome.attempts, outcome.model) == (2, "claude-sonnet-5")
    assert outcome.discarded == (Reason.INJECTION_SUSPECTED,)
    assert [c.topic_slug for c in outcome.cards] == ["ai", "cloud", "mobile"]
    catalogue = get_catalogue(CatalogueKind.TRENDS)
    for card in outcome.cards:
        for source in card.sources:
            saved = catalogue.get(source.excerpt_ref)
            assert saved is not None
            assert (source.url, source.publisher, source.quote) == (saved.url, saved.publisher, saved.quote)
            assert source.support in saved.quote
    request: Mapping[str, Any] = tape.requests[0].json()
    assert "tools" not in request
    assert request["model"] == "claude-sonnet-5"
    text = "\n".join(block["text"] for m in request["messages"] for block in m["content"])
    assert text.count("<submission nonce=") == 12
    second = "\n".join(block["text"] for m in tape.requests[1].json()["messages"] for block in m["content"])
    assert "refused by the checks (injection_suspected)" in second
    assert [e.status for e in r.ledger.entries] == [CallStatus.OK, CallStatus.OK]


async def test_an_excluded_ref_is_not_sent_and_a_draft_citing_it_is_unknown_excerpt() -> None:
    """Excerpts a stored card already cites (``exclude_refs``) never reach the prompt; citing one is invented."""
    client = fakes.FakeTrendsClient("partly_valid")
    outcome = await draft_trends(deps(client), WEEK, exclude_refs=frozenset({"tr-dat-002"}))
    [request] = client.requests
    text = "\n".join(b.text for m in request.messages for b in m.blocks)
    assert "id: tr-dat-002" not in text
    assert text.count("<submission nonce=") == 12  # the next excerpt takes its place
    assert isinstance(outcome, Accepted)
    assert outcome.discarded == (Reason.UNKNOWN_EXCERPT,)  # the second trend cites a ref that was not sent
    assert "tr-dat-002" not in {s.excerpt_ref for c in outcome.cards for s in c.sources}
    only_databases = await draft_trends(
        deps(fakes.FakeTrendsClient("valid", "valid")), WEEK, exclude_refs=frozenset({"tr-dat-002"})
    )
    assert isinstance(only_databases, Accepted)
    assert only_databases.discarded == (Reason.UNKNOWN_EXCERPT,)  # DATABASES cites tr-dat-002, now unsent
    assert [c.topic_slug for c in only_databases.cards] == ["security", "kenya-ict"]


async def test_excluding_every_usable_excerpt_refuses_without_a_call() -> None:
    client = fakes.FakeTrendsClient("valid")
    every = frozenset(e.id for e in get_catalogue(CatalogueKind.TRENDS).excerpts)
    outcome = await draft_trends(deps(client), WEEK, exclude_refs=every)
    assert outcome == Refused(WEEK, "no_saved_excerpts", 0, Decimal(0))
    assert client.requests == []
