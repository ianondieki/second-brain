"""Integration harness: a throwaway PostgreSQL 16 + pgvector database per test session, migrated to head.

The server is ``TEST_DATABASE_ADMIN_URL`` (a superuser URL; CI uses a service container) or, when unset, a
``pgvector/pgvector:pg16`` testcontainer. The harness creates the Bridge roles (``infra/postgres/roles.sql``), a
fresh database, runs ``alembic upgrade head`` as ``bridge_owner`` and hands out engines that act as ``bridge_app``,
``aggregate_worker`` or ``audit_reader`` through ``SET ROLE``, so Row-Level Security applies exactly as in production
(RLS follows the current role, not the superuser session). The database is dropped at the end.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
ROLES_SQL = (REPO / "infra" / "postgres" / "roles.sql").read_text(encoding="utf-8")
PREPARE_SQL = (REPO / "infra" / "postgres" / "prepare_db.sql").read_text(encoding="utf-8")
IMAGE = "pgvector/pgvector:pg16"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def admin_url() -> Iterator[URL]:
    configured = os.environ.get("TEST_DATABASE_ADMIN_URL")
    if configured:
        yield make_url(configured)
        return
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(IMAGE, driver="psycopg") as container:
        yield make_url(container.get_connection_url())


def alembic_config() -> Config:
    return Config(str(BACKEND / "alembic.ini"))


def run_alembic(url: URL, action: Callable[[Config], None]) -> None:
    """Run an Alembic command as ``bridge_owner`` on a sync connection (the harness logs in as a superuser)."""
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("SET ROLE bridge_owner")
            config = alembic_config()
            config.attributes["connection"] = connection
            action(config)
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def database_url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_test_{uuid4().hex[:12]}"
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=sa.pool.NullPool)
    with admin.connect() as connection:
        connection.exec_driver_sql(ROLES_SQL)
        connection.exec_driver_sql(f'CREATE DATABASE "{name}" OWNER bridge_owner')
    url = admin_url.set(database=name)
    prepare = sa.create_engine(url, isolation_level="AUTOCOMMIT", poolclass=sa.pool.NullPool)
    with prepare.connect() as connection:
        connection.exec_driver_sql(PREPARE_SQL)
    prepare.dispose()
    run_alembic(url, lambda config: command.upgrade(config, "head"))
    try:
        yield url
    finally:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.dispose()


def role_engine(url: URL, role: str, **kwargs: Any) -> AsyncEngine:
    """An async engine whose every connection runs as ``role`` (RLS and grants apply to that role)."""
    engine = create_async_engine(url, **kwargs)

    @sa.event.listens_for(engine.sync_engine, "connect")
    def _set_role(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET ROLE {role}")
        cursor.close()

    return engine


@pytest.fixture(scope="session")
async def app_engine(database_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = role_engine(database_url, "bridge_app")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def owner_engine(database_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = role_engine(database_url, "bridge_owner")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def aggregate_engine(database_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = role_engine(database_url, "aggregate_worker")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def audit_reader_engine(database_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = role_engine(database_url, "audit_reader")
    yield engine
    await engine.dispose()
