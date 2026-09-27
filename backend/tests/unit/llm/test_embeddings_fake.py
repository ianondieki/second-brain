"""REQ-EMB-01: the fixed-vector fake embedder (used by AC-PROP-4 and AC-SCOUT-1), its similarity helpers, the
bge-m3 embedder's wiring (without the library: a stand-in module; the model is never downloaded), the Voyage stub
behind its DPA flag, and the EMBEDDER setting."""

from __future__ import annotations

import math
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from bridge.llm import embeddings
from bridge.llm.embeddings import (
    BGE_M3_MODEL,
    EMBED_DIM,
    FAKE_MODEL,
    BgeM3Embedder,
    EmbedderUnavailable,
    FakeEmbedder,
    VoyageAdapter,
    cosine,
    embedder_from_settings,
    hashed_vector,
    normalise_text,
    unit,
    vector_with_similarity,
)
from tests.unit.llm.helpers import real_registry, settings


def norm(vector: list[float]) -> float:
    return math.sqrt(math.fsum(x * x for x in vector))


async def test_fake_vectors_are_deterministic_unit_1024() -> None:
    first = await FakeEmbedder().embed(["Solar cold rooms", "Mobile money for SACCOs"])
    again = await FakeEmbedder().embed(["Solar cold rooms", "Mobile money for SACCOs"])
    assert first == again
    assert [len(v) for v in first] == [EMBED_DIM, EMBED_DIM]
    assert all(abs(norm(v) - 1) < 1e-9 for v in first)
    assert first[0] != first[1]
    assert abs(cosine(first[0], first[1])) < 0.2  # unrelated hash directions are near-orthogonal


async def test_fake_keys_on_normalised_text() -> None:
    fake = FakeEmbedder()
    assert fake.vector_for("  Hello\n WORLD ") == fake.vector_for("hello world")
    full_width = "".join(chr(ord(c) + 0xFEE0) for c in "Solar")
    assert normalise_text(f"{full_width}  Kiosk") == "solar kiosk"  # NFKC folds full-width letters
    assert fake.model == FAKE_MODEL
    await fake.embed(["x"])
    assert fake.calls == [["x"]]


async def test_pinned_vectors_make_chosen_texts_similar() -> None:
    base = hashed_vector("anchor")
    near = vector_with_similarity(base, 0.93)
    fake = FakeEmbedder({"Solar kiosks for fish traders": base})
    fake.pin("Kiosks powered by the sun for fishmongers", near)
    a, b = await fake.embed(["solar kiosks for fish traders", "Kiosks powered by the sun for fishmongers"])
    assert cosine(a, b) == pytest.approx(0.93, abs=1e-9)


@pytest.mark.parametrize("target", [1.0, 0.95, 0.5, 0.0, -0.3, -1.0])
def test_vector_with_similarity_hits_the_target(target: float) -> None:
    base = hashed_vector("base")
    made = vector_with_similarity(base, target, seed=f"s{target}")
    assert abs(norm(made) - 1) < 1e-9
    assert cosine(base, made) == pytest.approx(target, abs=1e-9)


def test_vector_helpers_refuse_bad_input() -> None:
    with pytest.raises(ValueError, match=r"\[-1, 1\]"):
        vector_with_similarity(hashed_vector("x"), 1.5)
    with pytest.raises(ValueError, match="dimensions"):
        unit([1.0, 2.0])
    with pytest.raises(ValueError, match="zero"):
        unit([0.0] * EMBED_DIM)
    with pytest.raises(ValueError, match="dimensions"):
        FakeEmbedder().pin("x", [1.0])


# ------------------------------------------------------------------------------------------------ bge-m3 wiring


class _Model:
    def __init__(self, source: str, **kwargs: Any) -> None:
        self.source, self.kwargs, self.halved = source, kwargs, False
        self.encoded: list[tuple[list[str], dict[str, Any]]] = []

    def half(self) -> _Model:
        self.halved = True
        return self

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.encoded.append((texts, kwargs))
        return [[2.0] + [0.0] * (EMBED_DIM - 1) for _ in texts]


