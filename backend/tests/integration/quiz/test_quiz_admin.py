"""REQ-DEV-01, REQ-ADM-01 (D-59; P22 card A tests A2 and A6, the staff half): ``/api/admin/quiz/*``.

- Staff admin with a fresh second factor only: signed out and a developer 404, a moderator 403, a stale second
  factor 403 ``step_up_required``.
- The queue lists sets newest day first with their flag and pull counts (``status`` filters); a set's page has the
  answers, whys, sources, the flags by reason with their notes (never who flagged), who decided it and when, its
  generating call, and its attempts in aggregate only from three attempts on.
- One decision per set (409 ``already_decided``), an approval needs five questions (409 ``incomplete_set``), audited
  ``quiz.set_decided``; a rejected set is never served.
- Pull and restore rescore the set's attempts, each audited with the number of scores changed; the same state again
  is 409; a reason is one line of 1 to 300 characters.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import text

from bridge.db import create_session_factory
from bridge.ids import uuid7
from bridge.quiz.store import store_draft
from tests.integration.api import make_client
from tests.integration.quiz.api_world import (
    ADMIN,
    KEY,
    NO_REPEAT_DAYS,
    TODAY,
    Clients,
    QuizDb,
    accepted_set,
    approved_set,
    at,
    audit_actions,
    cast,
    code,
    draft_set,
    flag_path,
    owner_attempt,
    owner_rows,
    play,
    question_ids,
    scores,
)

ROUTES: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("GET", "/sets", None),
    ("GET", f"/sets/{uuid7()}", None),
    ("POST", f"/sets/{uuid7()}/decision", {"decision": "approve"}),
    ("POST", f"/questions/{uuid7()}/pull", {"reason": "Wrong key"}),
    ("POST", f"/questions/{uuid7()}/restore", None),
)


async def test_every_route_is_staff_admin_only_with_a_fresh_second_factor(quiz: QuizDb, as_user: Clients) -> None:
    p = await cast(quiz)
    developer, moderator = await as_user(p.developer), await as_user(p.moderator)
    stale = await as_user(p.admin, fresh=False)
    async with make_client(quiz.app) as anonymous:
        for method, path, body in ROUTES:
            assert (await anonymous.request(method, ADMIN + path, json=body)).status_code == 404, path
    for method, path, body in ROUTES:
        assert (await developer.request(method, ADMIN + path, json=body)).status_code == 404, path
        assert (await moderator.request(method, ADMIN + path, json=body)).status_code == 403, path
        assert code(await stale.request(method, ADMIN + path, json=body)) == (403, "step_up_required"), path


async def test_one_audited_decision_per_set_and_only_approved_sets_are_served(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    await at(quiz, monday)
    p = await cast(quiz)
    admin, dev = await as_user(p.admin), await as_user(p.developer)
    today = await draft_set(quiz, monday, role="job")
    queue = (await admin.get(f"{ADMIN}/sets", params={"status": "draft"})).json()["items"]
    assert [item["id"] for item in queue] == [str(today)]
    assert code(await dev.get(TODAY)) == (404, "no_quiz")
    rejected = await admin.post(f"{ADMIN}/sets/{today}/decision", json={"decision": "reject"})
    assert (rejected.json()["status"], rejected.json()["quiz_date"]) == ("rejected", monday.isoformat())
    assert code(await admin.post(f"{ADMIN}/sets/{today}/decision", json={"decision": "approve"})) == (
        409,
        "already_decided",
    )
    assert code(await dev.get(TODAY)) == (404, "no_quiz")  # a rejected set is never served
    again = await draft_set(quiz, monday, role="job")  # the day is free again
    approved = await admin.post(f"{ADMIN}/sets/{again}/decision", json={"decision": "approve"})
    assert approved.json()["status"] == "approved"
    assert (await dev.get(TODAY)).json()["set_id"] == str(again)
    for set_id, decision in ((today, "rejected"), (again, "approved")):
        [event] = await audit_actions(quiz, set_id)
        assert (event.action, event.actor_kind, event.actor_user_id) == ("quiz.set_decided", "staff", p.admin)
        assert event.payload == {"decision": decision, "quiz_date": monday.isoformat(), "origin": "model"}
    async with create_session_factory(quiz.app)() as db:  # the job writes a set and then fails before question 5
        short = uuid7()
        await db.execute(
            text("INSERT INTO quiz_sets (id, quiz_date, origin, llm_trace_id) VALUES (:s, :d, 'model', 't')"),
            {"s": short, "d": monday + timedelta(days=1)},
        )
        await db.commit()
    assert code(await admin.post(f"{ADMIN}/sets/{short}/decision", json={"decision": "approve"})) == (
        409,
        "incomplete_set",
    )
    assert code(await admin.post(f"{ADMIN}/sets/{uuid7()}/decision", json={"decision": "approve"})) == (
        404,
        "not_found",
    )
    assert (await admin.post(f"{ADMIN}/sets/{today}/decision", json={"decision": "maybe"})).status_code == 422


async def test_the_queue_and_a_sets_page(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    tuesday = monday + timedelta(days=1)
    await at(quiz, monday)
    p = await cast(quiz)
    admin = await as_user(p.admin)
    set_id, ids = await approved_set(quiz, monday, p.admin)
    async with create_session_factory(quiz.app)() as db:
        await store_draft(
            db, tuesday, accepted_set(), origin="model", trace_id="quiz:tue:2", no_repeat_days=NO_REPEAT_DAYS
        )
    for user, answers in ((p.developer, list(KEY)), (p.other, [*KEY[:4], None])):
        client = await as_user(user)
        await play(client, set_id, answers)
        await client.post(flag_path(ids[1]), json={"reason": "unclear", "note": f"Note of {user.hex[:6]}"})
    await owner_attempt(quiz, set_id, p.third)  # a third attempt: the aggregates show
    await (await as_user(p.developer)).post(flag_path(ids[2]), json={"reason": "outdated"})
    listed = (await admin.get(f"{ADMIN}/sets")).json()["items"]
    mine = [item for item in listed if item["quiz_date"] in (monday.isoformat(), tuesday.isoformat())]
    assert [(i["quiz_date"], i["status"], i["origin"], i["flags"], i["pulled"]) for i in mine] == [
        (tuesday.isoformat(), "draft", "model", 0, 0),
        (monday.isoformat(), "approved", "seeded", 3, 0),
    ]
    only = (await admin.get(f"{ADMIN}/sets", params={"status": "approved"})).json()["items"]
    assert {i["status"] for i in only} == {"approved"}
    assert str(set_id) in [i["id"] for i in only]
    assert (await admin.get(f"{ADMIN}/sets", params={"status": "live"})).status_code == 422
    page = (await admin.get(f"{ADMIN}/sets/{set_id}")).json()
    assert (page["decided_by"], page["llm_trace_id"], page["status"]) == (str(p.admin), None, "approved")
    assert page["decided_at"] is not None
    assert page["stats"] == {"attempts": 3, "average_score": "3.00", "per_question_correct": [2, 2, 2, 2, 1]}
    second = page["questions"][1]
    assert (second["answer"], second["why"], second["flags"], second["flag_reasons"]) == (
        KEY[1],
        f"The page says option {KEY[1]} for question 2.",
        2,
        {"unclear": 2},
    )
    assert sorted(n["note"] for n in second["notes"]) == sorted(f"Note of {u.hex[:6]}" for u in (p.developer, p.other))
    assert "user_id" not in str(second["notes"])
    assert page["questions"][2]["flag_reasons"] == {"outdated": 1}
    assert page["questions"][0]["source_url"] == "https://docs.python.org/3/reference/datamodel.html"
    drafted = (await admin.get(f"{ADMIN}/sets", params={"status": "draft"})).json()["items"][0]["id"]
    early = (await admin.get(f"{ADMIN}/sets/{drafted}")).json()
    assert (early["llm_trace_id"], early["decided_by"], early["stats"]) == (
        "quiz:tue:2",
        None,
        {"attempts": 0, "average_score": None, "per_question_correct": None},
    )
    assert code(await admin.get(f"{ADMIN}/sets/{uuid7()}")) == (404, "not_found")


async def test_pull_and_restore_rescore_and_are_audited(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    await at(quiz, monday)
    p = await cast(quiz)
    admin = await as_user(p.admin)
    set_id, ids = await approved_set(quiz, monday, p.admin)
    await play(await as_user(p.developer), set_id, list(KEY))
    await play(await as_user(p.other), set_id, [None, *KEY[1:]])
    for body in ({"reason": "  "}, {"reason": "x" * 301}, {"reason": "a\u0000b"}, {}):
        assert (await admin.post(f"{ADMIN}/questions/{ids[0]}/pull", json=body)).status_code == 422, body
    pulled = await admin.post(f"{ADMIN}/questions/{ids[0]}/pull", json={"reason": "  The key is   wrong. "})
    assert pulled.json() == {"question_id": str(ids[0]), "set_id": str(set_id), "status": "pulled", "rescored": 1}
    assert await scores(quiz, set_id) == {p.developer: 4, p.other: 4}
    [row] = await owner_rows(quiz, "SELECT status, pulled_reason FROM quiz_questions WHERE id = :q", q=ids[0])
    assert tuple(row) == ("pulled", "The key is wrong.")
    assert code(await admin.post(f"{ADMIN}/questions/{ids[0]}/pull", json={"reason": "Again"})) == (
        409,
        "already_pulled",
    )
    restored = await admin.post(f"{ADMIN}/questions/{ids[0]}/restore")
    assert restored.json()["rescored"] == 1
    assert await scores(quiz, set_id) == {p.developer: 5, p.other: 4}
    assert code(await admin.post(f"{ADMIN}/questions/{ids[0]}/restore")) == (409, "already_live")
    assert code(await admin.post(f"{ADMIN}/questions/{uuid7()}/restore")) == (404, "not_found")
    events = await audit_actions(quiz, ids[0])
    assert [(e.action, e.actor_kind, e.actor_user_id, e.payload) for e in events] == [
        ("quiz.question_pulled", "staff", p.admin, {"set_id": str(set_id), "rescored": 1, "reason": "staff"}),
        ("quiz.question_restored", "staff", p.admin, {"set_id": str(set_id), "rescored": 1}),
    ]
    listed = (await admin.get(f"{ADMIN}/sets/{set_id}")).json()["questions"][0]
    assert (listed["status"], listed["pulled_reason"], listed["restored_at"] is not None) == ("live", None, True)
    draft = await draft_set(quiz, monday + timedelta(days=1), role="job")
    [first, *_] = await question_ids(quiz, draft)
    held = await admin.post(f"{ADMIN}/questions/{first}/pull", json={"reason": "Check it first"})
    assert (held.json()["status"], held.json()["rescored"]) == ("pulled", 0)  # a draft's question, before approval
