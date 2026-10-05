"""REQ-DEV-01 (D-59; P22 card test A8, the sets' rules): the demo seed's quiz sets (``bridge.seed.demo.quiz``), on the
module's own database with a staff admin of its own approving through the API.

The hand-written sets pass the checks in code and are stored for yesterday and today as seeded drafts, then
approved; a second run adds nothing; a seeded draft a run left behind is approved; a day that has any other set gets
nothing; a later day inside the 60-day window of the hand-written prompts gets no set and one line."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from typing import Any

import httpx
import pytest

from bridge.quiz.checks import check_draft
from bridge.quiz.sources import get_sources
from bridge.seed.demo.data import STAFF_ADMIN
from bridge.seed.demo.quiz import SEEDED_SETS, checked, ensure_sets
from bridge.seed.demo.runtime import DemoReport, DemoSeedError
from tests.integration.quiz.api_world import Clients, QuizDb, at, cast, decide, draft_set, owner_rows


class Admin:
    """The demo staff admin's actor, as ``Actors`` hands it out: a signed-in client of the in-process API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client, self.calls = client, 0

    async def get(self, email: str) -> Admin:
        assert email == STAFF_ADMIN.email
        return self

    async def call(self, method: str, path: str, *, expect: Iterable[int] = (200,), **kwargs: Any) -> httpx.Response:
        self.calls += 1
        response = await self.client.request(method, path, **kwargs)
        if response.status_code not in set(expect):
            raise DemoSeedError(f"{method} {path}: {response.status_code}")
        return response


def test_the_hand_written_sets_pass_the_checks() -> None:
    for which, questions in SEEDED_SETS.items():
        accepted = check_draft(checked(questions), get_sources().by_id())
        assert isinstance(accepted, tuple), which
        assert [q.answer for q in accepted] == [q.answer for q in questions]
        assert all(q.source_url.startswith("https://") for q in accepted)


async def test_the_seeded_sets_are_stored_approved_once_and_later_days_get_one_line(
    quiz: QuizDb, as_user: Clients
) -> None:
    monday = quiz.monday()
    tuesday = monday + timedelta(days=1)
    await at(quiz, tuesday)
    p = await cast(quiz)
    admin = Admin(await as_user(p.admin))
    report = DemoReport(users={STAFF_ADMIN.email: p.admin})
    await ensure_sets(quiz.owner, admin, report)  # type: ignore[arg-type]
    assert report.created == [
        f"quiz set {monday} (seeded)",
        f"quiz set {monday} approved by {STAFF_ADMIN.email}",
        f"quiz set {tuesday} (seeded)",
        f"quiz set {tuesday} approved by {STAFF_ADMIN.email}",
    ]
    sets = await owner_rows(
        quiz,
        "SELECT quiz_date, status, origin, decided_by FROM quiz_sets WHERE quiz_date IN (:a, :b) ORDER BY 1",
        a=monday,
        b=tuesday,
    )
    assert [tuple(s) for s in sets] == [
        (monday, "approved", "seeded", p.admin),
        (tuesday, "approved", "seeded", p.admin),
    ]
    again = DemoReport(users=report.users)
    await ensure_sets(quiz.owner, admin, again)  # type: ignore[arg-type]
    assert (again.created, again.notes, admin.calls) == ([], [], 2)
    wednesday = tuesday + timedelta(days=1)
    await at(quiz, wednesday)
    later = DemoReport(users=report.users)
    await ensure_sets(quiz.owner, admin, later)  # type: ignore[arg-type]
    assert (later.created, later.notes) == ([], [f"quiz set {wednesday}: left out (repeated_prompt)"])
    assert await owner_rows(quiz, "SELECT id FROM quiz_sets WHERE quiz_date = :d", d=wednesday) == []


async def test_a_seeded_draft_left_behind_is_approved_and_other_sets_are_left(quiz: QuizDb, as_user: Clients) -> None:
    monday = quiz.monday()
    tuesday = monday + timedelta(days=1)
    await at(quiz, tuesday)
    p = await cast(quiz)
    left = await draft_set(quiz, tuesday)  # a seeded draft: a run stopped before approving it
    model = await draft_set(quiz, monday, role="owner")
    await decide(quiz, model, p.admin, "rejected")  # yesterday has a set (rejected): it gets nothing
    admin = Admin(await as_user(p.admin))
    report = DemoReport(users={STAFF_ADMIN.email: p.admin})
    await ensure_sets(quiz.owner, admin, report)  # type: ignore[arg-type]
    assert report.created == [f"quiz set {tuesday} approved by {STAFF_ADMIN.email}"]
    found = await owner_rows(
        quiz, "SELECT id, status FROM quiz_sets WHERE quiz_date IN (:a, :b) ORDER BY quiz_date", a=monday, b=tuesday
    )
    assert [(f.id, f.status) for f in found] == [(model, "rejected"), (left, "approved")]
    with pytest.raises(DemoSeedError, match=STAFF_ADMIN.email):  # no demo staff admin: refused
        await ensure_sets(quiz.owner, admin, DemoReport())  # type: ignore[arg-type]
