"""REQ-FND-04 (P28 track PD, AT-PD-5, unit half): the public demo's content scope. With
``PUBLIC_DEMO_CONTENT=fictional`` the seed skips the provisional directory of real organisations and every seeded
research card that cites an excerpt whose ``source_type`` is not ``official`` (all of them today); ``full``, and the
mode off, change nothing.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from bridge import public_demo
from bridge.config import Settings, get_settings
from bridge.problems.research.sources import Catalogue, load_catalogue
from bridge.seed.demo.research import SEEDED_ANSWERS, niches_to_seed, seeded_niches
from bridge.seed.directory import DirectorySeedRefused, directory_refusal, ensure_loadable


def public(**update: Any) -> Settings:
    return get_settings().model_copy(update={"public_demo": True, **update})


def test_fictional_only_is_the_public_demo_with_fictional_content() -> None:
    assert public_demo.fictional_only(public())
    assert not public_demo.fictional_only(public(public_demo_content="full"))
    assert not public_demo.fictional_only(get_settings())
    assert not public_demo.fictional_only(get_settings().model_copy(update={"public_demo_content": "fictional"}))


def test_the_fictional_public_demo_skips_the_provisional_directory() -> None:
    reason = directory_refusal(public())
    assert reason is not None
    assert reason.startswith("PUBLIC_DEMO=true with PUBLIC_DEMO_CONTENT=fictional")
    with pytest.raises(DirectorySeedRefused, match="fictional fixture organisations"):
        ensure_loadable(public())
    assert directory_refusal(public(public_demo_content="full")) is None
    assert directory_refusal(get_settings()) is None


def test_the_fictional_public_demo_leaves_out_every_card_citing_a_news_excerpt() -> None:
    catalogue = load_catalogue()
    for niche in seeded_niches():  # today each seeded card cites at least one non-official excerpt
        cited = [catalogue.get(i) for i, _ in SEEDED_ANSWERS[niche]["citations"]]
        assert any(e is not None and e.source_type != "official" for e in cited), niche
    assert niches_to_seed(public(), catalogue) == ()
    assert niches_to_seed(public(public_demo_content="full"), catalogue) == seeded_niches()
    assert niches_to_seed(get_settings(), catalogue) == seeded_niches()


def test_a_card_citing_official_excerpts_only_is_kept() -> None:
    catalogue = load_catalogue()
    official = Catalogue(tuple(replace(e, source_type="official") for e in catalogue.excerpts), catalogue.allowlists)
    assert niches_to_seed(public(), official) == seeded_niches()
    one_news = Catalogue(
        tuple(replace(e, source_type="news") if e.id == "ke-sac-004" else e for e in official.excerpts),
        catalogue.allowlists,
    )
    assert "microfinance-saccos" not in niches_to_seed(public(), one_news)
    assert len(niches_to_seed(public(), one_news)) == len(seeded_niches()) - 1
