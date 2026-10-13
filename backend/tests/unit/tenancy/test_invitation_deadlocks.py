"""REQ-TEN-02 (P28 track C; the security re-check's MINOR and the reviewer's note): a deadlock (SQLSTATE 40P01) in
accept, resend or invite's revoke of an expired open invitation is answered 409 ``conflict`` (retry-able) with the
transaction rolled back, never a 500; any other database error keeps its own answer or is re-raised.

The database is a stand-in here (as ``tests/unit/engagements/test_commands.py`` feeds refusals): the integration tests
show the lock order that keeps the deadlock from happening, these the backstop's answer when it happens anyway.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth.crypto import new_token
from bridge.auth.sessions import LiveSession
from bridge.config import get_settings
from bridge.errors import ApiError
from bridge.models.enums import OrgRole
from bridge.tenancy import invitations
from bridge.tenancy.deps import OrgContext

SETTINGS = get_settings()


class _Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"SQLSTATE {sqlstate}")
        self.sqlstate = sqlstate


def refusal(sqlstate: str) -> DBAPIError:
    return DBAPIError("statement", {}, _Orig(sqlstate))


class FakeDb:
    """Answers each ``scalar``/``execute`` from a queue (a value, or an exception to raise); counts rollbacks."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.rollbacks = 0

    def _next(self) -> Any:
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    async def scalar(self, *_: Any, **__: Any) -> Any:
        return self._next()

    async def execute(self, *_: Any, **__: Any) -> Any:
        return self._next()

    async def scalars(self, *_: Any, **__: Any) -> Any:
        return self._next()

    async def rollback(self) -> None:
        self.rollbacks += 1


def session(db: FakeDb) -> AsyncSession:
    return cast(AsyncSession, db)


def live() -> LiveSession:
    return cast(LiveSession, SimpleNamespace(user=SimpleNamespace(id=uuid4())))


def owner() -> OrgContext:
    return OrgContext(uuid4(), frozenset({OrgRole.OWNER, OrgRole.ADMIN}), live())


def detail(error: ApiError) -> tuple[int, str]:
    return error.status_code, cast(dict[str, Any], error.detail)["code"]


async def nothing(*_: Any, **__: Any) -> None:
    return None


def returning(value: Any) -> Callable[..., Any]:
    async def answer(*_: Any, **__: Any) -> Any:
        return value

    return answer


@pytest.fixture
def no_developer_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(invitations, "has_developer_profile", returning(False))


@pytest.mark.usefixtures("no_developer_profile")
async def test_a_deadlock_in_the_accept_function_is_409_conflict() -> None:
    db = FakeDb(refusal("40P01"))
    with pytest.raises(ApiError) as answered:
        await invitations.accept(session(db), SETTINGS, live(), new_token())
    assert detail(answered.value) == (409, "conflict")
    assert db.rollbacks == 1


@pytest.mark.usefixtures("no_developer_profile")
async def test_a_deadlock_on_the_organisation_s_lock_after_accepting_is_409_conflict() -> None:
    joined = SimpleNamespace(one=lambda: SimpleNamespace(id=uuid4(), roles=["reviewer"], legal_name="Telco A"))
    db = FakeDb(uuid4(), joined, refusal("40P01"))  # the function's answer, the membership read, then the lock
    with pytest.raises(ApiError) as answered:
        await invitations.accept(session(db), SETTINGS, live(), new_token())
    assert detail(answered.value) == (409, "conflict")
    assert db.rollbacks == 1


@pytest.mark.usefixtures("no_developer_profile")
async def test_the_accept_function_s_other_refusals_keep_their_answers() -> None:
    for sqlstate, expected in (
        ("P0002", (404, "not_found")),
        ("42501", (403, "invitation_email_mismatch")),
        ("23505", (409, "already_member")),
    ):
        db = FakeDb(refusal(sqlstate))
        with pytest.raises(ApiError) as answered:
            await invitations.accept(session(db), SETTINGS, live(), new_token())
        assert detail(answered.value) == expected
    db = FakeDb(refusal("42601"))  # anything else is a bug: re-raised
    with pytest.raises(DBAPIError):
        await invitations.accept(session(db), SETTINGS, live(), new_token())


def _open(org: OrgContext) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        org_id=org.org_id,
        email="newcomer@example.com",
        roles=["reviewer"],
        expires_at=datetime(2026, 10, 20, tzinfo=UTC),
        accepted_at=None,
        revoked_at=None,
    )


@pytest.mark.parametrize("where", ["_locked_open", "_lock"])
async def test_a_deadlock_in_resend_is_409_conflict(monkeypatch: pytest.MonkeyPatch, where: str) -> None:
    org = owner()
    found = _open(org)
    monkeypatch.setattr(invitations, "_open_invitation", returning(found))
    monkeypatch.setattr(invitations, "_check_verified", nothing)
    monkeypatch.setattr(invitations, "_spend", nothing)
    monkeypatch.setattr(invitations, "_locked_open", returning(found))

    async def deadlocked(*_: Any, **__: Any) -> None:
        raise refusal("40P01")

    monkeypatch.setattr(invitations, where, deadlocked)
    db = FakeDb()
    with pytest.raises(ApiError) as answered:
        await invitations.resend(session(db), SETTINGS, org, cast(UUID, found.id), "127.0.0.1")
    assert detail(answered.value) == (409, "conflict")
    assert db.rollbacks == 1


async def test_another_database_error_in_resend_is_re_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    org = owner()
    found = _open(org)
    for name in ("_check_verified", "_spend", "_lock"):
        monkeypatch.setattr(invitations, name, nothing)
    monkeypatch.setattr(invitations, "_open_invitation", returning(found))

    async def broken(*_: Any, **__: Any) -> None:
        raise refusal("42601")

    monkeypatch.setattr(invitations, "_locked_open", broken)
    db = FakeDb()
    with pytest.raises(DBAPIError):
        await invitations.resend(session(db), SETTINGS, org, cast(UUID, found.id), "127.0.0.1")
    assert db.rollbacks == 0


@pytest.mark.parametrize(("sqlstate", "expected"), [("40P01", (409, "conflict")), ("42501", (403, "protected_role"))])
async def test_invite_s_revoke_of_an_expired_invitation_answers_its_refusals(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str, expected: tuple[int, str]
) -> None:
    for name in ("_check_verified", "_spend", "_lock"):
        monkeypatch.setattr(invitations, name, nothing)
    monkeypatch.setattr(invitations, "_is_member", returning(False))
    no_stale = SimpleNamespace(all=lambda: [])
    db = FakeDb(no_stale, refusal(sqlstate))  # the expired invitations' roles, then the revoke
    with pytest.raises(ApiError) as answered:
        await invitations.invite(session(db), SETTINGS, owner(), "newcomer@example.com", [OrgRole.REVIEWER], "::1")
    assert detail(answered.value) == expected
    assert db.rollbacks == (1 if sqlstate == "40P01" else 0)
