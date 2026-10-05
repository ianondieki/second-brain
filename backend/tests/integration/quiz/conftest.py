"""The quiz API, job and store tests' database (REQ-DEV-01): one of each module's own, migrated to head, so a test may
move the shared clock and commit sets without touching the session database the other tests share."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy.engine import URL

from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.integration.quiz.api_world import Clients, QuizDb, clients


@pytest.fixture(scope="module")
def quiz_url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_quiz_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        run_alembic(url, lambda config: command.upgrade(config, "head"))
        yield url
    finally:
        drop_database(admin_url, name)


@pytest.fixture(scope="module")
async def quiz(quiz_url: URL) -> AsyncIterator[QuizDb]:
    found = QuizDb(role_engine(quiz_url, "bridge_owner"), role_engine(quiz_url, "bridge_app"))
    try:
        yield found
    finally:
        await found.owner.dispose()
        await found.app.dispose()


@pytest.fixture
async def as_user(quiz: QuizDb) -> AsyncIterator[Clients]:
    async with clients(quiz) as made:
        yield made
