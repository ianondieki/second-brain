"""REQ-DEV-01 (D-59; P22 card A tests A2 and A3, the developer's half, and A6's routes): playing Today's five.

- Only an approved set of the current Nairobi day is served: a draft and a rejected set answer 404 ``no_quiz``.
- The questions come without answers or whys until the caller finished; one attempt per developer per set (409
  ``already_played``), its answers validated (422, nothing written), its score the database's from the live questions
  (deterministic from fixed answers); the response carries the key, the whys, the sources and the streak.
- A set whose day ended on the shared clock is 409 ``set_closed``; an unknown or draft set id is 404 ``no_quiz``.
- An organisation-only account and staff (even with a developer profile) get 404 on every route, signed out 401; a
  demo account plays; another developer's attempt is never shown.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from bridge.ids import uuid7
from tests.integration.api import make_client
from tests.integration.quiz.api_world import (
    ANSWERS,
    BOARD,
    KEY,
    SETTINGS,
    TODAY,
    Clients,
    QuizDb,
    approved_set,
    at,
    cast,
    code,
    decide,
    draft_set,
    flag_path,
    owner_rows,
    owner_run,
    play,
)


@pytest.fixture(scope="module")
def shared_week(quiz: QuizDb) -> date:
    return quiz.monday()


ROUTES: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("GET", TODAY, None),
    ("POST", ANSWERS, {"set_id": str(uuid7()), "answers": [0, 0, 0, 0, 0], "time_ms": 1}),
    ("POST", flag_path(uuid7()), {"reason": "unclear"}),
    ("GET", BOARD, None),
    ("PUT", SETTINGS, {"leaderboard_opt_in": True}),
)


async def test_only_an_approved_set_of_today_is_served(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    await at(quiz, monday)
    p = await cast(quiz)
    dev = await as_user(p.developer)
    assert code(await dev.get(TODAY)) == (404, "no_quiz")
    draft = await draft_set(quiz, monday, role="job")
    assert code(await dev.get(TODAY)) == (404, "no_quiz")  # a draft is never served
    await decide(quiz, draft, p.admin, "rejected")
    assert code(await dev.get(TODAY)) == (404, "no_quiz")
    await approved_set(quiz, monday + timedelta(days=1), p.admin)  # tomorrow's, approved: not served ahead
    assert code(await dev.get(TODAY)) == (404, "no_quiz")
    set_id, ids = await approved_set(quiz, monday, p.admin)
    body = (await dev.get(TODAY)).json()
    assert (body["set_id"], body["quiz_date"], body["attempt"]) == (str(set_id), monday.isoformat(), None)
    assert (body["streak"], body["leaderboard_opt_in"]) == ({"current": 0, "best": 0}, False)
    assert [q["id"] for q in body["questions"]] == [str(i) for i in ids]
    first = body["questions"][0]
    assert (first["position"], first["options"], first["topic"], first["pulled"]) == (
        1,
        ["Alpha", "Beta", "Gamma", "Delta"],
        "python",
        False,
    )
    assert first["source"] == {
        "id": "python-datamodel",
        "title": "Python Language Reference: Data model",
        "url": "https://docs.python.org/3/reference/datamodel.html",
    }
    assert all((q["answer"], q["why"]) == (None, None) for q in body["questions"])  # withheld before playing


async def test_one_attempt_scored_from_the_live_questions_with_the_key_after(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    await at(quiz, monday, time(9, 15))
    p = await cast(quiz)
    set_id, ids = await approved_set(quiz, monday, p.admin, KEY)  # (1, 2, 3, 0, 1)
    dev, other = await as_user(p.developer), await as_user(p.other)
    finished = await play(dev, set_id, [1, 2, 0, None, 1], ms=41_500)
    assert finished.status_code == 201, finished.text
    body = finished.json()
    attempt = body["attempt"]
    assert (attempt["answers"], attempt["score"], attempt["out_of"], attempt["time_ms"]) == (
        [1, 2, 0, None, 1],
        3,
        5,
        41_500,
    )
    assert attempt["correct"] == [True, True, False, False, True]
    assert [q["answer"] for q in body["questions"]] == list(KEY)
    assert [q["why"] for q in body["questions"]] == [
        f"The page says option {a} for question {n}." for n, a in enumerate(KEY, start=1)
    ]
    assert body["streak"] == {"current": 1, "best": 1}
    again = (await dev.get(TODAY)).json()
    assert again["attempt"] == attempt
    assert [q["answer"] for q in again["questions"]] == list(KEY)
    assert code(await play(dev, set_id, list(KEY))) == (409, "already_played")
    stored = await owner_rows(
        quiz, "SELECT user_id, answers, score, time_ms FROM quiz_attempts WHERE set_id = :s", s=set_id
    )
    assert [tuple(row) for row in stored] == [(p.developer, [1, 2, 0, None, 1], 3, 41_500)]
    mine = (await other.get(TODAY)).json()  # another developer: their own state only
    assert (mine["attempt"], [q["answer"] for q in mine["questions"]]) == (None, [None] * 5)
    assert (await play(other, set_id, list(KEY))).json()["attempt"]["score"] == 5
    assert [q["id"] for q in body["questions"]] == [str(i) for i in ids]


@pytest.mark.parametrize(
    "change",
    [
        {"answers": [0, 0, 0, 0]},
        {"answers": [0, 0, 0, 0, 0, 0]},
        {"answers": [0, 0, 0, 0, 4]},
        {"answers": [-1, 0, 0, 0, 0]},
        {"answers": ["1", 0, 0, 0, 0]},
        {"answers": [1.5, 0, 0, 0, 0]},
        {"answers": [True, 0, 0, 0, 0]},
        {"time_ms": -1},
        {"time_ms": 86_400_001},
        {"time_ms": "10"},
        {"set_id": None},
        {"extra": 1},
    ],
    ids=lambda change: str(change),
)
async def test_answers_are_validated_and_nothing_is_written(
    quiz: QuizDb, as_user: Clients, shared_week: date, change: dict[str, Any]
) -> None:
    monday = shared_week  # one week for every case of this test
    await at(quiz, monday)
    p = await cast(quiz)
    found = await owner_rows(quiz, "SELECT id FROM quiz_sets WHERE quiz_date = :d AND status = 'approved'", d=monday)
    set_id = found[0].id if found else (await approved_set(quiz, monday, p.admin))[0]
    dev = await as_user(p.developer)
    body = {"set_id": str(set_id), "answers": [0, 0, 0, 0, 0], "time_ms": 1000} | change
    if change.get("set_id", "") is None:
        del body["set_id"]
    assert (await dev.post(ANSWERS, json=body)).status_code == 422
    assert await owner_rows(quiz, "SELECT id FROM quiz_attempts WHERE user_id = :u", u=p.developer) == []
    assert await owner_rows(quiz, "SELECT user_id FROM quiz_profiles WHERE user_id = :u", u=p.developer) == []


async def test_a_set_whose_day_ended_is_closed_and_unknown_or_draft_sets_are_not_found(
    quiz: QuizDb, as_user: Clients
) -> None:
    monday = quiz.monday()
    await at(quiz, monday, time(23, 59))
    p = await cast(quiz)
    set_id, _ = await approved_set(quiz, monday, p.admin)
    tomorrow = await draft_set(quiz, monday + timedelta(days=1), role="job")
    dev = await as_user(p.developer)
    served = (await dev.get(TODAY)).json()
    assert served["set_id"] == str(set_id)
    await at(quiz, monday + timedelta(days=1), time(0, 1))  # midnight in Nairobi passed while they played
    assert code(await play(dev, set_id, list(KEY))) == (409, "set_closed")
    assert code(await play(dev, uuid7(), list(KEY))) == (404, "no_quiz")
    assert code(await play(dev, tomorrow, list(KEY))) == (404, "no_quiz")
    assert code(await dev.get(TODAY)) == (404, "no_quiz")
    assert await owner_rows(quiz, "SELECT id FROM quiz_attempts WHERE user_id = :u", u=p.developer) == []


async def test_only_developers_play_and_each_reads_their_own(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    await at(quiz, monday)
    p = await cast(quiz)
    set_id, ids = await approved_set(quiz, monday, p.admin)
    async with quiz.owner.begin() as conn:  # a staff member who also has a developer profile
        await conn.execute(
            text("INSERT INTO developer_profiles (user_id, handle) VALUES (:u, :h)"),
            {"u": p.moderator, "h": f"mod-{p.moderator.hex}"},
        )
    async with make_client(quiz.app) as anonymous:
        for method, path, body in ROUTES:
            assert (await anonymous.request(method, path, json=body)).status_code == 401, path
    for user in (p.org_only, p.admin, p.moderator):
        client = await as_user(user)
        for method, path, body in ROUTES:
            assert code(await client.request(method, path, json=body)) == (404, "not_found"), (user, path)
    await owner_run(quiz, "UPDATE users SET demo_account = true WHERE id = :u", u=p.fourth)
    demo = await as_user(p.fourth)
    assert (await play(demo, set_id, list(KEY))).status_code == 201  # demo accounts play (and never rank)
    dev = await as_user(p.developer)
    assert (await play(dev, set_id, [0] * 5)).status_code == 201
    assert (await dev.post(flag_path(ids[0]), json={"reason": "unclear"})).status_code == 201
    assert (await dev.put(SETTINGS, json={"leaderboard_opt_in": True})).json() == {"leaderboard_opt_in": True}
    async with quiz.app.connect() as conn:  # Row-Level Security: the other developer reads none of it
        await conn.execute(text("SELECT set_config('app.user_id', :u, false)"), {"u": str(p.other)})
        for table in ("quiz_attempts", "quiz_flags", "quiz_profiles"):
            assert (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0, table
        await conn.execute(text("SELECT set_config('app.user_id', :u, false)"), {"u": str(p.developer)})
        owned = "SELECT count(*) FROM {} WHERE user_id = :u"
        for table in ("quiz_attempts", "quiz_flags", "quiz_profiles"):
            total = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert total == (await conn.execute(text(owned.format(table)), {"u": p.developer})).scalar_one() == 1
