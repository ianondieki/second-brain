"""REQ-PERS-02 (P23-1): the SQL tables pass the reader's text hash back to revision 0012's writers; a row without one
(not listed by the table's reader) is refused before any database call."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from bridge.embeddings.tables import READER_MAX, ProblemEmbeddingTable, ProfileEmbeddingTable
from bridge.jobs.reembed import StaleRow
from bridge.llm.embeddings import FAKE_MODEL, FAKE_VERSION, FakeEmbedder


@pytest.mark.parametrize("table", [ProfileEmbeddingTable, ProblemEmbeddingTable])
async def test_a_row_without_its_readers_hash_is_never_written(table: Any) -> None:
    def no_database() -> Any:
        raise AssertionError("no session is opened for a row without its hash")

    row = StaleRow(uuid4(), "text")
    vector = FakeEmbedder().vector_for(row.text)
    with pytest.raises(ValueError, match="text hash"):
        await table(no_database).save(row, vector, model=FAKE_MODEL, version=FAKE_VERSION)


def test_the_tables_name_their_columns_and_the_readers_largest_page() -> None:
    assert (ProfileEmbeddingTable.name, ProblemEmbeddingTable.name) == ("developer_profiles", "problems")
    assert READER_MAX == 1000
