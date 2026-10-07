"""The embedding job over revision 0012's functions (P23-1; REQ-PERS-02, REQ-EMB-01), in a database of its own.

- The tables: a consented developer's profile and a published problem are listed with their text and its hash and
  written; a developer without the consent and a held problem are never listed and never written.
- A write refused because the text changed meanwhile is logged as skipped, not counted, and the row is embedded again
  with its new text in the same run.
- A run clears the vectors of emptied texts, embeds both tables with the configured embedder, logs the counts per table
  and is idempotent; ``max_rows_per_run`` bounds it; an embedder that cannot run ends the run with one line.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from structlog.testing import capture_logs

from bridge.db import create_session_factory
from bridge.embeddings.tables import PerTable, ProblemEmbeddingTable, ProfileEmbeddingTable
from bridge.embeddings.worker import run_embeddings
from bridge.jobs.reembed import StaleRow, reembed
from bridge.llm.embeddings import FAKE_MODEL, FAKE_VERSION, EmbedderUnavailable, FakeEmbedder, Vector
from tests.integration import world as w
from tests.integration.embeddings.job_world import Interrupting, committed, consented_developer, deps, problem, profile
from tests.integration.embeddings.schema_world import EMPTY_PROBLEM, EMPTY_PROFILE, named_niche, problem_text, sha
from tests.integration.engagements import tracker as t
from tests.integration.teams.schema_world import developer

FAKE = (FAKE_MODEL, FAKE_VERSION)


def first(vector: Vector) -> object:
    """The vector's first value as stored (real, float32)."""
    return pytest.approx(vector[0], rel=1e-6)


async def test_the_tables_list_and_write_only_what_may_be_embedded(
    job_owner: AsyncEngine, job_app: AsyncEngine
) -> None:
    """Given a developer who granted profiling, one who refused it, a published problem and a held one, When the tables
    are read and written as the worker, Then the consented profile and the published problem are listed with their
    text and its hash and written with the fake's vector, model and version; the others are not listed, and a write
    for them is refused (false) and leaves nothing."""
    consented = await consented_developer(job_owner, "consented")
    refused = await consented_developer(job_owner, "refused", granted=False)
    async with committed(job_owner) as conn:
        author = await developer(conn, "author", peers=False)
        topic = await named_niche(conn, "Problems of the tables")
        published = await w.add_problem(conn, author, topic)
        held = await w.add_problem(conn, author, topic, moderation_state="held")
        held_text = await problem_text(conn, held)
    factory = create_session_factory(job_app)
    profiles, problems = ProfileEmbeddingTable(factory), ProblemEmbeddingTable(factory)
    embedder = FakeEmbedder()

    listed = {row.id: row for row in await profiles.stale_rows(model=FAKE_MODEL, version=FAKE_VERSION, limit=1000)}
    assert consented in listed
    assert refused not in listed
    row = listed[consented]
    assert row.text.startswith("Consented ")
    assert row.text_hash == sha(row.text)
    vector = embedder.vector_for(row.text)
    assert await profiles.save(row, vector, model=FAKE_MODEL, version=FAKE_VERSION) is True
    stored = await profile(job_owner, consented)
    assert (stored["first"], stored["embed_model"], stored["embed_version"]) == (first(vector), *FAKE)
    assert stored["profile_embedding_hash"] == row.text_hash
    never = StaleRow(refused, row.text, row.text_hash)
    assert await profiles.save(never, vector, model=FAKE_MODEL, version=FAKE_VERSION) is False
    assert await profile(job_owner, refused) == EMPTY_PROFILE

    found = {row.id: row for row in await problems.stale_rows(model=FAKE_MODEL, version=FAKE_VERSION, limit=1000)}
    assert published in found
    assert held not in found
    assert found[published].text_hash == sha(found[published].text)
    assert await problems.save(found[published], vector, model=FAKE_MODEL, version=FAKE_VERSION) is True
    assert (await problem(job_owner, published))["embedding_hash"] == found[published].text_hash
    blocked = StaleRow(held, held_text, sha(held_text))
    assert await problems.save(blocked, vector, model=FAKE_MODEL, version=FAKE_VERSION) is False
    assert await problem(job_owner, held) == EMPTY_PROBLEM


async def test_a_write_refused_after_an_edit_is_logged_and_the_new_text_embedded(
    job_owner: AsyncEngine, job_app: AsyncEngine
) -> None:
    """Given a consented developer whose headline is edited (and committed) after the listing, When the profiles are
    re-embedded, Then the first write is refused and logged as skipped, and the row is listed again with its new hash
    and written in the same run with the new text's vector."""
    user = await consented_developer(job_owner, "edited")

    async def edit() -> None:
        async with committed(job_owner) as conn:
            await t.run(conn, "UPDATE developer_profiles SET headline = 'Edited mid-run' WHERE user_id = :u", u=user)

    embedder = Interrupting(edit)
    with capture_logs() as logs:
        report = await reembed(ProfileEmbeddingTable(create_session_factory(job_app)), embedder, batch_size=1000)
    assert report.refused == 1
    assert report.abandoned == 0
    skipped = [entry for entry in logs if entry["event"] == "embeddings.reembed.skipped"]
    assert [(entry["table"], entry["attempt"]) for entry in skipped] == [("developer_profiles", 1)]
    stored = await profile(job_owner, user)
    async with committed(job_owner) as conn:
        text = await t.run(conn, "SELECT profile_embedding_text(:u)", u=user)
    assert text.startswith("Edited mid-run\n")
    assert stored["profile_embedding_hash"] == sha(text)
    assert stored["first"] == first(embedder.vector_for(text))


