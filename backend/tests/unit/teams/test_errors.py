"""REQ-DEV-03: the database's refusals as the teams API answers them, every branch (revision 0011's operating rules):
a refusal about another developer is the same 404 whatever its cause."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.exc import DBAPIError

from bridge.errors import ApiError
from bridge.teams import errors


@dataclass
class Diag:
    message_primary: str
    constraint_name: str | None = None


@dataclass
class Orig(Exception):
    sqlstate: str
    diag: Diag


def refused(sqlstate: str, message: str = "", constraint: str | None = None) -> DBAPIError:
    return DBAPIError("statement", {}, Orig(sqlstate, Diag(message, constraint)))


def answer(found: ApiError | None) -> tuple[int, str] | None:
    if found is None:
        return None
    detail = found.detail
    assert isinstance(detail, dict)
    return found.status_code, detail["code"]


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (refused("P0002", "team_invitations: no published problem with that id"), (404, "problem_unavailable")),
        (
            refused("P0002", "team_invitations: the recipient is neither a peer nor a counterpart"),
            (404, "peer_unavailable"),
        ),
        (refused("23505", "", "uq_team_invitations_pending_pair"), (409, "already_invited")),
        (refused("23505", "", "pk_team_invitations"), None),
        (refused("42501", "new row violates row-level security policy"), (404, "peer_unavailable")),
        (refused("23503", "insert violates foreign key"), (404, "peer_unavailable")),
        (refused("23514", "ck_team_invitations_note_valid"), (422, "invalid_invitation")),
        (refused("40001"), None),
    ],
)
def test_invitation_refusals(exc: DBAPIError, expected: tuple[int, str] | None) -> None:
    assert answer(errors.invitation_refusal(exc)) == expected


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            refused("42501", "app_decide_team_invitation: no invitation of the caller's with that id"),
            (404, "not_found"),
        ),
        (refused("42501", "app_decide_team_invitation: only the sender withdraws"), (403, "wrong_party")),
        (
            refused("55000", "app_decide_team_invitation: the invitation was already decided (accepted)"),
            (409, "already_decided"),
        ),
        (
            refused("55000", "app_decide_team_invitation: the problem is no longer open to teams"),
            (409, "invitation_unavailable"),
        ),
        (refused("22023"), None),
    ],
)
def test_decision_refusals(exc: DBAPIError, expected: tuple[int, str] | None) -> None:
    assert answer(errors.decision_refusal(exc)) == expected


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (refused("42501", "team_messages: no thread of the caller's with that id"), (404, "not_found")),
        (refused("42501", "new row violates row-level security policy"), (409, "thread_closed")),
        (refused("55000", "team_messages: the thread is closed; it is read-only"), (409, "thread_closed")),
        (refused("23514", "ck_team_messages_body_length"), (422, "invalid_message")),
        (refused("40P01"), None),
    ],
)
def test_message_refusals(exc: DBAPIError, expected: tuple[int, str] | None) -> None:
    assert answer(errors.message_refusal(exc)) == expected
