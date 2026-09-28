"""Database engine, sessions and the per-transaction tenant context (REQ-TEN-01, docs/spec/08 Tenancy).

Row-Level Security reads ``app.user_id`` and ``app.org_id``. They are set with ``set_config(..., true)``, which lasts
for the current transaction only, so a pooled connection never carries one request's tenant into the next. The
context is kept in ``session.info`` and re-applied at the start of every transaction (``after_begin``), so a handler
that commits and keeps working stays inside its tenant.

Tier-2 tables are readable only by the roles of docs/spec/06 6.1 (revision 0002, ``infra/postgres/roles.sql``).
``bridge_app`` is a member of each WITH INHERIT FALSE, SET TRUE: code switches to one with ``as_role`` after the
application check has passed, and back before writing audit events.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final
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


# The roles bridge_app may switch to (docs/spec/06 6.1). Never bridge_owner, aggregate_worker or audit_reader: the
# database refuses those too (no membership); this list refuses them before a statement is sent.
TIER2_ROLES: Final = frozenset(
    {"tier2_reader", "provenance_worker", "tier2_embed_worker", "tier2_moderation", "dsr_exporter"}
)
_CURRENT_ROLE = text("select current_user")
# set_config('role', ..., true) is SET LOCAL ROLE with the name as a bound value (no identifier quoting); the server
# checks membership exactly as for SET ROLE.
_SET_LOCAL_ROLE = text("select set_config('role', :role, true)")


@asynccontextmanager
async def as_role(session: AsyncSession, role: str) -> AsyncIterator[AsyncSession]:
    """Run the block as ``role`` (one of ``TIER2_ROLES``) inside the session's current transaction.

    ``SET LOCAL ROLE`` lasts until the block ends or the transaction does, whichever is first; the block then restores
    the role that was current before it. That is ``RESET ROLE`` when the session logs in as ``bridge_app``; restoring
    explicitly also stays right under a harness that set its role for the whole session, where ``RESET ROLE`` would
    return to the login (superuser) role. Do not commit inside the block: a commit ends the switch early. Blocks do not
    nest. RLS applies to the switched role, so bind the tenant context (``bind_tenant``) first.
    """
    if role not in TIER2_ROLES:
        raise ValueError(f"as_role: {role!r} is not a Tier-2 role")
    previous = (await session.execute(_CURRENT_ROLE)).scalar_one()
    if previous in TIER2_ROLES:
        raise RuntimeError(f"as_role: already running as {previous}; blocks do not nest")
    await session.execute(_SET_LOCAL_ROLE, {"role": role})
    try:
        yield session
    except BaseException:
        try:
            await session.execute(_SET_LOCAL_ROLE, {"role": previous})
        except Exception:
            # The transaction failed and cannot run the restore; rolling it back ends the SET LOCAL as well.
            await session.rollback()
        raise
    await session.execute(_SET_LOCAL_ROLE, {"role": previous})


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request. Handlers commit explicitly; anything uncommitted rolls back."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session
