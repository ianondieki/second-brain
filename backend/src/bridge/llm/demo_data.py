"""The D-37 data rule: only seeded demo data goes to a free provider (a free provider may train on what it receives).

A call routed to a free slot passes only when its user (``CallContext.user_id``: the signed-in user, or the member an
organisation's call is bound to) is a demo account and so is every field's owner: ``users.demo_account = true``
(schema v3; the demo seed sets it as the owner role, never the app). ``LLMService`` runs the rule right after the
Tier-2 consent guard, before sanitising, budgeting or sending:

- a Tier-2 field owned by a non-demo account is refused (``Tier2DemoOnly``, a ``Tier2NotAllowed``: a ``blocked_tier2``
  row with names and lengths only), whatever the consent and whoever calls;
- otherwise a call with no user (a platform or organisation job), a non-demo user, or a field owned by a non-demo
  account raises ``NotDemoData``, unrecorded (nothing was attempted); the router answers with the deterministic fake,
  labelled "demo fallback" (``bridge.llm.routing``).

The Anthropic services have no rule: they keep the T2.2 rules. ``SqlDemoAccounts`` reads the column in its own short
transaction as the caller's tenant, so a failure never touches the caller's transaction; a missing column (the
integration branch before schema v3), a missing or unreadable row, and any database error all count as "not a demo
account" (fail closed).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.db import bind_tenant, tenant_of
from bridge.llm.errors import NotDemoData, Tier2DemoOnly
from bridge.llm.types import CallContext, Message, Tier
from bridge.logging import get_logger

log = get_logger("bridge.llm")
DEMO_ACCOUNT = text("SELECT demo_account FROM users WHERE id = :id")


class DemoAccounts(Protocol):
    async def is_demo(self, user_id: UUID) -> bool: ...


class DataRule(Protocol):
    async def check_call(self, task: str, messages: Sequence[Message], ctx: CallContext) -> None:
        """Raise an ``LLMBlocked`` when the call's data may not go to the service's provider."""
        ...


class StaticDemoAccounts:
    """Demo accounts held in memory (tests and fakes)."""

    def __init__(self, ids: Iterable[UUID] = ()) -> None:
        self.ids = set(ids)

    async def is_demo(self, user_id: UUID) -> bool:
        return user_id in self.ids


class SqlDemoAccounts:
    """``users.demo_account`` read as ``caller``'s tenant (only its binding is read), in a session of ``factory``."""

    def __init__(self, factory: async_sessionmaker[AsyncSession], *, caller: AsyncSession) -> None:
        self._factory = factory
        self._caller = caller

    async def is_demo(self, user_id: UUID) -> bool:
        bound_user, bound_org = tenant_of(self._caller)
        try:
            async with self._factory() as db:
                await bind_tenant(db, user_id=bound_user, org_id=bound_org)
                value = (await db.execute(DEMO_ACCOUNT, {"id": user_id})).scalar_one_or_none()
        except DBAPIError as exc:  # no column before schema v3, or no privilege: not a demo account
            log.info("llm.demo_account_unreadable", reason=type(exc.orig).__name__)
            return False
        return value is True


class DemoDataRule:
    """The rule of one request or job (each account is looked up once)."""

    def __init__(self, accounts: DemoAccounts) -> None:
        self._accounts = accounts
        self._known: dict[UUID, bool] = {}

    async def _is_demo(self, user_id: UUID) -> bool:
        if user_id not in self._known:
            self._known[user_id] = await self._accounts.is_demo(user_id)
        return self._known[user_id]

    async def check_call(self, task: str, messages: Sequence[Message], ctx: CallContext) -> None:
        fields = [f for message in messages for f in message.fields]
        refused = set()
        for item in fields:
            if item.tier is Tier.TIER2 and (item.owner_id is None or not await self._is_demo(item.owner_id)):
                refused.add(item.name)
        if refused:
            raise Tier2DemoOnly(task, tuple(sorted(refused)))
        if ctx.user_id is None or not await self._is_demo(ctx.user_id):
            raise NotDemoData(task)
        for item in fields:
            if item.owner_id is not None and not await self._is_demo(item.owner_id):
                raise NotDemoData(task)
