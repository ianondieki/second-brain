"""Embeddings (REQ-EMB-01; ADR-005 decision 6; docs/spec/08 Embeddings). Anthropic has no embeddings endpoint.

- ``BgeM3Embedder``: self-hosted bge-m3 (model id and version in ``ai/models.yaml``; 1024 dimensions,
  multilingual incl. Swahili) through
  sentence-transformers on the worker, fp16 or int8. sentence-transformers is not a dependency (not in uv.lock):
  it is imported lazily, and the worker image installs it from the CPU-only torch index only after the human
  approves bge-m3 (weights and image size; Docker has 4 GB). The weights are loaded with
  ``local_files_only``: code never downloads them (the image must carry them; the human approves that first).
- ``FakeEmbedder``: deterministic 1024-dimension bag-of-words unit vectors (``bag_of_words_vector``: SHAKE-256
  feature hashing of the text's words), for tests, CI and the demo. Texts that share words are close and texts with
  no shared word are near-orthogonal, but paraphrases are not; ``pin`` and ``vector_with_similarity`` let a test
  choose vectors.
- ``VoyageAdapter``: a hosted option behind a DPA flag, off in Release 1 (a stub that refuses).

Every stored vector carries ``embed_model`` and ``embed_version``; when either changes, ``bridge.jobs.reembed``
re-embeds the rows that differ.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import math
import re
import threading
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from bridge.config import Settings
from bridge.llm.registry import EmbeddingPolicy

EMBED_DIM = 1024
FAKE_MODEL = "fake-shake256"
FAKE_VERSION = "2"  # 1: one hash of the whole text; 2: bag of words (stored v1 vectors are re-embedded)

Vector = list[float]
Precision = Literal["fp32", "fp16", "int8"]
_SPACES = re.compile(r"\s+")
_TOKEN = re.compile(r"[^\W_]+")  # runs of letters and digits
MIN_TOKEN_CHARS = 3
STOP_WORDS = frozenset(
    {
        # English
        "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "has", "have", "had", "but",
        "not", "you", "your", "our", "their", "they", "its", "into", "than", "then", "them", "who", "what", "when",
        "which", "will", "can", "all", "any", "also",
        # Swahili
        "na", "kwa", "ya", "wa", "za", "katika", "ni", "hii", "huu", "hiyo", "kama", "lakini", "pia", "sana",
        "kwamba", "ambayo", "ambao", "kuwa", "cha", "vya",
    }
)  # fmt: skip


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


def tokens(text: str) -> list[str]:
    """The words of the normalised text that carry meaning: letter/digit runs of at least three characters that are
    not on the short English and Swahili stop list, in order and with repeats."""
    return [t for t in _TOKEN.findall(normalise_text(text)) if len(t) >= MIN_TOKEN_CHARS and t not in STOP_WORDS]


@functools.lru_cache(maxsize=8192)
def _token_vector(token: str, dim: int) -> tuple[float, ...]:
    return tuple(hashed_vector(token, dim))


def bag_of_words_vector(text: str, dim: int = EMBED_DIM) -> Vector:
    """A deterministic unit vector of the text's words (feature hashing; hashlib only, so portable).

    Each distinct token (``tokens``) contributes its own SHAKE-256 direction (``hashed_vector(token)``) weighted by
    ``1 + ln(tf)``; the sum is unit-normalised. Random directions in 1,024 dimensions are near-orthogonal (cosine
    about 0 with a spread of about 0.03), so the cosine of two texts approximates the weighted overlap of their
    vocabularies: shared words give a positive cosine (equal word sets give 1, whatever the order or case), texts
    with no shared word give a cosine near zero. Synonyms and paraphrases are not close: this is a fake, not a model.
    A text with no token (empty, punctuation, stop words only) falls back to ``hashed_vector(text)``.
    """
    counts: dict[str, int] = {}
    for token in tokens(text):
        counts[token] = counts.get(token, 0) + 1
    total = [0.0] * dim
    for token, tf in counts.items():
        weight = 1.0 + math.log(tf)
        for i, x in enumerate(_token_vector(token, dim)):
            total[i] += weight * x
    norm = math.sqrt(math.fsum(x * x for x in total))
    if not counts or norm == 0 or not math.isfinite(norm):
        return hashed_vector(text, dim)
    return [x / norm for x in total]


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
    """Deterministic vectors for tests, CI and the demo: ``bag_of_words_vector`` of the text, unless ``pinned`` (or
    ``pin``) maps the normalised text to a chosen vector."""

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
        return self._pinned.get(normalise_text(text)) or bag_of_words_vector(text, self.dim)

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        self.calls.append(list(texts))
        return [self.vector_for(text) for text in texts]


class BgeM3Embedder:
    """bge-m3 on the worker; ``model_id`` and ``version`` come from ``ai/models.yaml``. ``model_path`` is a local
    directory with the weights (default: the Hugging Face cache); nothing is downloaded. The model loads once, on
    first use and under a lock (encodes run in worker threads, so two first calls could otherwise load twice)."""

    dim = EMBED_DIM

    def __init__(
        self,
        *,
        model_id: str,
        version: str,
        model_path: Path | None = None,
        precision: Precision = "int8",
        batch_size: int = 16,
        device: str = "cpu",
    ) -> None:
        self._model_id = model_id
        self._version = version
        self._source = str(model_path) if model_path is not None else model_id
        self._precision = precision
        self._batch_size = batch_size
        self._device = device
        self._loaded: Any = None
        self._load_lock = threading.Lock()

    @property
    def model(self) -> str:
        return self._model_id

    @property
    def version(self) -> str:
        """``embed_version``: the registry version plus the precision (int8 and fp16 vectors differ slightly)."""
        return f"{self._version}-{self._precision}"

    def _load(self) -> Any:
        try:
            from sentence_transformers import SentenceTransformer  # not a dependency: installed in the worker image
        except ImportError as exc:
            raise EmbedderUnavailable(
                "sentence-transformers is not installed: the worker image adds it (CPU torch index) once bge-m3 is"
                " approved (REQ-EMB-01)"
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

    def _model_once(self) -> Any:
        with self._load_lock:
            if self._loaded is None:
                self._loaded = self._load()
            return self._loaded

    def _encode(self, texts: list[str]) -> list[Vector]:
        rows = self._model_once().encode(texts, batch_size=self._batch_size, normalize_embeddings=True)
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
            model_id=policy.model,
            version=policy.version,
            model_path=settings.embedder_model_path,
            precision=policy.precision,
            batch_size=policy.batch_size,
        )
    if settings.app_env == "production":
        raise ValueError("EMBEDDER=fake is not allowed in production (REQ-EMB-01)")
    return FakeEmbedder()
