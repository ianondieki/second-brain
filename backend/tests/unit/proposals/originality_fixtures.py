"""Shared inputs of the originality check's unit tests (REQ-PROP-04): fixture proposals with Tier-1 and Tier-2
fields, and an in-memory pool that indexes them exactly as publish does (``submission_text`` of the whole record, so
a Tier-2 field reaching the index or the check would change the answers)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from bridge.llm.embeddings import FakeEmbedder, Vector, cosine
from bridge.proposals import originality as o
from bridge.proposals.originality import PublishedTeaser
from bridge.proposals.sanitise import TIER1_FIELDS

SUBMITTER = UUID("01900000-0000-7000-8000-00000000a001")
OTHER = UUID("01900000-0000-7000-8000-00000000a002")
THIRD = UUID("01900000-0000-7000-8000-00000000a003")
SESSION = UUID("01900000-0000-7000-8000-00000000a0e1")
DRAFT_ID = UUID("01900000-0000-7000-8000-00000000b001")
OWN_PUBLISHED_ID = UUID("01900000-0000-7000-8000-00000000b002")
COPY_ID = UUID("01900000-0000-7000-8000-00000000b003")
UNRELATED_ID = UUID("01900000-0000-7000-8000-00000000b004")
HELD_ID = UUID("01900000-0000-7000-8000-00000000b005")

TEASER = {
    "title": "Cold-chain alerts for dairy farmers",
    "problem_statement": "Milk spoils before it reaches a cooler because nobody knows the cooler has warmed up.",
    "impact_claims": "Cuts spoilage for forty farms in the first season.",
    "summary": "Farmers get an SMS the moment a milk cooler starts to warm, so less milk spoils on the way.",
}
UNRELATED = {
    "title": "Market prices for fishers",
    "problem_statement": "Fishers in Kisumu sell their catch late because prices reach them after the boats land.",
    "impact_claims": "Better prices for two hundred fishers.",
    "summary": "A daily price board on basic phones for lake fishers and traders.",
}


@dataclass
class Record:
    proposal_id: UUID
    owner_id: UUID
    fields: Mapping[str, str]  # Tier 1 and Tier 2, as the editor holds them
    published: bool = True
    clear: bool = True


@dataclass
class InMemoryPool:
    """``TeaserPool`` over records, indexed like ``index_teaser`` (buckets and vectors of ``submission_text``)."""

    records: Sequence[Record]
    embedder: FakeEmbedder = field(default_factory=FakeEmbedder)

    def _pool(self, owner_id: UUID, proposal_id: UUID) -> list[Record]:
        return [
            r
            for r in self.records
            if r.published and r.clear and r.owner_id != owner_id and r.proposal_id != proposal_id
        ]

    @staticmethod
    def _teaser(record: Record) -> PublishedTeaser:
        tier1 = {name: value for name, value in record.fields.items() if name in TIER1_FIELDS and value}
        return PublishedTeaser(record.proposal_id, record.owner_id, tier1)

    async def size(self, *, owner_id: UUID, proposal_id: UUID) -> int:
        return len(self._pool(owner_id, proposal_id))

    async def by_buckets(
        self, buckets: Sequence[tuple[int, int]], *, owner_id: UUID, proposal_id: UUID, limit: int
    ) -> list[PublishedTeaser]:
        wanted = set(buckets)
        hits = []
        for record in self._pool(owner_id, proposal_id):
            mine = set(o.lsh_bands(o.signature(o.shingles(o.submission_text(record.fields)))))
            if shared := len(mine & wanted):
                hits.append((shared, record))
        hits.sort(key=lambda item: (-item[0], str(item[1].proposal_id)))
        return [self._teaser(record) for _, record in hits[:limit]]

    async def nearest(
        self, vector: Vector, *, model: str, version: str, owner_id: UUID, proposal_id: UUID, limit: int
    ) -> list[tuple[PublishedTeaser, float]]:
        assert (model, version) == (self.embedder.model, self.embedder.version)
        scored = [
            (cosine(vector, self.embedder.vector_for(o.submission_text(r.fields))), r)
            for r in self._pool(owner_id, proposal_id)
        ]
        scored.sort(key=lambda item: (-item[0], str(item[1].proposal_id)))
        return [(self._teaser(record), score) for score, record in scored[:limit]]


def with_tier2(fields: Mapping[str, str], secret: str) -> dict[str, str]:
    """The teaser plus confidential fields carrying ``secret``."""
    return {
        **fields,
        "approach": f"{secret} approach",
        "architecture": f"{secret} architecture",
        "pricing": f"{secret} pricing",
        "notes": secret,
    }
