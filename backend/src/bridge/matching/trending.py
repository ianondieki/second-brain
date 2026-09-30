"""Trend scores, computed on read (REQ-TREND-01; docs/spec/06 6.6; prototype-m2-plan.md §6: plain Python, no stored
scores, no ``trends.recompute`` job).

For each item (a problem or a project) the decayed score is ``T(t) = Σ w_e · 2^(-(t - t_e)/h)`` over its events, by
Africa/Nairobi day (h = 14 days for problems, 7 for projects; the weights are ``config/ranking/weights_v1.yaml``'s).
It is shown as a z-score against the item's niche: the baseline is every item of the niche scored at weekly points
over the last 90 days (an item counts only from the week it was published), so a small niche can trend against its
own history. A niche with too few non-zero baseline scores has no z-score (cold start): its items can be "New this
week" but never "Trending". An item is Trending when its z-score, its score and its distinct actors all reach the
configured floors.

Anti-gaming, the cheap part (docs/spec/06 6.6):

- unique verified accounts: organisation-side signals come only from E1/E2 organisations' members and scouts, and a
  proposal only from a D1 developer (the routes that write them require it);
- one event per account, item and day: ``app_trend_aggregates`` counts each actor once per item and day, and
  ``once_per_actor_and_day`` does the same for facts read from tables (proposals against a problem);
- no self or same-organisation boosts: a problem's own creator's proposals never count for it, and an
  organisation-side kind counts only when it comes from at least ``min_orgs`` distinct organisations, weighted by
  organisations rather than people (``organisation_side``), so one organisation's many seats are one voice;
- at least 3 distinct actors: the definer returns nothing below 3 per item and kind, and an item needs
  ``min_actors`` in all before it is Trending;
- the burst detector (``without_bursts``: when more than half of an item's events come from accounts younger than 7
  days, those events are ignored) is written and tested, but ``app_trend_aggregates`` (0005) does not say which
  events came from young accounts, so it has no data yet: a later revision adds that count (REQ-TREND-01 card).

Everything here is pure: the facts are read by ``bridge.matching.trend_facts``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo

from bridge.matching.ranking_config import Decay, TrendConfig

NAIROBI: Final = ZoneInfo("Africa/Nairobi")


@dataclass(frozen=True, slots=True)
class Aggregate:
    """One row of ``app_trend_aggregates``: ``actors`` and ``orgs`` are the item and kind's over the whole window;
    ``young`` would be the day's events by accounts younger than ``young_days`` (not returned by revision 0005)."""

    item_id: UUID
    kind: str
    day: date
    events: float
    actors: int
    orgs: int | None
    young: int | None = None


@dataclass(frozen=True, slots=True)
class Event:
    kind: str
    day: date
    count: float


@dataclass(frozen=True, slots=True)
class Subject:
    """An item to score: its niche, when it was published and its events after the anti-gaming rules."""

    id: UUID
    niche_id: UUID | None
    published_at: datetime | None
    events: tuple[Event, ...]
    actors: int


@dataclass(frozen=True, slots=True)
class Trend:
    score: float  # T(now), rounded to 3 places
    z: float | None  # None: the niche has no baseline yet (cold start)
    trending: bool
    new_this_week: bool
    actors: int


def nairobi_day(moment: datetime) -> date:
    return moment.astimezone(NAIROBI).date()


def once_per_actor_and_day[A: Hashable, I: Hashable](rows: Iterable[tuple[A, I, date]]) -> dict[tuple[I, date], int]:
    """``(actor, item, day)`` facts -> events per ``(item, day)``, each actor counted once per item and day."""
    seen = {(actor, item, day) for actor, item, day in rows}
    counts: dict[tuple[I, date], int] = defaultdict(int)
    for _actor, item, day in seen:
        counts[(item, day)] += 1
    return dict(counts)


def organisation_side(rows: Iterable[Aggregate], min_orgs: int) -> list[Aggregate]:
    """Organisation-side kinds count organisations, not people: an item and kind below ``min_orgs`` distinct
    organisations (``orgs`` is NULL below 3) is dropped, and the rest are weighted by ``orgs / actors`` with
    ``actors = orgs``."""
    kept = []
    for row in rows:
        if row.orgs is None or row.orgs < min_orgs or row.actors <= 0:
            continue
        share = min(1.0, row.orgs / row.actors)
        kept.append(replace(row, events=row.events * share, actors=row.orgs))
    return kept


def without_bursts(rows: Sequence[Aggregate], young_share: float) -> list[Aggregate]:
    """The burst detector: for an item and kind whose events come more than ``young_share`` from young accounts,
    the young accounts' events are ignored. Rows whose ``young`` count is unknown are kept as they are."""
    totals: dict[tuple[UUID, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for row in rows:
        if row.young is not None:
            total = totals[(row.item_id, row.kind)]
            total[0] += row.events
            total[1] += min(row.young, row.events)
    kept = []
    for row in rows:
        seen = totals.get((row.item_id, row.kind))
        if row.young is not None and seen is not None and seen[0] > 0 and seen[1] / seen[0] > young_share:
            remaining = row.events - min(row.young, row.events)
            if remaining > 0:
                kept.append(replace(row, events=remaining, young=0))
            continue
        kept.append(row)
    return kept


def decayed(events: Iterable[Event], decay: Decay, at: date) -> float:
    """``Σ w · count · 2^(-age/h)`` over the events of day ``at`` and before (age in whole days)."""
    total = 0.0
    for event in events:
        age = (at - event.day).days
        if age < 0:
            continue
        total += decay.weights.get(event.kind, 0.0) * event.count * 2.0 ** (-age / decay.half_life_days)
    return total


@dataclass(frozen=True, slots=True)
class _Baseline:
    mean: float
    sd: float


def _baselines(samples: Mapping[UUID | None, list[float]], cfg: TrendConfig) -> dict[UUID | None, _Baseline | None]:
    out: dict[UUID | None, _Baseline | None] = {}
    for niche, values in samples.items():
        if sum(1 for v in values if v > 0) < cfg.min_baseline_samples:
            out[niche] = None
            continue
        mean = sum(values) / len(values)
        sd = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        out[niche] = _Baseline(mean, max(sd, cfg.sd_floor))
    return out


def trends(subjects: Iterable[Subject], decay: Decay, cfg: TrendConfig, now: datetime) -> dict[UUID, Trend]:
    """Every subject's trend at ``now``: score, z-score against its niche's baseline, Trending and New this week."""
    today = nairobi_day(now)
    steps = [
        today - timedelta(days=k * cfg.baseline_step_days)
        for k in range(1, 1 + cfg.baseline_days // cfg.baseline_step_days)
    ]
    listed = list(subjects)
    scores: dict[UUID, float] = {}
    samples: dict[UUID | None, list[float]] = defaultdict(list)
    for subject in listed:
        scores[subject.id] = decayed(subject.events, decay, today)
        since = None if subject.published_at is None else nairobi_day(subject.published_at)
        samples[subject.niche_id].extend(
            decayed(subject.events, decay, at) for at in steps if since is None or since <= at
        )
    baselines = _baselines(samples, cfg)
    out = {}
    for subject in listed:
        score = scores[subject.id]
        base = baselines.get(subject.niche_id)
        z = None if base is None else round((score - base.mean) / base.sd, 3) + 0.0  # never -0.0
        trending = z is not None and z >= cfg.z_trending and score >= cfg.min_score and subject.actors >= cfg.min_actors
        new = subject.published_at is not None and now - subject.published_at <= timedelta(days=cfg.new_days)
        out[subject.id] = Trend(round(score, 3), z, trending, new, subject.actors)
    return out
