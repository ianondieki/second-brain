"""REQ-DEV-01 (D-59; P22 card A test A4): flags on Today's five.

- A developer flags a question of a set they played (403 ``play_first`` before), once (409 ``already_flagged``), with
  a reason and an optional one-line note of at most 300 characters (422 otherwise); a question the caller cannot read
  (of a draft, of a set approved ahead of its day, or none) is 404, never 403; at most 10 flags a Nairobi day (429
  ``flag_limit``), the next day's are open again.
- Three flags from new accounts never pull a question; three from established accounts (a verified email and three
  attempts on earlier days) pull it: every attempt of the set is rescored (those who had it right lose a point), the
  question's row says ``three_flags``, the developer sees it withdrawn, and the audit trail has
  ``quiz.question_pulled`` from the system with the reason ``flags`` (never the note).
- A staff restore rescores again (audited ``quiz.question_restored``), and later flags never pull it again.
"""

from __future__ import annotations

from datetime import time, timedelta
from uuid import UUID

from bridge.ids import uuid7
from tests.integration.quiz.api_world import (
    ADMIN,
    KEY,
    TODAY,
    Clients,
    QuizDb,
    approved_set,
    at,
    audit_actions,
    cast,
    code,
    developers,
    draft_set,
    established,
    flag_path,
    owner_attempt,
    owner_rows,
    play,
    question_ids,
    scores,
)

WRONG_FIRST = [2, *KEY[1:]]  # every answer right but the first


