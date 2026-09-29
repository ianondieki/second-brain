"""``app_add_niche`` refuses in SQL (REQ-ADM-01, REQ-DIR-01); the admin route turns each refusal into an API error by
SQLSTATE and lets anything else propagate (a 500, never a silent success)."""

from __future__ import annotations

from unittest.mock import ANY

import pytest
from sqlalchemy.exc import DBAPIError

from bridge.admin.router import niche_refusal


class _DriverError(Exception):
    def __init__(self, sqlstate: str | None) -> None:
        super().__init__("app_add_niche: refused")
        self.sqlstate = sqlstate


def _error(sqlstate: str | None) -> DBAPIError:
    return DBAPIError("SELECT app_add_niche(...)", None, _DriverError(sqlstate))


@pytest.mark.parametrize(
    ("sqlstate", "status", "code"),
    [
        ("23505", 409, "niche_slug_taken"),  # unique_violation
        ("23514", 422, "parent_niche_not_top_level"),  # check_violation
        ("23503", 422, "parent_niche_not_found"),  # foreign_key_violation
        ("22023", 422, "invalid_niche"),  # invalid_parameter_value
        ("42501", 404, "not_found"),  # insufficient_privilege: the database's staff check, answered like the dependency
    ],
)
def test_each_refusal_maps_to_its_api_error(sqlstate: str, status: int, code: str) -> None:
    refusal = niche_refusal(_error(sqlstate))
    assert refusal is not None
    detail: object = refusal.detail  # a dict at run time (bridge.errors.ApiError); Starlette types it as str
    assert (refusal.status_code, detail) == (status, {"code": code, "message": ANY})


@pytest.mark.parametrize("sqlstate", ["40001", "57014", None])
def test_other_database_errors_are_not_mapped(sqlstate: str | None) -> None:
    assert niche_refusal(_error(sqlstate)) is None
