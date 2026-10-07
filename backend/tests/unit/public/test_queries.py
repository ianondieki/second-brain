"""REQ-UX-03 (P24-B): the public reads' statements and reader, checked without a database.

The statements are compiled for PostgreSQL: they read only public columns, under the same public predicate as the
problem list and ``problem_is_readable`` (published, clear, a listed organisation, a Brief published and public), and
list registered versions of published, clear proposals only. ``read`` runs them as the public reader (the nil UUID,
never an account) in a read-only transaction of its own.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import create_engine

from bridge.public import queries

DIALECT = create_engine("postgresql+psycopg://").dialect  # nothing connects


def sql(statement: Any) -> str:
    return str(statement.compile(dialect=DIALECT, compile_kwargs={"literal_binds": True}))


STATEMENTS = pytest.mark.parametrize(
    "statement", [queries.activity_statement, queries.explore_statement], ids=["activity", "explore"]
)
PRIVATE_COLUMNS = (
    "legal_name",
    "slug",
    "owner_id",
    "owner_handle",
    "created_by",
    "display_name",
    "email",
    "statement",
    "summary",
    "impact_claims",
    "cert_id",
    "budget_band",
    "named_orgs",
)


@STATEMENTS
def test_the_statements_read_no_private_column(statement: Any) -> None:
    text = sql(statement())
    for column in PRIVATE_COLUMNS:
        assert f".{column}" not in text, column
    assert "engagement" not in text


@STATEMENTS
def test_the_statements_keep_the_public_problem_predicate(statement: Any) -> None:
    text = " ".join(sql(statement()).split())
    for clause in (
        "problems.status = 'published'",
        "problems.moderation_state = 'clear'",
        "problems.org_id IS NULL",
        "verification IN ('unclaimed', 'e1', 'e2')",
        "delisted_at IS NULL",
        "problems.source != 'org_brief'",
        "status = 'published' AND problem_briefs_1.visibility = 'public'",
    ):
        assert clause in text, clause


def test_the_activity_statement_lists_only_published_clear_registered_versions() -> None:
    text = " ".join(sql(queries.activity_statement()).split())
    assert "proposal_versions.status = 'registered'" in text
    assert "proposals.status = 'published' AND proposals.moderation_state = 'clear'" in text
    assert text.count("LIMIT 20") == 3  # each branch and the merged feed


def test_the_explore_statement_ranks_the_newest_three_per_group() -> None:
    text = " ".join(sql(queries.explore_statement()).split())
    assert "county_rank <= 3 OR" in text
    assert "niche_rank <= 3" in text


class Session:
    """A stand-in session: records what runs, returns ``rows``."""

    def __init__(self, rows: list[Any], log: list[str]) -> None:
        self.rows, self.log = rows, log
        self.info: dict[str, Any] = {}

    async def __aenter__(self) -> Session:
        return self

    async def __aexit__(self, *_: object) -> None:
        self.log.append("close")

    def in_transaction(self) -> bool:
        return False

    def begin(self) -> Session:
        self.log.append("begin")
        return self

    async def execute(self, statement: Any) -> SimpleNamespace:
        self.log.append(" ".join(str(statement).split()))
        return SimpleNamespace(all=lambda: self.rows)


async def test_the_reads_run_as_the_public_reader_in_a_read_only_transaction() -> None:
    log: list[str] = []
    sessions: list[Session] = []

    def factory() -> Session:
        sessions.append(Session(["a row"], log))
        return sessions[-1]

    assert await queries.read(factory, queries.activity_statement()) == ["a row"]  # type: ignore[arg-type]
    assert sessions[0].info["bridge.tenant"] == (queries.PUBLIC_READER, None)
    assert UUID(int=0) == queries.PUBLIC_READER  # never a user: account ids are UUIDv7
    assert log[:2] == ["begin", "SET TRANSACTION READ ONLY"]
    assert log[2].startswith("SELECT feed.row_id, feed.kind")
    assert log[3:] == ["close", "close"]  # the transaction, then the session
