"""Database engine, sessions and the per-transaction tenant context (REQ-TEN-01, docs/spec/08 Tenancy).

Row-Level Security reads ``app.user_id`` and ``app.org_id``. They are set with ``set_config(..., true)``, which lasts
for the current transaction only, so a pooled connection never carries one request's tenant into the next. The
context is kept in ``session.info`` and re-applied at the start of every transaction (``after_begin``), so a handler
that commits and keeps working stays inside its tenant.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, SessionTransaction
from starlette.requests import Request

TENANT_KEY = "bridge.tenant"
_SET_TENANT = text("select set_config('app.user_id', :user_id, true), set_config('app.org_id', :org_id, true)")


def create_engine(url: str, **kwargs: Any) -> AsyncEngine:
    # hide_parameters: DB errors never echo bound values (emails, password hashes) into logs.
    return create_async_engine(url, pool_pre_ping=True, hide_parameters=True, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _tenant_params(session: Session) -> dict[str, str]:
    user_id, org_id = session.info.get(TENANT_KEY, (None, None))
    return {"user_id": str(user_id) if user_id else "", "org_id": str(org_id) if org_id else ""}


@event.listens_for(Session, "after_begin")
def _apply_tenant(session: Session, _transaction: SessionTransaction, connection: Connection) -> None:
    if TENANT_KEY in session.info:
        connection.execute(_SET_TENANT, _tenant_params(session))


async def bind_tenant(session: AsyncSession, *, user_id: UUID | None, org_id: UUID | None = None) -> None:
    """Scope ``session`` to one user (and optionally one organisation) for RLS, now and for later transactions."""
    session.info[TENANT_KEY] = (user_id, org_id)
    if session.in_transaction():
        await session.execute(_SET_TENANT, _tenant_params(session.sync_session))


def tenant_of(session: AsyncSession) -> tuple[UUID | None, UUID | None]:
    value: tuple[UUID | None, UUID | None] = session.info.get(TENANT_KEY, (None, None))
    return value


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request. Handlers commit explicitly; anything uncommitted rolls back."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session
