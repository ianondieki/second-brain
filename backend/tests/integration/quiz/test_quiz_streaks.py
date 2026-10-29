"""REQ-DEV-01 (D-59; P22 card A test A7): streaks on the test clock, kept when an attempt finishes.

A streak counts consecutive days that had an approved set played. Monday and Tuesday played: 2. Wednesday's draft was
rejected, so Wednesday had no set and breaks nothing: Thursday morning the streak still shows 2, and Thursday played
makes 3. Friday's set is missed: on Saturday the streak shows 0 and the best 3; Saturday played: 1, best 3. A streak
shows on ``GET /today`` and in the finish response; nobody else's play changes it.
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
    decide,
    draft_set,
    owner_rows,
    play,
)


async def test_consecutive_set_days_count_a_missed_set_resets_and_the_best_is_kept(
    quiz: QuizDb, as_user: Clients
) -> None:
    monday = quiz.monday()
    p = await cast(quiz)
    days = [monday + timedelta(days=n) for n in range(6)]  # Monday to Saturday
    wednesday = days[2]
    sets = {day: (await approved_set(quiz, day, p.admin))[0] for day in days if day != wednesday}
    await decide(quiz, await draft_set(quiz, wednesday), p.admin, "rejected")  # no set on Wednesday
    dev, other = await as_user(p.developer), await as_user(p.other)
    seen = []
    for day in (days[0], days[1], days[3], days[5]):  # Wednesday had no set; Friday's is missed
        await at(quiz, day)
        seen.append((await dev.get(TODAY)).json()["streak"])
        seen.append((await play(dev, sets[day], list(KEY))).json()["streak"])
    assert seen == [
        {"current": 0, "best": 0},
        {"current": 1, "best": 1},
        {"current": 1, "best": 1},  # Tuesday morning: Monday's streak is alive
        {"current": 2, "best": 2},
        {"current": 2, "best": 2},  # Thursday morning: Wednesday had no set, so nothing was missed
        {"current": 3, "best": 3},
        {"current": 0, "best": 3},  # Saturday: Friday's set was missed
        {"current": 1, "best": 3},
    ]
    assert (await play(other, sets[days[5]], [0] * 5)).json()["streak"] == {"current": 1, "best": 1}
    [row] = await owner_rows(
        quiz,
        "SELECT current_streak, best_streak, last_played_on, leaderboard_opt_in FROM quiz_profiles WHERE user_id = :u",
        u=p.developer,
    )
    assert tuple(row) == (1, 3, days[5], False)
