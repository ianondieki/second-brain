"""REQ-TREND-01 (docs/spec/06 6.6): decayed scores, per-niche z-scores against a 90-day baseline, cold start and "New
this week", and the anti-gaming rules (AC-TREND-1)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from bridge.matching.ranking_config import Decay, get_ranking
from bridge.matching.trending import (
    Aggregate,
    Event,
    Subject,
    decayed,
    once_per_actor_and_day,
    organisation_side,
    trends,
    without_bursts,
)

CFG = get_ranking().trending
PROBLEMS = CFG.problems
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)  # 12:00 in Nairobi, Monday 5 October
TODAY = date(2026, 10, 5)


def subject(events: list[Event], *, niche: UUID | None = None, actors: int = 3, age_days: int = 200) -> Subject:
    return Subject(uuid4(), niche, NOW - timedelta(days=age_days), tuple(events), actors)


def test_the_score_halves_every_half_life() -> None:
    event = [Event("scout_match", TODAY - timedelta(days=14), 1)]
    assert decayed(event, PROBLEMS, TODAY) == pytest.approx(1.0)  # weight 2, one half-life old
    assert decayed(event, PROBLEMS, TODAY - timedelta(days=14)) == pytest.approx(2.0)
    assert decayed(event, PROBLEMS, TODAY - timedelta(days=15)) == 0  # not happened yet
    projects = get_ranking().trending.projects
    assert decayed([Event("org_interest", TODAY - timedelta(days=7), 2)], projects, TODAY) == pytest.approx(12.0)
    assert decayed([Event("unlisted", TODAY, 5)], PROBLEMS, TODAY) == 0  # a kind without a weight counts nothing


def test_anti_gaming() -> None:
    """AC-TREND-1: five saves by one account in one day count as one; events from a 3-day-old account cohort forming
    more than half of an item's events are excluded (the rest are kept)."""
    item, day = uuid4(), TODAY
    rows = [("acct-1", item, day)] * 5 + [("acct-2", item, day), ("acct-1", item, day - timedelta(days=1))]
    assert once_per_actor_and_day(rows) == {(item, day): 2, (item, day - timedelta(days=1)): 1}

    burst = [
        Aggregate(item, "org_interest", day, events=6, actors=8, orgs=8, young=5),  # 5 of 6 by 3-day-old accounts
        Aggregate(item, "org_interest", day - timedelta(days=1), events=2, actors=8, orgs=8, young=1),
    ]
    kept = without_bursts(burst, CFG.young_share)  # 6 of 8 events young: > 50%
    assert [(r.day, r.events) for r in kept] == [(day, 1), (day - timedelta(days=1), 1)]
    calm = [replace(burst[0], young=2), replace(burst[1], young=0)]  # 2 of 8 young: kept as they are
    assert without_bursts(calm, CFG.young_share) == calm
    unknown = [replace(r, young=None) for r in burst]  # revision 0005 does not say: nothing is dropped
    assert without_bursts(unknown, CFG.young_share) == unknown


def test_organisation_side_kinds_count_organisations_not_seats() -> None:
    """No same-organisation boosts: below 3 organisations a kind is dropped whatever its seats did; above, events
    are weighted by organisations per actor."""
    item = uuid4()
    few = Aggregate(item, "org_interest", TODAY, events=5, actors=5, orgs=None)
    two = Aggregate(item, "org_interest", TODAY, events=5, actors=5, orgs=2)
    many = Aggregate(item, "org_interest", TODAY, events=6, actors=6, orgs=3)
    assert organisation_side([few, two], CFG.min_orgs) == []
    [kept] = organisation_side([many], CFG.min_orgs)
    assert (kept.events, kept.actors) == (3.0, 3)