@pytest.fixture
def stand_in(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stand-in ``sentence_transformers`` and ``torch`` modules: the real ones are not dependencies (REQ-EMB-01)."""
    seen: dict[str, Any] = {}

    def factory(source: str, **kwargs: Any) -> _Model:
        seen["model"] = _Model(source, **kwargs)
        return seen["model"]  # type: ignore[no-any-return]

    def quantize(model: _Model, layers: Any, dtype: Any) -> _Model:
        seen["quantized"] = (layers, dtype)
        return model

    st = types.ModuleType("sentence_transformers")
    st.SentenceTransformer = factory  # type: ignore[attr-defined]
    torch = types.ModuleType("torch")
    torch.nn = types.SimpleNamespace(Linear="Linear")  # type: ignore[attr-defined]
    torch.qint8 = "qint8"  # type: ignore[attr-defined]
    torch.quantization = types.SimpleNamespace(quantize_dynamic=quantize)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", st)
    monkeypatch.setitem(sys.modules, "torch", torch)
    return seen


async def test_bge_m3_loads_local_weights_only_and_quantises(stand_in: dict[str, Any]) -> None:
    embedder = BgeM3Embedder(model_path=Path("/models/bge-m3"), precision="int8", batch_size=8)
    assert "model" not in stand_in  # nothing loads at construction
    [vector] = await embedder.embed(["Habari ya asubuhi"])
    model = stand_in["model"]
    assert model.source == str(Path("/models/bge-m3"))
    assert model.kwargs["local_files_only"] is True  # never downloads
    assert stand_in["quantized"] == ({"Linear"}, "qint8")
    assert model.encoded[0][1] == {"batch_size": 8, "normalize_embeddings": True}
    assert vector[0] == 1.0
    assert (embedder.model, embedder.version, embedder.dim) == (BGE_M3_MODEL, "1-int8", EMBED_DIM)
    await embedder.embed(["again"])
    assert len(model.encoded) == 2  # loaded once


async def test_bge_m3_fp16_and_default_source(stand_in: dict[str, Any]) -> None:
    embedder = BgeM3Embedder(precision="fp16")
    await embedder.embed(["x"])
    assert stand_in["model"].halved
    assert stand_in["model"].source == BGE_M3_MODEL
    assert "quantized" not in stand_in
    await BgeM3Embedder(precision="fp32").embed(["y"])


async def test_bge_m3_without_the_library_or_weights_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(EmbedderUnavailable, match="once bge-m3 is approved"):
        await BgeM3Embedder().embed(["x"])

    def missing(source: str, **kwargs: Any) -> None:
        raise OSError("not cached")

    st = types.ModuleType("sentence_transformers")
    st.SentenceTransformer = missing  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", st)
    with pytest.raises(EmbedderUnavailable, match="not available locally"):
        await BgeM3Embedder().embed(["x"])


async def test_voyage_is_off_without_a_dpa() -> None:
    with pytest.raises(EmbedderUnavailable, match="DPA"):
        VoyageAdapter()
    stub = VoyageAdapter(dpa_signed=True)
    with pytest.raises(NotImplementedError):
        await stub.embed(["x"])


def test_embedder_setting() -> None:
    policy = real_registry().embeddings
    assert isinstance(embedder_from_settings(settings(), policy), FakeEmbedder)
    real = embedder_from_settings(settings(embedder="bge-m3"), policy)
    assert isinstance(real, BgeM3Embedder)
    assert real.version == f"{embeddings.BGE_M3_VERSION}-{policy.precision}"
    production = settings().model_copy(update={"app_env": "production"})  # the validator already refuses this
    with pytest.raises(ValueError, match="not allowed in production"):
        embedder_from_settings(production, policy)


def test_the_lock_carries_no_ml_stack() -> None:
    """sentence-transformers and torch stay out of uv.lock until the human approves bge-m3 (Docker has 4 GB)."""
    lock = (Path(embeddings.__file__).resolve().parents[3] / "uv.lock").read_text(encoding="utf-8")
    names = {line.split('"')[1] for line in lock.splitlines() if line.startswith("name = ")}
    heavy = {"torch", "triton", "sentence-transformers", "transformers", "scikit-learn", "safetensors"}
    assert not names & heavy
    assert not [name for name in names if name.startswith("nvidia-")]
