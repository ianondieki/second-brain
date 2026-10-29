"""This week's API, reminder and trend tests' database (REQ-DEV-02): one of each module's own, migrated to head with
Kenya's counties, so a test may move the shared clock and commit events without touching the session database the
other tests share."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy.engine import URL

from bridge.seed.reference import load_reference, seed_regions
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.integration.events.api_world import Clients, WeekDb, clients


@pytest.fixture(scope="module")
def week_url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_week_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        run_alembic(url, lambda config: command.upgrade(config, "head"))
        yield url
    finally:
        drop_database(admin_url, name)


@pytest.fixture(scope="module")
async def week(week_url: URL) -> AsyncIterator[WeekDb]:
    found = WeekDb(role_engine(week_url, "bridge_owner"), role_engine(week_url, "bridge_app"))
    async with found.owner.begin() as conn:
        await seed_regions(conn, load_reference()["regions"])
    try:
        yield found
    finally:
        await found.owner.dispose()
        await found.app.dispose()


@pytest.fixture
async def as_user(week: WeekDb) -> AsyncIterator[Clients]:
    async with clients(week) as made:
        yield made
