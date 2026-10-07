"""REQ-PERS-02, REQ-EMB-01: a write the table refuses is not counted as done (bridge/jobs/reembed.py). A row whose text
changed between the listing and the write comes back with its new hash and is embedded again; a row that keeps changing
is tried at most 1 + ``MAX_RETRIES`` times in one run and then left for the next run; a row that left the set is simply
not listed again. A row written in this run that comes back with the same hash (its vector cleared since: a consent
withdrawn and granted again) is one more try, abandoned after ``MAX_RETRIES``. None of these is a stall: only a table
that keeps no hash stalls loudly when a written row comes back."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest
from structlog.testing import capture_logs

from bridge.jobs import reembed as reembed_module
from bridge.jobs.reembed import MAX_RETRIES, InMemoryEmbeddingTable, StaleRow, reembed
from bridge.llm.embeddings import FAKE_MODEL, FAKE_VERSION, FakeEmbedder, Vector
from bridge.logging import get_logger


@pytest.fixture(autouse=True)
def fresh_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """A logger of the test's own: one cached under an earlier logging configuration (``create_app`` configures it
    again in other tests) would not reach ``capture_logs``."""
    monkeypatch.setattr(reembed_module, "log", get_logger(reembed_module.__name__))


class EditedOnce(InMemoryEmbeddingTable):
    """The text of ``row`` changes once, just before its first write (an edit that commits mid-run)."""

    def __init__(self, row: UUID) -> None:
        super().__init__("edited", hashed=True)
        self.row, self.edited = row, False

    async def save(self, row: StaleRow, vector: Vector, *, model: str, version: str) -> bool:
        if row.id == self.row and not self.edited:
            self.edited = True
            self.rows[row.id].text += " (edited)"
        return await super().save(row, vector, model=model, version=version)


class Restless(InMemoryEmbeddingTable):
    """The text of ``row`` changes before every write (or only before the first ``settles_after`` writes)."""

    def __init__(self, row: UUID, settles_after: int | None = None) -> None:
        super().__init__("restless", hashed=True)
        self.row, self.writes, self.settles_after = row, 0, settles_after

    async def save(self, row: StaleRow, vector: Vector, *, model: str, version: str) -> bool:
        if row.id == self.row:
            self.writes += 1
            if self.settles_after is None or self.writes <= self.settles_after:
                self.rows[row.id].text = f"draft {self.writes}"
        return await super().save(row, vector, model=model, version=version)


class Withdrawn(InMemoryEmbeddingTable):
    """``row`` leaves the set before its write (a consent withdrawn, a problem held): refused, never listed again."""

    def __init__(self, row: UUID) -> None:
        super().__init__("withdrawn", hashed=True)
        self.row = row

    async def save(self, row: StaleRow, vector: Vector, *, model: str, version: str) -> bool:
        if row.id == self.row:
            del self.rows[row.id]
        return await super().save(row, vector, model=model, version=version)


async def test_a_text_edited_before_its_write_is_embedded_again_with_its_new_text() -> None:
    row = uuid4()
    table = EditedOnce(row)
    table.add(row, "first text")
    for n in range(3):
        table.add(uuid4(), f"other {n}")
    embedder = FakeEmbedder()
    report = await reembed(table, embedder, batch_size=2)
    assert (report.rows, report.refused, report.abandoned) == (4, 1, 0)
    stored = table.rows[row]
    assert stored.text == "first text (edited)"
    assert stored.vector == embedder.vector_for("first text (edited)")
    assert await table.stale_rows(model=FAKE_MODEL, version=FAKE_VERSION, limit=10) == []


async def test_a_row_that_never_settles_is_tried_three_times_then_left_for_the_next_run() -> None:
    row = uuid4()
    table = Restless(row)
    table.add(row, "draft 0")
    others = [uuid4() for _ in range(5)]
    for n, other in enumerate(others):
        table.add(other, f"steady {n}")
    with capture_logs() as logs:  # a finite cap: without the abandoned-row exclusion the run ends (and fails) at 50
        report = await reembed(table, FakeEmbedder(), batch_size=2, max_rows=50)
    assert table.writes == 1 + MAX_RETRIES == 3
    assert (report.rows, report.refused, report.abandoned) == (5, 3, 1)
    assert all(table.rows[other].model == FAKE_MODEL for other in others)  # the page saw past the abandoned row
    assert table.rows[row].vector is None
    skipped = [entry for entry in logs if entry["event"] == "embeddings.reembed.skipped"]
    assert [(entry["table"], entry["attempt"], entry["log_level"]) for entry in skipped] == [
        ("restless", 1, "info"),
        ("restless", 2, "info"),
        ("restless", 3, "info"),
    ]
    again = await reembed(table, FakeEmbedder(), batch_size=2, max_rows=50)  # the next run tries it again
    assert (again.rows, again.refused, again.abandoned) == (0, 3, 1)


async def test_a_row_that_left_the_set_is_refused_and_not_counted() -> None:
    row = uuid4()
    table = Withdrawn(row)
    table.add(row, "consent withdrawn")
    table.add(uuid4(), "still here")
    report = await reembed(table, FakeEmbedder(), batch_size=5)
    assert (report.rows, report.refused, report.abandoned, report.batches) == (1, 1, 0, 1)


async def test_a_row_edited_after_its_write_is_embedded_again_not_a_stall() -> None:
    """Freshness is by content: a row written in this run and edited before the next page comes back with another hash;
    it is embedded again (the same hash again would be a table that did not record the write: a stall)."""
    row = uuid4()
    table = InMemoryEmbeddingTable("profiles", hashed=True)
    table.add(row, "before")
    embedder = FakeEmbedder()

    class EditAfterWrite(FakeEmbedder):
        async def embed(self, texts: Sequence[str]) -> list[Vector]:
            if self.calls:  # the second batch: the first one's row was written, then edited
                table.rows[row].text = "after"
            return await super().embed(texts)

    table.add(uuid4(), "second")
    report = await reembed(table, EditAfterWrite(), batch_size=1)
    assert table.rows[row].vector == embedder.vector_for("after")
    assert (report.rows, report.refused, report.abandoned) == (2, 0, 0)


async def test_a_row_written_on_its_last_try_is_written_not_abandoned() -> None:
    row = uuid4()
    table = Restless(row, settles_after=MAX_RETRIES)
    table.add(row, "draft 0")
    report = await reembed(table, FakeEmbedder(), batch_size=1)
    assert table.writes == 1 + MAX_RETRIES
    assert (report.rows, report.refused, report.abandoned) == (1, MAX_RETRIES, 0)
    assert table.rows[row].model == FAKE_MODEL


class Regranted(InMemoryEmbeddingTable):
    """``row``'s vector is cleared after each of its first ``clears`` writes (profiling withdrawn and granted again):
    it comes back with the hash it was written for."""

    def __init__(self, row: UUID, clears: int) -> None:
        super().__init__("regranted", hashed=True)
        self.row, self.clears = row, clears

    async def save(self, row: StaleRow, vector: Vector, *, model: str, version: str) -> bool:
        wrote = await super().save(row, vector, model=model, version=version)
        if row.id == self.row and self.clears:
            self.clears -= 1
            self.rows[row.id].vector = None
        return wrote


async def test_a_row_cleared_after_its_write_is_tried_again_not_a_stall() -> None:
    """The reviewer's case: four stale rows, batches of one, the first cleared after its write and listed again with
    the same hash: it is written again and the other three are written; nothing raises."""
    row = uuid4()
    table = Regranted(row, clears=1)
    table.add(row, "toggled")
    others = [uuid4() for _ in range(3)]
    for n, other in enumerate(others):
        table.add(other, f"steady {n}")
    report = await reembed(table, FakeEmbedder(), batch_size=1, max_rows=50)
    assert (report.rows, report.refused, report.abandoned) == (4, 0, 0)
    assert all(stored.vector is not None for stored in table.rows.values())


async def test_a_row_cleared_after_every_write_is_abandoned_after_its_retries() -> None:
    """A toggling user cannot hold a run: the row is tried 1 + MAX_RETRIES times, then left; the rest is written."""
    row = uuid4()
    table = Regranted(row, clears=100)
    table.add(row, "toggled")
    table.add(uuid4(), "steady")
    report = await reembed(table, FakeEmbedder(), batch_size=1, max_rows=50)
    assert (report.rows, report.abandoned) == (2, 1)
    assert table.clears == 100 - (1 + MAX_RETRIES)


async def test_a_hashed_table_that_never_records_abandons_its_rows_without_an_error() -> None:
    class Forgetful(InMemoryEmbeddingTable):
        async def save(self, row: StaleRow, vector: Vector, *, model: str, version: str) -> bool:
            return True  # claims the write, records nothing

    table = Forgetful("forgetful", hashed=True)
    for n in range(2):
        table.add(uuid4(), f"text {n}")
    report = await reembed(table, FakeEmbedder(), batch_size=1, max_rows=50)
    assert (report.rows, report.abandoned, report.batches) == (2, 2, 2 * (1 + MAX_RETRIES))
