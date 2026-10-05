"""REQ-DEV-01 (D-59; P22 card A test A5): this week's board, ``GET /api/me/quiz/leaderboard``.

On the test clock: the ISO week (Monday to Sunday in Nairobi) of the current day; the points of opted-in developers
only, by points then less time (equal points and time share a rank), by handle; demo accounts never show to a real
caller (a demo caller sees the demo people); the caller's own points and rank also when not opted in (null rank
when they did not play this week); the first 20 rows only; the board starts again each week. The board is one
statement, however many people played.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from tests.integration.query_counts import statements
from tests.integration.quiz.api_world import (
    BOARD,
    KEY,
    SETTINGS,
    Clients,
    QuizDb,
    approved_set,
    at,
    cast,
    developers,
    handle_of,
    owner_attempt,
    owner_run,
)

Answers = list[int | None]
FIVE: Answers = list(KEY)
THREE: Answers = [*KEY[:3], None, None]
TWO: Answers = [*KEY[:2], None, None, None]


async def opt_in(quiz: QuizDb, users: Sequence[UUID]) -> None:
    for user in users:
        await owner_run(quiz, "INSERT INTO quiz_profiles (user_id, leaderboard_opt_in) VALUES (:u, true)", u=user)


def rows(body: dict[str, Any]) -> list[tuple[int, str, int, bool]]:
    return [(r["rank"], r["handle"], r["points"], r["you"]) for r in body["rows"]]


async def test_the_board_is_this_weeks_opted_in_developers_of_the_callers_kind(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    sunday, next_monday = monday + timedelta(days=6), monday + timedelta(days=7)
    p = await cast(quiz)
    sets = {
        day: (await approved_set(quiz, day, p.admin))[0]
        for day in (monday - timedelta(days=1), monday, sunday, next_monday)
    }
    a, b, c, c2, demo, demo2, e, f = await developers(quiz, "board", 8)
    await owner_run(quiz, "UPDATE users SET demo_account = true WHERE id = ANY(:u)", u=[demo, demo2])
    plays: list[tuple[UUID, date, Answers, int]] = [
        (a, monday, FIVE, 50_000), (a, sunday, THREE, 20_000),  # 8 points, 70 s
        (b, monday, FIVE, 30_000), (b, sunday, THREE, 30_000),  # 8 points, 60 s: before a
        (c, monday, TWO, 10_000), (c2, monday, TWO, 10_000),  # 2 points each, the same time: one rank
        (c, monday - timedelta(days=1), FIVE, 1), (c, next_monday, FIVE, 1),  # last and next week: not this one
        (demo, monday, FIVE, 1), (demo2, sunday, TWO, 1),
        (e, monday, FIVE, 40_000), (e, sunday, FIVE, 40_000),  # 10 points, not opted in
    ]  # fmt: skip
    for user, day, answers, ms in plays:
        await owner_attempt(quiz, sets[day], user, answers, ms)
    await opt_in(quiz, [b, c, c2, demo, demo2, f])
    await at(quiz, monday + timedelta(days=2))  # Wednesday
    handles = {user: await handle_of(quiz, user) for user in (a, b, c, c2, demo, demo2, e, f)}
    first = await as_user(a)
    assert (await first.put(SETTINGS, json={"leaderboard_opt_in": True})).json() == {"leaderboard_opt_in": True}
    body = (await first.get(BOARD)).json()
    assert (body["week_start"], body["week_end"]) == (monday.isoformat(), sunday.isoformat())
    shared = sorted([handles[c], handles[c2]])
    assert rows(body) == [
        (1, handles[b], 8, False),
        (2, handles[a], 8, True),
        (3, shared[0], 2, False),
        (3, shared[1], 2, False),
    ]
    assert body["me"] == {"points": 8, "rank": 2, "opted_in": True, "played": True}
    outsider = (await (await as_user(e)).get(BOARD)).json()  # not opted in: not listed, their own numbers shown
    assert [r[1] for r in rows(outsider)] == [handles[b], handles[a], *shared]
    assert outsider["me"] == {"points": 10, "rank": 1, "opted_in": False, "played": True}
    idle = (await (await as_user(f)).get(BOARD)).json()
    assert idle["me"] == {"points": 0, "rank": None, "opted_in": True, "played": False}
    demo_board = (await (await as_user(demo)).get(BOARD)).json()  # the demo shows its own people only
    assert rows(demo_board) == [(1, handles[demo], 5, True), (2, handles[demo2], 2, False)]
    off = await first.put(SETTINGS, json={"leaderboard_opt_in": False})
    assert off.json() == {"leaderboard_opt_in": False}
    assert [r[1] for r in rows((await first.get(BOARD)).json())] == [handles[b], *shared]
    await at(quiz, next_monday)  # a new week: the board starts again
    later = (await (await as_user(b)).get(BOARD)).json()
    assert rows(later) == [(1, handles[c], 5, False)]
    assert later["me"] == {"points": 0, "rank": None, "opted_in": True, "played": False}


async def test_the_board_lists_twenty_in_one_statement(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    p = await cast(quiz)
    set_id, _ = await approved_set(quiz, monday, p.admin)
    await at(quiz, monday)
    few = await developers(quiz, "few", 2)
    for n, user in enumerate(few):
        await owner_attempt(quiz, set_id, user, FIVE, 1000 + n)
    await opt_in(quiz, few)
    last = await as_user(few[-1])
    with statements(quiz.app) as seen:
        small = await last.get(BOARD)
    assert rows(small.json())[-1][3] is True
    many = await developers(quiz, "many", 20)
    for n, user in enumerate(many):
        await owner_attempt(quiz, set_id, user, FIVE, 10 + n)  # all faster than the first two
    await opt_in(quiz, many)
    with statements(quiz.app) as seen_large:
        large = await last.get(BOARD)
    body = large.json()
    assert len(body["rows"]) == 20
    assert not any(r["you"] for r in body["rows"])  # the caller is 22nd: not listed, their rank given
    assert body["me"] == {"points": 5, "rank": 22, "opted_in": True, "played": True}
    assert len(seen_large) == len(seen)
    assert [s for s in seen_large if "app_quiz_board" in s] == [s for s in seen if "app_quiz_board" in s]
    assert len([s for s in seen_large if "app_quiz_board" in s]) == 1