async def test_a_run_embeds_both_tables_logs_the_counts_and_is_idempotent(
    job_owner: AsyncEngine, job_app: AsyncEngine
) -> None:
    """Given a consented developer and a published problem never embedded, When the job runs twice, Then the first
    run writes both with the fake's vectors and logs one line per table (written, cleared, still stale: none), and the
    second writes nothing."""
    user = await consented_developer(job_owner, "run")
    async with committed(job_owner) as conn:
        author = await developer(conn, "run-author", peers=False)
        published = await w.add_problem(conn, author, await named_niche(conn, "Problems of the run"))
    embedder = FakeEmbedder()
    with capture_logs() as logs:
        report = await run_embeddings(deps(job_app, embedder))
    assert not report.unavailable
    assert [r.table for r in report.tables] == ["developer_profiles", "problems"]
    assert all(r.rows >= 1 and r.refused == 0 for r in report.tables)
    assert report.stale == PerTable(0, 0)
    lines = [(e["table"], e["stale"], e["log_level"]) for e in logs if e["event"] == "embeddings.run"]
    assert lines == [("developer_profiles", 0, "info"), ("problems", 0, "info")]
    stored = await profile(job_owner, user)
    async with committed(job_owner) as conn:
        text = await t.run(conn, "SELECT profile_embedding_text(:u)", u=user)
        statement = await problem_text(conn, published)
    expected = first(embedder.vector_for(text))
    assert (stored["first"], stored["embed_model"], stored["embed_version"]) == (expected, *FAKE)
    assert (await problem(job_owner, published))["first"] == first(embedder.vector_for(statement))

    again = await run_embeddings(deps(job_app, embedder))
    assert [(r.rows, r.batches) for r in again.tables] == [(0, 0), (0, 0)]


async def test_the_per_run_cap_bounds_each_table(job_owner: AsyncEngine, job_app: AsyncEngine) -> None:
    """Given three consented developers and three published problems never embedded, When the job runs with a cap of
    one row, Then it writes one row of each table and logs the rest as still stale; the next runs finish them."""
    users = [await consented_developer(job_owner, f"capped{n}") for n in range(3)]
    async with committed(job_owner) as conn:
        author = await developer(conn, "cap-author", peers=False)
        topic = await named_niche(conn, "Problems of the cap")
        for _ in range(3):
            await w.add_problem(conn, author, topic)
    report = await run_embeddings(deps(job_app, max_rows=1))
    assert [r.rows for r in report.tables] == [1, 1]
    assert report.stale is not None
    assert report.stale.profiles >= 2
    assert report.stale.problems >= 2
    rest = await run_embeddings(deps(job_app, max_rows=500))
    assert rest.stale == PerTable(0, 0)
    for user in users:
        assert (await profile(job_owner, user))["embed_model"] == FAKE_MODEL


async def test_an_emptied_text_loses_its_vector_on_the_next_run(job_owner: AsyncEngine, job_app: AsyncEngine) -> None:
    """Given an embedded profile whose only content, a liked niche, is removed, When the job runs, Then it starts by
    clearing that vector (counted) and does not list the profile again."""
    user = await consented_developer(job_owner, "emptied")
    await run_embeddings(deps(job_app))
    assert (await profile(job_owner, user))["embed_model"] == FAKE_MODEL
    async with committed(job_owner) as conn:
        await t.run(conn, "DELETE FROM developer_niches WHERE user_id = :u", u=user)
    report = await run_embeddings(deps(job_app))
    assert report.cleared.profiles >= 1
    assert await profile(job_owner, user) == EMPTY_PROFILE


async def test_an_embedder_that_cannot_run_ends_the_run_with_one_line(
    job_owner: AsyncEngine, job_app: AsyncEngine
) -> None:
    """Given a stale profile and an embedder whose weights are missing, When the job runs, Then it logs one warning
    and ends normally: no exception, no retry, nothing written; the next run with a working embedder writes it."""

    class Missing(FakeEmbedder):
        async def embed(self, texts: Sequence[str]) -> list[Vector]:
            raise EmbedderUnavailable("bge-m3 weights are not available locally")

    user = await consented_developer(job_owner, "unavailable")
    missing = Missing()
    with capture_logs() as logs:
        report = await run_embeddings(deps(job_app, missing))
    assert (report.unavailable, report.tables, report.stale) == (True, (), None)
    warnings = [e for e in logs if e["log_level"] == "warning"]
    assert [(e["event"], e["model"]) for e in warnings] == [("embeddings.unavailable", FAKE_MODEL)]
    assert not [e for e in logs if e["event"] == "embeddings.run"]
    assert await profile(job_owner, user) == EMPTY_PROFILE
    await run_embeddings(deps(job_app))
    assert (await profile(job_owner, user))["embed_model"] == FAKE_MODEL
