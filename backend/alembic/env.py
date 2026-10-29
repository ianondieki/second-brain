"""Alembic environment. Migrations run as the owner role (docs/spec/08: "migrations use a separate owner role").

The URL comes from ``DATABASE_OWNER_URL``. A caller (the test harness) may instead pass an open connection in
``config.attributes["connection"]``.
"""

from __future__ import annotations

import asyncio
import os
import sys

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import bridge.models.all  # noqa: F401  # registers every table
from bridge.models import Base

config = context.config
target_metadata = Base.metadata


def include_name(name: str | None, type_: str, _parent_names: object) -> bool:
    """Leave out objects the ORM does not declare: Procrastinate's job tables (vendored SQL in revision 0001)."""
    return not (type_ == "table" and name is not None and name.startswith("procrastinate_"))


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True, include_name=include_name
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    url = os.environ.get("DATABASE_OWNER_URL")
    if not url:
        raise SystemExit("DATABASE_OWNER_URL is not set: migrations must run as the owner role (bridge_owner).")
    # psycopg's async driver needs a selector loop; Windows defaults to the proactor loop.
    asyncio.run(_run_async(url), loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None)


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported; run against a database.")
run_migrations_online()