async def test_a_flag_needs_a_played_set_and_is_taken_once(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    await at(quiz, monday)
    p = await cast(quiz)
    set_id, ids = await approved_set(quiz, monday, p.admin)
    draft = await draft_set(quiz, monday + timedelta(days=1), role="job")
    [draft_question, *_] = await question_ids(quiz, draft)
    dev = await as_user(p.developer)
    assert code(await dev.post(flag_path(ids[0]), json={"reason": "wrong_answer"})) == (403, "play_first")
    assert (await play(dev, set_id, list(KEY))).status_code == 201
    for body in (
        {"reason": "spam"},
        {"reason": "unclear", "note": "x" * 301},
        {"reason": "unclear", "note": "bell \u0007 here"},
        {"reason": "unclear", "extra": True},
    ):
        assert (await dev.post(flag_path(ids[0]), json=body)).status_code == 422, body
    taken = await dev.post(flag_path(ids[0]), json={"reason": "unclear", "note": "  Two  options\nlook alike. "})
    assert taken.status_code == 201, taken.text
    assert taken.json()["pulled"] is False
    assert code(await dev.post(flag_path(ids[0]), json={"reason": "outdated"})) == (409, "already_flagged")
    assert code(await dev.post(flag_path(draft_question), json={"reason": "unclear"})) == (404, "not_found")
    _, ahead_ids = await approved_set(quiz, monday + timedelta(days=2), p.admin)  # approved, not yet served
    assert code(await dev.post(flag_path(ahead_ids[0]), json={"reason": "unclear"})) == (404, "not_found")
    assert code(await dev.post(flag_path(uuid7()), json={"reason": "unclear"})) == (404, "not_found")
    flags = await owner_rows(
        quiz, "SELECT id, question_id, reason, note FROM quiz_flags WHERE user_id = :u", u=p.developer
    )
    assert [(f.id, f.question_id, f.reason, f.note) for f in flags] == [
        (UUID(taken.json()["flag_id"]), ids[0], "unclear", "Two options look alike.")
    ]
    assert await audit_actions(quiz, ids[0]) == []  # a flag that pulls nothing writes no audit event


async def test_ten_flags_a_day(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    wednesday = monday + timedelta(days=2)
    await at(quiz, wednesday, time(10, 0))
    p = await cast(quiz)
    dev = await as_user(p.developer)
    questions = []
    for back in (1, 2):
        past, ids = await approved_set(quiz, wednesday - timedelta(days=back), p.admin)
        await owner_attempt(quiz, past, p.developer)
        questions += ids
    today, ids = await approved_set(quiz, wednesday, p.admin)
    assert (await play(dev, today, list(KEY))).status_code == 201
    questions += ids
    for question in questions[:10]:
        assert (await dev.post(flag_path(question), json={"reason": "other"})).status_code == 201
    assert code(await dev.post(flag_path(questions[10]), json={"reason": "other"})) == (429, "flag_limit")
    await at(quiz, wednesday + timedelta(days=1), time(0, 1))  # a new Nairobi day
    assert (await dev.post(flag_path(questions[10]), json={"reason": "other"})).status_code == 201


async def test_established_flags_pull_and_rescore_and_a_restore_is_final(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    thursday = monday + timedelta(days=3)
    await at(quiz, thursday)
    p = await cast(quiz)
    newcomers = await developers(quiz, "new", 3)
    regulars = await developers(quiz, "regular", 4)
    await established(quiz, thursday, p.admin, regulars)
    set_id, ids = await approved_set(quiz, thursday, p.admin)
    right, wrong = await as_user(p.developer), await as_user(p.other)
    assert (await play(right, set_id, list(KEY))).json()["attempt"]["score"] == 5
    assert (await play(wrong, set_id, WRONG_FIRST)).json()["attempt"]["score"] == 4
    flaggers = {}
    for user in (*newcomers, *regulars):
        flaggers[user] = await as_user(user)
        assert (await play(flaggers[user], set_id, list(KEY))).status_code == 201
    for user in newcomers:  # new accounts: their flags reach staff but never pull
        assert (await flaggers[user].post(flag_path(ids[0]), json={"reason": "wrong_answer"})).json()["pulled"] is False
    assert (await scores(quiz, set_id))[p.developer] == 5
    pulled = [
        (await flaggers[user].post(flag_path(ids[0]), json={"reason": "wrong_answer", "note": "Secret"})).json()[
            "pulled"
        ]
        for user in regulars[:3]
    ]
    assert pulled == [False, False, True]
    after = await scores(quiz, set_id)
    assert (after[p.developer], after[p.other]) == (4, 4)  # who had it right lost a point; who had it wrong did not
    assert all(after[user] == 4 for user in (*newcomers, *regulars))
    [row] = await owner_rows(quiz, "SELECT status, pulled_reason FROM quiz_questions WHERE id = :q", q=ids[0])
    assert tuple(row) == ("pulled", "three_flags")
    [event] = await audit_actions(quiz, ids[0])
    assert (event.action, event.actor_kind, event.actor_user_id) == ("quiz.question_pulled", "system", None)
    assert event.payload == {"set_id": str(set_id), "reason": "flags"}  # the notes stay out of the audit trail
    seen = (await right.get(TODAY)).json()
    assert (seen["questions"][0]["pulled"], seen["attempt"]["correct"][0]) == (True, None)
    assert (seen["attempt"]["score"], seen["attempt"]["out_of"]) == (4, 4)
    assert code(await flaggers[regulars[3]].post(flag_path(ids[0]), json={"reason": "other"})) == (
        409,
        "question_pulled",
    )

    admin = await as_user(p.admin)
    restored = await admin.post(f"{ADMIN}/questions/{ids[0]}/restore")
    assert restored.json() == {"question_id": str(ids[0]), "set_id": str(set_id), "status": "live", "rescored": 8}
    assert (await scores(quiz, set_id))[p.developer] == 5
    assert [e.action for e in await audit_actions(quiz, ids[0])] == ["quiz.question_pulled", "quiz.question_restored"]
    late = await flaggers[regulars[3]].post(flag_path(ids[0]), json={"reason": "wrong_answer"})
    assert late.json()["pulled"] is False  # a staff restore is never overturned by flags
    [row] = await owner_rows(
        quiz, "SELECT status, restored_at IS NOT NULL AS restored FROM quiz_questions WHERE id = :q", q=ids[0]
    )
    assert tuple(row) == ("live", True)
