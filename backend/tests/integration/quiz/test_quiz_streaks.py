"""REQ-DEV-01 (D-59; P22 card A test A7): streaks on the test clock, kept when an attempt finishes.

Monday and Tuesday played: a streak of 2. Wednesday missed: on Thursday the streak shows 0 and the best 2; Thursday
played: 1, best 2. A streak shows on ``GET /today`` and in the finish response; nobody else's play changes it.
"""

from __future__ import annotations

from datetime import timedelta

from tests.integration.quiz.api_world import (
    KEY,
    TODAY,
    Clients,
    QuizDb,
    approved_set,
    at,
    cast,
    owner_rows,
    play,
)


async def test_consecutive_days_count_a_gap_resets_and_the_best_is_kept(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    p = await cast(quiz)
    days = [monday + timedelta(days=n) for n in range(4)]
    sets = {day: (await approved_set(quiz, day, p.admin))[0] for day in days}
    dev, other = await as_user(p.developer), await as_user(p.other)
    seen = []
    for day in (days[0], days[1], days[3]):  # Wednesday missed
        await at(quiz, day)
        seen.append((await dev.get(TODAY)).json()["streak"])
        seen.append((await play(dev, sets[day], list(KEY))).json()["streak"])
    assert seen == [
        {"current": 0, "best": 0},
        {"current": 1, "best": 1},
        {"current": 1, "best": 1},  # Tuesday morning: Monday's streak is alive
        {"current": 2, "best": 2},
        {"current": 0, "best": 2},  # Thursday: Wednesday was missed
        {"current": 1, "best": 2},
    ]
    assert (await play(other, sets[days[3]], [0] * 5)).json()["streak"] == {"current": 1, "best": 1}
    [row] = await owner_rows(
        quiz,
        "SELECT current_streak, best_streak, last_played_on, leaderboard_opt_in FROM quiz_profiles WHERE user_id = :u",
        u=p.developer,
    )
    assert tuple(row) == (1, 2, days[3], False)
