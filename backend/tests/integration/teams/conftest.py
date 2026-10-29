"""The teams API tests' database (REQ-DEV-03): one per module, migrated to head with Kenya's counties, so a test may
commit peers, invitations and threads (the peers list reads every developer of the database) without touching the
session database the schema tests share."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy.engine import URL

from bridge.seed.reference import load_reference, seed_regions
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.integration.teams.api_world import Clients, TeamsDb, clients


@pytest.fixture(scope="module")
def teams_url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_teams_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        run_alembic(url, lambda config: command.upgrade(config, "head"))
        yield url
    finally:
        drop_database(admin_url, name)


@pytest.fixture(scope="module")
async def teams(teams_url: URL) -> AsyncIterator[TeamsDb]:
    found = TeamsDb(role_engine(teams_url, "bridge_owner"), role_engine(teams_url, "bridge_app"))
    async with found.owner.begin() as conn:
        await seed_regions(conn, load_reference()["regions"])
    try:
        yield found
    finally:
        await found.owner.dispose()
        await found.app.dispose()


@pytest.fixture
async def as_user(teams: TeamsDb) -> AsyncIterator[Clients]:
    async with clients(teams) as made:
        yield made