def test_a_spike_against_its_niche_baseline_trends_and_steady_activity_does_not() -> None:
    niche = uuid4()
    steady = [Event("scout_match", TODAY - timedelta(days=d), 1) for d in range(0, 90, 7)]
    spike = [*steady[1:], *(Event("scout_match", TODAY - timedelta(days=d), 3) for d in range(3))]
    a, b = subject(steady, niche=niche), subject(spike, niche=niche)
    out = trends([a, b], PROBLEMS, CFG, NOW)
    assert out[b.id].z is not None
    assert out[b.id].trending
    assert out[a.id].z is not None
    assert not out[a.id].trending


def test_trending_needs_three_actors_and_a_minimum_score() -> None:
    niche = uuid4()
    history = [Event("scout_match", TODAY - timedelta(days=d), 1) for d in range(7, 90, 7)]
    now_events = [*history, *(Event("scout_match", TODAY, 3) for _ in range(2))]
    lonely = subject(now_events, niche=niche, actors=2)
    crowd = subject(now_events, niche=niche, actors=3)
    out = trends([lonely, crowd], PROBLEMS, CFG, NOW)
    assert out[lonely.id].z == out[crowd.id].z
    assert (out[lonely.id].trending, out[crowd.id].trending) == (False, True)


def test_cold_start_has_no_z_score_and_shows_new_this_week() -> None:
    """A niche without enough baseline history: no z-score and no badge, but an item published this week is New."""
    niche = uuid4()
    fresh = subject([Event("scout_match", TODAY, 5)], niche=niche, age_days=2)
    old = subject([], niche=niche, age_days=30)
    out = trends([fresh, old], PROBLEMS, CFG, NOW)
    assert (out[fresh.id].z, out[fresh.id].trending, out[fresh.id].new_this_week) == (None, False, True)
    assert (out[old.id].z, out[old.id].new_this_week) == (None, False)
    assert out[fresh.id].score == pytest.approx(10.0)


def test_an_item_counts_in_its_baseline_only_from_its_publication() -> None:
    """Weeks before an item existed are not zeros of its niche's baseline (they would make any activity a trend)."""
    niche = uuid4()
    history = [Event("scout_match", TODAY - timedelta(days=d), 1) for d in range(7, 90, 7)]
    veteran = subject(history, niche=niche)
    newcomer = subject([], niche=niche, age_days=10)  # scored at 1 baseline point only, not 12
    with_newcomer = trends([veteran, newcomer], PROBLEMS, CFG, NOW)
    as_if_old = trends([veteran, replace(newcomer, published_at=NOW - timedelta(days=200))], PROBLEMS, CFG, NOW)
    assert with_newcomer[veteran.id].z != as_if_old[veteran.id].z


def test_niches_have_their_own_baselines() -> None:
    """A small niche can trend: its items are compared with its own history, not with a busy niche's."""
    busy, small = uuid4(), uuid4()
    loud = [Event("scout_match", TODAY - timedelta(days=d), 20) for d in range(200)]  # steady, older than 90 days
    quiet_history = [Event("scout_match", TODAY - timedelta(days=d), 1) for d in range(14, 90, 7)]
    quiet_now = [*quiet_history, Event("scout_match", TODAY, 4)]
    busy_items = [subject(loud, niche=busy) for _ in range(3)]
    small_item = subject(quiet_now, niche=small)
    out = trends([*busy_items, small_item], PROBLEMS, CFG, NOW)
    assert out[small_item.id].trending
    assert all(not out[s.id].trending for s in busy_items)


def test_the_result_is_deterministic() -> None:
    niche = uuid4()
    items = [subject([Event("scout_match", TODAY - timedelta(days=d), 1)], niche=niche) for d in range(0, 60, 5)]
    assert trends(items, PROBLEMS, CFG, NOW) == trends(list(reversed(items)), PROBLEMS, CFG, NOW)


def test_a_custom_decay_uses_its_own_weights() -> None:
    decay = Decay(half_life_days=1, weights={"scout_match": 1})
    assert decayed([Event("scout_match", TODAY - timedelta(days=2), 4)], decay, TODAY) == pytest.approx(1.0)
