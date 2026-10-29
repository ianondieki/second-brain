"""REQ-DEV-02 (D-60; P22 card B test B6, the job's half): the weekly pass ``run_weekly`` on the shared clock, as the
scheduler runs it, with no user bound (``app_trend_job_state`` is the job's reader of the cards).

- It drafts the week's Monday once (one scripted ``trend_synthesis`` call through the real ``LLMService``) and stores
  the kept cards as candidates through ``app_create_trend_candidate``, with their sources and the call's trace id.
- Within 6 days of a card that is not rejected it makes no call; after them, the excerpts such cards cite are not sent
  again (the scripted answer citing them is refused twice); a rejected card neither holds the week nor its excerpts.
- The kill switch refuses without a call; wired as the worker wires it, no provider is reached (the demo fallback).
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any

from bridge.config import get_settings
from bridge.db import create_session_factory
from bridge.jobs.trends import RECENT_CARD, Skipped, Stored, TrendsRuntime, WeeklyDeps, run_weekly
from bridge.llm.fakes import FAKE_GLOBAL_DAILY_CAP_USD
from bridge.llm.ledger import CallStatus
from bridge.problems.trends import fakes
from bridge.problems.trends.run import Refused
from tests.integration.events.api_world import WeekDb, at, cast, owner_rows, owner_run

WEEKLY = time(5, 15)  # the job's hour in Nairobi on Mondays


def client(*variants: str, **settings: Any) -> fakes.FakeTrendsClient:
    roomy = {"llm_global_daily_cap_usd": FAKE_GLOBAL_DAILY_CAP_USD, "llm_prototype_total_cap_usd": 1000} | settings
    return fakes.FakeTrendsClient(*variants, settings=get_settings().model_copy(update=roomy))


def deps(week: WeekDb, llm: fakes.FakeTrendsClient) -> WeeklyDeps:
    return WeeklyDeps(factory=create_session_factory(week.app), llm=lambda db: llm)


async def fresh(week: WeekDb) -> None:
    """No card of an earlier test (the module's database is shared): they would count as recent or cited."""
    await owner_run(week, "DELETE FROM trend_cards")


async def cards(week: WeekDb) -> list[Any]:
    return await owner_rows(
        week, "SELECT id, title, status, topic_slug, llm_trace_id, named_orgs FROM trend_cards ORDER BY created_at, id"
    )


async def test_the_job_stores_the_kept_cards_once_a_week(week: WeekDb) -> None:
    monday = week.monday()
    await at(week, monday, WEEKLY)
    await fresh(week)
    before = {row.id for row in await cards(week)}
    llm = client("valid")
    stored = await run_weekly(deps(week, llm))
    assert isinstance(stored, Stored)
    assert (stored.week_start, len(stored.card_ids)) == (monday, 3)
    made = [row for row in await cards(week) if row.id not in before]
    assert [(r.status, r.topic_slug, r.llm_trace_id) for r in made] == [
        ("candidate", "security", f"trends:{monday}:1"),
        ("candidate", "databases", f"trends:{monday}:1"),
        ("candidate", "kenya-ict", f"trends:{monday}:1"),
    ]
    assert [r.title for r in made] == [fakes.SECURITY.title, fakes.DATABASES.title, fakes.KENYA.title]
    assert made[0].named_orgs == ["GitHub"]
    sources = await owner_rows(
        week,
        "SELECT card_id, position, publisher, excerpt_ref, support FROM trend_card_sources WHERE card_id = ANY(:c)"
        " ORDER BY position",
        c=list(stored.card_ids),
    )
    assert {(s.card_id, s.excerpt_ref) for s in sources} == {
        (stored.card_ids[0], "tr-sec-001"),
        (stored.card_ids[1], "tr-dat-002"),
        (stored.card_ids[2], "tr-ke-002"),
    }
    [entry] = llm.ledger.entries
    assert (entry.status, entry.trace_id) == (CallStatus.OK, f"trends:{monday}:1")
    again = await run_weekly(deps(week, llm))  # the same morning: nothing to do, no call
    assert again == Skipped(monday, RECENT_CARD)
    assert len(llm.requests) == 1


async def test_within_six_days_no_call_and_after_them_no_cited_excerpt_again(week: WeekDb) -> None:
    monday = week.monday()
    await at(week, monday, WEEKLY)
    await fresh(week)
    p = await cast(week)
    llm = client("valid")
    assert isinstance(await run_weekly(deps(week, llm)), Stored)
    await at(week, monday + timedelta(days=5), time(23, 0))
    assert await run_weekly(deps(week, llm)) == Skipped(monday, RECENT_CARD)
    assert len(llm.requests) == 1
    next_monday = monday + timedelta(days=7)
    await at(week, next_monday, WEEKLY)
    llm.queue(fakes.answer("valid"), fakes.answer("valid"))  # cites only excerpts the stored cards cite
    refused = await run_weekly(deps(week, llm))
    assert isinstance(refused, Refused)
    assert (refused.week_start, refused.reason, refused.attempts) == (next_monday, "unknown_excerpt", 2)
    sent = " ".join(block.text for message in llm.requests[-1].messages for block in message.blocks)
    assert "tr-sec-001" not in sent
    assert "tr-dat-002" not in sent
    assert "tr-sec-002" in sent  # the other excerpts of the topic still go
    await owner_run(  # staff reject the week's cards: they neither hold a week nor keep their excerpts back
        week,
        "UPDATE trend_cards SET status = 'rejected', decided_by = :a, decided_at = now() WHERE status = 'candidate'",
        a=p.admin,
    )
    llm.queue(fakes.answer("valid"))
    again = await run_weekly(deps(week, llm))
    assert isinstance(again, Stored)
    assert (again.week_start, len(again.card_ids)) == (next_monday, 3)


async def test_the_kill_switch_refuses_without_a_call(week: WeekDb) -> None:
    monday = week.monday()
    await at(week, monday, WEEKLY)
    await fresh(week)
    before = len(await cards(week))
    llm = client("valid", llm_kill_switch=True)
    refused = await run_weekly(deps(week, llm))
    assert isinstance(refused, Refused)
    assert (refused.reason, refused.attempts) == ("llm_kill_switch", 1)
    assert llm.requests == []
    assert [e.status for e in llm.ledger.entries] == [CallStatus.BLOCKED_KILL_SWITCH]
    assert len(await cards(week)) == before


async def test_wired_as_the_worker_no_provider_is_reached(week: WeekDb) -> None:
    monday = week.monday()
    await at(week, monday, WEEKLY)
    await fresh(week)
    before = len(await cards(week))
    runtime = TrendsRuntime(get_settings(), factory=create_session_factory(week.app))
    try:
        outcome = await run_weekly(runtime.deps())
    finally:
        await runtime.aclose()
    assert isinstance(outcome, Refused)
    assert (outcome.reason, outcome.attempts) == ("demo_fallback", 1)
    assert len(await cards(week)) == before
