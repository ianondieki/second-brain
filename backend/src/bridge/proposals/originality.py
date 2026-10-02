"""The originality check (REQ-PROP-04; docs/spec/06 6.3; docs/spec/09). Informational, never blocking.

What it compares: the submitter's saved Tier-1 teaser text (``TIER1_FIELDS`` through ``sanitise.plain_text``; every
other field, Tier 2 above all, is ignored by construction: ``submission_text`` picks those four names) against
**other owners'** published teasers that are clear of moderation, and nothing else. Two signals, plain code:

- **MinHash LSH** in plain Python (no dependency, D-36): 5-word shingles, 128 hashes (blake2b, one fixed salt per
  hash, so signatures and buckets are the same on every run and machine), 16 bands of 8 rows. ``index_teaser`` writes
  the bands to ``proposal_lsh_bands`` at publish; a check reads the teasers sharing a bucket and computes the exact
  Jaccard of the shingle sets.
- **Teaser embeddings** through the configured ``Embedder`` (``EMBEDDER``; the fake in tests and the demo):
  ``index_teaser`` stores the vector with its model and version; a check compares only vectors of the same model and
  version (cosine).

The answer is a coarse band (``band_for``; the thresholds are ``policy.yaml`` ``originality``) and ``compared``, how
many teasers were in the pool (never which). Numbers, matched ids and other owners' text never leave this module
except toward the explainer (``bridge.proposals.originality_explainer``), which sees Tier 1 only.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Final

from bridge.models.enums import OriginalityBand
from bridge.proposals.originality_policy import OriginalityPolicy
from bridge.proposals.sanitise import TIER1_FIELDS, plain_text

SHINGLE_WORDS: Final = 5
NUM_HASHES: Final = 128
BANDS: Final = 16
ROWS: Final = 8
# One 16-byte blake2b salt per hash function: the index format. Changing any of these four constants changes every
# stored bucket, so it needs a re-index of proposal_lsh_bands (never a silent edit).
_SALTS: Final = tuple(i.to_bytes(4, "big") + b"bridge-mh-v1" for i in range(NUM_HASHES))
_BAND_PERSON: Final = b"bridge-lsh-v1"
_WORD: Final = re.compile(r"\w+")

if BANDS * ROWS != NUM_HASHES:  # pragma: no cover - a constant mistake
    raise RuntimeError("BANDS * ROWS must equal NUM_HASHES")


def submission_text(fields: Mapping[str, object]) -> str:
    """The Tier-1 teaser text a check reads and an index stores: ``TIER1_FIELDS`` in order, as plain text. Any other
    key (a Tier-2 field, a link) is ignored, whatever its value."""
    parts = [plain_text(value) for name in TIER1_FIELDS if isinstance(value := fields.get(name), str)]
    return "\n".join(part for part in parts if part)


def words(text: str) -> list[str]:
    return _WORD.findall(plain_text(text).casefold())


def shingles(text: str, size: int = SHINGLE_WORDS) -> frozenset[str]:
    """Every run of ``size`` consecutive words; a shorter, non-empty text is one shingle of all its words."""
    found = words(text)
    if not found:
        return frozenset()
    if len(found) < size:
        return frozenset({" ".join(found)})
    return frozenset(" ".join(found[i : i + size]) for i in range(len(found) - size + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def signature(items: Iterable[str]) -> tuple[int, ...]:
    """The MinHash signature: per salted hash, the smallest 64-bit value over the shingles (empty: no signature)."""
    encoded = [item.encode("utf-8") for item in items]
    if not encoded:
        return ()
    return tuple(
        min(int.from_bytes(hashlib.blake2b(item, digest_size=8, salt=salt).digest(), "big") for item in encoded)
        for salt in _SALTS
    )


def estimate(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    """The Jaccard estimate of two signatures: the share of equal minimums."""
    if not a or len(a) != len(b):
        return 0.0
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def lsh_bands(sig: tuple[int, ...]) -> list[tuple[int, int]]:
    """``(band, bucket)`` per band of ``ROWS`` minimums; the bucket is a signed 64-bit hash (a BIGINT column)."""
    if len(sig) != NUM_HASHES:
        return []
    found = []
    for band in range(BANDS):
        rows = b"".join(value.to_bytes(8, "big") for value in sig[band * ROWS : (band + 1) * ROWS])
        digest = hashlib.blake2b(rows, digest_size=8, person=_BAND_PERSON).digest()
        found.append((band, int.from_bytes(digest, "big", signed=True)))
    return found


def band_for(jaccard_value: float, cosine_value: float | None, policy: OriginalityPolicy) -> OriginalityBand:
    """The coarse band: high at or above either high threshold, some at or above the "some" cosine, else none."""
    if jaccard_value >= policy.jaccard_high or (cosine_value is not None and cosine_value >= policy.cosine_high):
        return OriginalityBand.HIGH_OVERLAP
    if cosine_value is not None and cosine_value >= policy.cosine_some:
        return OriginalityBand.SOME_OVERLAP
    return OriginalityBand.NONE
