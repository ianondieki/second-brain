"""REQ-AUTH-02: ``identities.reload_session`` forgets every row read before the provider call, so it must never run
over changes not yet flushed: they would be dropped without a word (pre-merge MINOR, security review of the T2.12
follow-ups). No database: the session has no bind, so any statement would fail loudly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import make_transient_to_detached

from bridge.auth import identities
from bridge.auth.models import LoginAttempt


def ledger_row() -> LoginAttempt:
    return LoginAttempt(id=uuid4(), email_digest=b"e" * 32, ip_digest=b"i" * 32, succeeded=False)


def persistent(db: AsyncSession) -> LoginAttempt:
    """A row the session holds as if it had been loaded (in the identity map, nothing to flush)."""
    row = ledger_row()
    make_transient_to_detached(row)
    db.add(row)
    return row


async def _pending_new(db: AsyncSession) -> None:
    db.add(ledger_row())


async def _pending_dirty(db: AsyncSession) -> None:
    persistent(db).succeeded = True


async def _pending_deleted(db: AsyncSession) -> None:
    await db.delete(persistent(db))


@pytest.mark.parametrize("change", [_pending_new, _pending_dirty, _pending_deleted], ids=["new", "dirty", "deleted"])
async def test_reload_session_refuses_to_drop_unflushed_changes(
    change: Callable[[AsyncSession], Awaitable[None]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def never(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("reload_session went on past unflushed changes")

    monkeypatch.setattr(identities, "bind_tenant", never)
    db = AsyncSession()
    await change(db)
    with pytest.raises(RuntimeError, match="unflushed"):
        await identities.reload_session(db, None)
    assert db.new or db.dirty or db.deleted  # nothing was thrown away


async def test_reload_session_forgets_clean_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    bound: list[object] = []

    async def bind(_db: AsyncSession, *, user_id: object) -> None:
        bound.append(user_id)

    monkeypatch.setattr(identities, "bind_tenant", bind)
    db = AsyncSession()
    row = persistent(db)
    assert await identities.reload_session(db, None) is None
    assert row not in db
    assert bound == [None]
