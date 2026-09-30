"""P12 demo seed (``bridge.seed.demo.trending``): simulated signals are keyed and timed by their Nairobi date, so runs
a week apart never add a second signal for the same proposal, kind, organisation and date (review MINOR 5)."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from bridge.seed.demo.data import P1, P2, P3, P4
from bridge.seed.demo.runtime import DemoReport
from bridge.seed.demo.trending import NAIROBI, SIGNALS, signal_rows

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def report() -> DemoReport:
    r = DemoReport()
    r.proposals.update({p.key: uuid4() for p in (P1, P2, P3, P4)})
    return r


def test_runs_a_week_apart_share_their_common_dates_and_never_pile_up() -> None:
    r = report()
    first, again, later = (
        signal_rows(r, NOW),
        signal_rows(r, NOW + timedelta(hours=3)),
        signal_rows(r, NOW + timedelta(days=7)),
    )
    assert [row["id"] for row in again] == [row["id"] for row in first]  # the same day: nothing new
    union = {row["id"]: row for row in [*first, *later]}
    per_date: dict[tuple[object, ...], set[object]] = defaultdict(set)
    for row in union.values():
        when = row["ts"]
        assert isinstance(when, datetime)
        per_date[(row["item"], row["kind"], row["org"], when.astimezone(NAIROBI).date())].add(row["id"])
    assert all(len(ids) == 1 for ids in per_date.values())
    shared = {row["id"] for row in first} & {row["id"] for row in later}
    assert len(shared) > len(first) // 2  # the weekly history mostly lands on dates the first run covered
    assert len(union) < 2 * len(first)


def test_no_signal_is_in_the_future_and_every_kind_has_three_organisations() -> None:
    rows = signal_rows(report(), NOW)
    assert all(isinstance(row["ts"], datetime) and row["ts"] < NOW for row in rows)
    assert all(plan.orgs >= 3 for plan in SIGNALS)
