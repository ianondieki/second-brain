"""REQ-SCOUT-01, REQ-ENG-04: the database's backstop refusals map to stable API errors (a race the application's own
checks could not see), and anything else is re-raised as the bug it is."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from bridge.engagements import interest
from bridge.errors import ApiError
from bridge.matching import scouts


class Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def refused(sqlstate: str) -> DBAPIError:
    return DBAPIError("INSERT ...", None, Orig(sqlstate))


@pytest.mark.parametrize(
    ("sqlstate", "status", "code"),
    [("23505", 409, "engagement_exists"), ("42501", 403, "refused"), ("23514", 409, "conflict")],
)
def test_an_interest_refused_by_the_database(sqlstate: str, status: int, code: str) -> None:
    error = interest._refusal(refused(sqlstate))
    assert (error.status_code, error.detail["code"]) == (status, code)  # type: ignore[index]


def test_an_unknown_database_error_is_re_raised() -> None:
    other = refused("08006")
    with pytest.raises(DBAPIError):
        interest._refusal(other)
    assert scouts._db_refusal(other) is None


@pytest.mark.parametrize(("sqlstate", "status", "code"), [("23514", 422, "invalid_scout"), ("42501", 403, "forbidden")])
def test_a_scout_refused_by_the_database(sqlstate: str, status: int, code: str) -> None:
    error = scouts._db_refusal(refused(sqlstate))
    assert error is not None
    assert (error.status_code, error.detail["code"]) == (status, code)  # type: ignore[index]


class Session:
    def __init__(self, error: DBAPIError) -> None:
        self.error, self.rolled_back = error, False

    async def commit(self) -> None:
        raise self.error

    async def rollback(self) -> None:
        self.rolled_back = True


async def test_a_refused_commit_rolls_back_and_answers() -> None:
    session = Session(refused("23514"))
    with pytest.raises(ApiError) as caught:
        await scouts._commit(session)  # type: ignore[arg-type]
    assert caught.value.status_code == 422
    assert session.rolled_back
    bug: Any = Session(refused("08006"))
    with pytest.raises(DBAPIError):
        await scouts._commit(bug)
