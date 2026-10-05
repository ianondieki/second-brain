"""REQ-DEV-01 (D-59; P22 card A test A7, the code half): a streak counts consecutive days that had an approved set
played; a day with no approved set is skipped (it breaks nobody's streak); a day with a set the developer did not play
resets it; the best streak is kept; a streak with a missed set since its last day shows as 0."""

from __future__ import annotations

from datetime import date, timedelta

from bridge.quiz.streaks import Streak, after_playing, shown

MONDAY = date(2026, 10, 5)


def day(n: int) -> date:
    return MONDAY + timedelta(days=n)


def test_a_first_play_starts_a_streak_of_one() -> None:
    assert after_playing(None, MONDAY, missed=0) == Streak(1, 1, MONDAY)
    assert after_playing(Streak(), MONDAY, missed=0) == Streak(1, 1, MONDAY)


def test_consecutive_days_count() -> None:
    streak = None
    for n in range(4):
        streak = after_playing(streak, day(n), missed=0)
    assert streak == Streak(4, 4, day(3))


def test_a_day_without_an_approved_set_is_skipped() -> None:
    """Monday to Wednesday played, no set on Thursday, Friday played: a streak of 4."""
    streak = None
    for n in range(3):
        streak = after_playing(streak, day(n), missed=0)
    assert after_playing(streak, day(4), missed=0) == Streak(4, 4, day(4))
    assert shown(Streak(3, 3, day(2)), day(4), missed=0) == (3, 3)  # Friday, before playing: still alive


def test_a_missed_set_resets_and_the_best_is_kept() -> None:
    streak = None
    for n in range(3):
        streak = after_playing(streak, day(n), missed=0)
    assert after_playing(streak, day(4), missed=1) == Streak(1, 3, day(4))  # Thursday had a set, not played
    assert after_playing(Streak(2, 5, day(0)), day(1), missed=0) == Streak(3, 5, day(1))


def test_the_same_day_twice_changes_nothing_and_a_day_before_the_last_starts_again() -> None:
    assert after_playing(Streak(2, 2, day(1)), day(1), missed=0) == Streak(2, 2, day(1))
    assert after_playing(Streak(2, 4, day(5)), day(1), missed=0) == Streak(1, 4, day(1))  # a clock moved back


def test_shown_is_the_live_streak_or_zero_and_the_best() -> None:
    assert shown(None, MONDAY, missed=0) == (0, 0)
    assert shown(Streak(), MONDAY, missed=0) == (0, 0)
    assert shown(Streak(3, 4, day(2)), day(2), missed=0) == (3, 4)  # played today
    assert shown(Streak(3, 4, day(2)), day(3), missed=0) == (3, 4)  # played yesterday: still alive today
    assert shown(Streak(3, 4, day(2)), day(4), missed=1) == (0, 4)  # Thursday's set missed: over
    assert shown(Streak(3, 4, day(5)), day(2), missed=0) == (0, 4)  # a clock moved back
