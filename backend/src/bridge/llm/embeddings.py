"""Embeddings (REQ-EMB-01; ADR-005 decision 6; docs/spec/08 Embeddings). Anthropic has no embeddings endpoint.

- ``BgeM3Embedder``: self-hosted ``BAAI/bge-m3`` (1024 dimensions, multilingual incl. Swahili) through
  sentence-transformers on the worker, fp16 or int8. The library is an optional extra
  (``uv sync --extra embeddings``; CI does not install it) imported lazily, and the weights are loaded with
  ``local_files_only``: code never downloads them (the image must carry them; the human approves that first).
- ``FakeEmbedder``: deterministic 1024-dimension unit vectors from a SHAKE-256 hash of the normalised text, for
  tests and CI. Similar texts are NOT close; ``pin`` and ``vector_with_similarity`` let a test choose vectors.
- ``VoyageAdapter``: a hosted option behind a DPA flag, off in Release 1 (a stub that refuses).

Every stored vector carries ``embed_model`` and ``embed_version``; when either changes, ``bridge.jobs.reembed``
re-embeds the rows that differ.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from bridge.config import Settings
from bridge.llm.registry import EmbeddingPolicy

EMBED_DIM = 1024
BGE_M3_MODEL = "BAAI/bge-m3"
BGE_M3_VERSION = "1"  # bump with any change to the weights or the encode settings; the precision is appended
FAKE_MODEL = "fake-shake256"
FAKE_VERSION = "1"

Vector = list[float]
Precision = Literal["fp32", "fp16", "int8"]
_SPACES = re.compile(r"\s+")


class EmbedderUnavailable(RuntimeError):
    """The configured embedder cannot run here (library not installed, weights missing, no DPA)."""


class Embedder(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def dim(self) -> int: ...

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        """One unit vector of ``dim`` floats per text, in order."""
        ...


def normalise_text(text: str) -> str:
    """The text a vector is keyed on: NFKC, case-folded, whitespace collapsed."""
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()


def unit(vector: Sequence[float], dim: int = EMBED_DIM) -> Vector:
    if len(vector) != dim:
        raise ValueError(f"expected {dim} dimensions, got {len(vector)}")
    norm = math.sqrt(math.fsum(x * x for x in vector))
    if norm == 0 or not math.isfinite(norm):
        raise ValueError("cannot normalise a zero or non-finite vector")
    return [x / norm for x in vector]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return math.fsum(x * y for x, y in zip(unit(a, len(a)), unit(b, len(b)), strict=True))


def hashed_vector(text: str, dim: int = EMBED_DIM) -> Vector:
    """A deterministic unit vector from SHAKE-256 of the normalised text (portable across platforms)."""
    raw = hashlib.shake_256(normalise_text(text).encode("utf-8")).digest(dim * 4)
    values = [int.from_bytes(raw[i : i + 4], "big") / 2**31 - 1.0 for i in range(0, dim * 4, 4)]
    return unit(values, dim)


def vector_with_similarity(base: Sequence[float], similarity: float, *, seed: str = "orthogonal") -> Vector:
    """A unit vector whose cosine similarity with ``base`` is ``similarity`` (for pinning similar texts in tests)."""
    if not -1.0 <= similarity <= 1.0:
        raise ValueError("cosine similarity lies in [-1, 1]")
    b = unit(base, len(base))
    r = hashed_vector(seed, len(base))
    along = math.fsum(x * y for x, y in zip(r, b, strict=True))
    perpendicular = unit([x - along * y for x, y in zip(r, b, strict=True)], len(base))
    side = math.sqrt(max(0.0, 1.0 - similarity * similarity))
    return unit([similarity * x + side * y for x, y in zip(b, perpendicular, strict=True)], len(base))


class FakeEmbedder:
    """Deterministic vectors for tests and CI; ``pinned`` (or ``pin``) maps chosen texts to chosen vectors."""

    model = FAKE_MODEL
    version = FAKE_VERSION
    dim = EMBED_DIM

    def __init__(self, pinned: Mapping[str, Sequence[float]] | None = None) -> None:
        self._pinned: dict[str, Vector] = {}
        self.calls: list[list[str]] = []
        for text, vector in (pinned or {}).items():
            self.pin(text, vector)

    def pin(self, text: str, vector: Sequence[float]) -> None:
        self._pinned[normalise_text(text)] = unit(vector, self.dim)

    def vector_for(self, text: str) -> Vector:
        return self._pinned.get(normalise_text(text)) or hashed_vector(text, self.dim)

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        self.calls.append(list(texts))
        return [self.vector_for(text) for text in texts]


class BgeM3Embedder:
    """``BAAI/bge-m3`` on the worker. ``model_path`` is a local directory with the weights (default: the Hugging Face
    cache); nothing is downloaded. The model loads on first use, in a worker thread like every encode."""

    model = BGE_M3_MODEL
    dim = EMBED_DIM

    def __init__(
        self,
        *,
        model_path: Path | None = None,
        precision: Precision = "int8",
        batch_size: int = 16,
        device: str = "cpu",
    ) -> None:
        self._source = str(model_path) if model_path is not None else BGE_M3_MODEL
        self._precision = precision
        self._batch_size = batch_size
        self._device = device
        self._loaded: Any = None

    @property
    def version(self) -> str:
        return f"{BGE_M3_VERSION}-{self._precision}"

    def _load(self) -> Any:
        try:
            from sentence_transformers import SentenceTransformer  # optional extra, never installed in CI
        except ImportError as exc:
            raise EmbedderUnavailable(
                "sentence-transformers is not installed; the worker needs `uv sync --extra embeddings` (REQ-EMB-01)"
            ) from exc
        try:
            loaded = SentenceTransformer(self._source, device=self._device, local_files_only=True)
        except OSError as exc:
            raise EmbedderUnavailable(f"bge-m3 weights are not available locally at {self._source}") from exc
        if self._precision == "fp16":
            loaded = loaded.half()
        elif self._precision == "int8":
            import torch

            loaded = torch.quantization.quantize_dynamic(loaded, {torch.nn.Linear}, dtype=torch.qint8)
        return loaded

    def _encode(self, texts: list[str]) -> list[Vector]:
        if self._loaded is None:
            self._loaded = self._load()
        rows = self._loaded.encode(texts, batch_size=self._batch_size, normalize_embeddings=True)
        return [unit([float(x) for x in row], self.dim) for row in rows]

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        return await asyncio.to_thread(self._encode, list(texts))


class VoyageAdapter:
    """Hosted embeddings, optional behind a DPA flag (ADR-005 decision 6). Off in Release 1: a hosted embedder adds a
    sub-processor for proposal text, so it needs a signed DPA and an approved adapter; until then it refuses."""

    model = "voyage"
    version = "0"
    dim = EMBED_DIM

    def __init__(self, *, dpa_signed: bool = False) -> None:
        if not dpa_signed:
            raise EmbedderUnavailable("VoyageAdapter needs a signed DPA; it is off in Release 1 (ADR-005)")

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        raise NotImplementedError("VoyageAdapter is a stub until the DPA and the adapter are approved")


def embedder_from_settings(settings: Settings, policy: EmbeddingPolicy) -> Embedder:
    """``EMBEDDER=bge-m3`` builds the real embedder (loaded on first use); ``fake`` is refused in production."""
    if settings.embedder == "bge-m3":
        return BgeM3Embedder(
            model_path=settings.embedder_model_path, precision=policy.precision, batch_size=policy.batch_size
        )
    if settings.app_env == "production":
        raise ValueError("EMBEDDER=fake is not allowed in production (REQ-EMB-01)")
    return FakeEmbedder()
