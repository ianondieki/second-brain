"""P27 (REQ-ENG-15, REQ-PROV-06): the database's backstop refusals (revision 0013's guards and window trigger, revision
0003's chain) map to the same answers as the API's own checks, and anything else is re-raised (a bug, never hidden);
N30 never raises."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.exc import DBAPIError

from bridge.engagements import prior_knowledge, team
from bridge.engagements.schemas import TeamOut
from bridge.errors import ApiError

ENGAGEMENT = UUID("01900000-0000-7000-8000-00000000000c")


@dataclass
class Diag:
    message_primary: str = ""
    constraint_name: str = ""


@dataclass
class Orig(Exception):
    sqlstate: str
    diag: Diag = field(default_factory=Diag)


def refused(sqlstate: str, message: str = "", constraint: str = "") -> DBAPIError:
    return DBAPIError("INSERT ...", {}, Orig(sqlstate, Diag(message, constraint)))


def answer(error: ApiError) -> tuple[int, str]:
    detail: dict[str, Any] = error.detail  # type: ignore[assignment]
    return error.status_code, str(detail["code"])


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            refused("55000", "prior_knowledge_declarations: the organisation has not viewed the proposal's Tier 2 yet"),
            (403, "no_tier2_access_yet"),
        ),
        (
            refused("55000", "prior_knowledge_declarations: the declaration window closed on 2026-10-26"),
            (403, "declaration_window_closed"),
        ),
        (refused("23505", "duplicate key", "uq_prior_knowledge_declarations_engagement_id"), (409, "already_declared")),
        (
            refused(
                "23514",
                "prior_knowledge_declarations: the evidence is dated after the organisation's first Tier-2 view"
                " (2026-10-12)",
            ),
            (422, "evidence_after_first_view"),
        ),
        (
            refused("23514", "violates", "ck_prior_knowledge_declarations_evidence_predates_first_view"),
            (422, "evidence_after_first_view"),
        ),
        (refused("55000", "prior_knowledge_declarations: the engagement has ended"), (409, "engagement_ended")),
        (
            refused("23514", "engagement_events: the engagement ended in DECLINED and takes no further event"),
            (409, "engagement_ended"),
        ),
        (refused("23514", "engagement_events: the engagement is in state X, not Y"), (409, "conflict")),
        (refused("42501", "tracker_engagement_visible: no engagement of the caller"), (404, "not_found")),
        (refused("42501", "new row violates row-level security policy"), (403, "role_not_allowed")),
        (refused("40001"), (409, "conflict")),
    ],
)
def test_the_declarations_backstop_answers_as_the_api(exc: DBAPIError, expected: tuple[int, str]) -> None:
    assert answer(prior_knowledge._refusal(exc)) == expected


def test_an_unknown_database_error_is_re_raised() -> None:
    unknown = refused("XX000", "internal")
    with pytest.raises(DBAPIError):
        prior_knowledge._refusal(unknown)
    with pytest.raises(DBAPIError):
        team._refusal(unknown, check=ApiError(422, "c", "m"), unique=ApiError(409, "u", "m"))


def test_the_closed_window_names_its_last_day_when_known() -> None:
    closed: dict[str, Any] = prior_knowledge._closed(date(2026, 10, 26)).detail  # type: ignore[assignment]
    assert closed == {
        "code": "declaration_window_closed",
        "message": prior_knowledge.WINDOW_CLOSED,
        "window_closed_on": "2026-10-26",
    }
    unknown: dict[str, Any] = prior_knowledge._closed(None).detail  # type: ignore[assignment]
    assert "window_closed_on" not in unknown


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("23514", (422, "check")),
        ("42501", (403, "role_not_allowed")),
        ("23505", (409, "unique")),
        ("40P01", (409, "unique")),
    ],
)
def test_the_triage_backstop_answers_as_the_api(sqlstate: str, expected: tuple[int, str]) -> None:
    mapped = team._refusal(refused(sqlstate), check=ApiError(422, "check", "m"), unique=ApiError(409, "unique", "m"))
    assert answer(mapped) == expected


async def test_n30_never_raises_and_tells_nobody_without_a_new_assignee() -> None:
    sheet = TeamOut(engagement_id=ENGAGEMENT, members=[], assignee=None, recommendations=[])
    nobody = team.Assigned(team=sheet, assignment_id=None, assignee_id=None, title="Cold-chain alerts")

    def broken() -> Any:
        raise RuntimeError("the database is down")

    kwargs = {"org_id": ENGAGEMENT, "engagement_id": ENGAGEMENT, "assigner_name": "Amina"}
    assert await team.tell_assignee(broken, assigned=nobody, **kwargs) is False  # type: ignore[arg-type]
    someone = team.Assigned(team=sheet, assignment_id=ENGAGEMENT, assignee_id=ENGAGEMENT, title="Cold-chain alerts")
    assert await team.tell_assignee(broken, assigned=someone, **kwargs) is False  # type: ignore[arg-type]
