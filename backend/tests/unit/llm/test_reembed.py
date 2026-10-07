"""REQ-EMB-01: the re-embed job (bridge/jobs/reembed.py) re-embeds only rows whose model or version differ."""

from __future__ import annotations

from uuid import uuid4

import pytest

from bridge.jobs.reembed import InMemoryEmbeddingTable, ReembedStalled, StaleRow, reembed
from bridge.llm.embeddings import FAKE_MODEL, FAKE_VERSION, FakeEmbedder, Vector


def table_with(fresh: int, old_model: int, old_version: int, missing: int) -> InMemoryEmbeddingTable:
    table = InMemoryEmbeddingTable("teasers")
    for i in range(fresh):
        table.add(uuid4(), f"fresh {i}", model=FAKE_MODEL, version=FAKE_VERSION)
    for i in range(old_model):
        table.add(uuid4(), f"old model {i}", model="old-model", version=FAKE_VERSION)
    for i in range(old_version):
        table.add(uuid4(), f"old version {i}", model=FAKE_MODEL, version="0")
    for i in range(missing):
        table.add(uuid4(), f"missing {i}")
    return table


async def test_only_stale_rows_are_reembedded_in_batches() -> None:
    table = table_with(fresh=3, old_model=4, old_version=2, missing=1)
    embedder = FakeEmbedder()
    report = await reembed(table, embedder, batch_size=3)
    assert (report.table, report.rows, report.batches) == ("teasers", 7, 3)
    assert [len(call) for call in embedder.calls] == [3, 3, 1]
    assert all(row.model == FAKE_MODEL and row.version == FAKE_VERSION for row in table.rows.values())
    assert all(row.vector == embedder.vector_for(row.text) for row in table.rows.values() if "fresh" not in row.text)
    again = await reembed(table, embedder, batch_size=3)
    assert again.rows == 0


async def test_max_rows_bounds_one_run() -> None:
    table = table_with(fresh=0, old_model=5, old_version=0, missing=0)
    report = await reembed(table, FakeEmbedder(), batch_size=2, max_rows=3)
    assert report.rows == 3
    assert len(await table.stale_rows(model=FAKE_MODEL, version=FAKE_VERSION, limit=10)) == 2


async def test_a_table_that_does_not_record_the_version_stalls_loudly() -> None:
    class Forgetful(InMemoryEmbeddingTable):
        async def save(self, row: StaleRow, vector: Vector, *, model: str, version: str) -> bool:
            return True  # claims the write, records nothing

    table = Forgetful("broken")
    table.add(uuid4(), "text")
    with pytest.raises(ReembedStalled):
        await reembed(table, FakeEmbedder(), batch_size=5)
    with pytest.raises(ValueError, match="positive"):
        await reembed(table, FakeEmbedder(), batch_size=0)
    assert StaleRow(uuid4(), "t").text == "t"
