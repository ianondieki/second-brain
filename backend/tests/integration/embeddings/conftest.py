"""Fixtures of the embedding job's tests (P23-1; REQ-PERS-02, REQ-EMB-01): a database of each test module's own (module
scope), so a run's whole-table passes and its counts see only that module's rows, with an owner and an app engine."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic


@pytest.fixture(scope="module")
def job_url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_embed_job_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "head"))
        yield database
    finally:
        drop_database(admin_url, name)


@pytest.fixture(scope="module")
async def job_owner(job_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = role_engine(job_url, "bridge_owner")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
async def job_app(job_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = role_engine(job_url, "bridge_app")
    yield engine
    await engine.dispose()
