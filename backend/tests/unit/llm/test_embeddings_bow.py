"""REQ-EMB-01: the fake embedder's bag-of-words vectors. Texts that share words point the same way and texts with no
shared word are near-orthogonal, so the demo's profile/problem fit and the ranker's semantic factor mean something
without a real model. Pinned texts still win."""

from __future__ import annotations

import math
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bridge.llm import embeddings
from bridge.llm.embeddings import (
    EMBED_DIM,
    STOP_WORDS,
    TOKEN_CACHE_SIZE,
    FakeEmbedder,
    bag_of_words_vector,
    cosine,
    hashed_vector,
    tokens,
    vector_with_similarity,
)

PROFILE = "Python backend developer building M-Pesa payment integrations and SMS alerts for SACCOs in Nairobi"
PROBLEM = "SACCOs in Nairobi need a Python backend for M-Pesa payment integrations and SMS alerts to members"
DISJOINT = "Greenhouse irrigation sensors measuring soil moisture across Kericho tea estates"


def norm(vector: list[float]) -> float:
    return math.sqrt(math.fsum(x * x for x in vector))


def test_the_vector_is_deterministic() -> None:
    assert bag_of_words_vector(PROFILE) == bag_of_words_vector(PROFILE)
    assert FakeEmbedder().vector_for(PROFILE) == FakeEmbedder().vector_for(PROFILE) == bag_of_words_vector(PROFILE)


def test_texts_sharing_most_words_are_close() -> None:
    assert cosine(bag_of_words_vector(PROFILE), bag_of_words_vector(PROBLEM)) > 0.5
    one_word_changed = ("Solar cold rooms for dairy farmers in Nakuru", "Solar cold rooms for dairy farmers in Kisumu")
    assert cosine(*map(bag_of_words_vector, one_word_changed)) > 0.5


def test_texts_with_no_shared_word_are_near_orthogonal() -> None:
    assert not set(tokens(PROFILE)) & set(tokens(DISJOINT))
    assert abs(cosine(bag_of_words_vector(PROFILE), bag_of_words_vector(DISJOINT))) < 0.15


def test_word_order_and_case_do_not_matter() -> None:
    shuffled = " ".join(reversed(PROFILE.upper().split()))
    assert cosine(bag_of_words_vector(PROFILE), bag_of_words_vector(shuffled)) == pytest.approx(1.0, abs=1e-12)


def test_repeated_words_weigh_more_but_sub_linearly() -> None:
    base = bag_of_words_vector("solar kiosks")
    once = cosine(base, bag_of_words_vector("solar kiosks fish"))
    thrice = cosine(base, bag_of_words_vector("solar kiosks fish fish fish"))
    assert thrice < once  # the repeated word pulls the vector away from the shared ones
    assert thrice > 0.5  # damped by 1 + ln(tf): a raw count of 3 would give about 0.43


def test_the_stop_list_and_short_tokens_are_dropped() -> None:
    assert {"the", "na", "and", "kwa", "katika"} <= STOP_WORDS
    assert tokens("The farmers na wavuvi, kwa the AI of 3 co-ops") == ["farmers", "wavuvi", "ops"]
    assert bag_of_words_vector("the solar kiosks na") == bag_of_words_vector("solar kiosks")


@pytest.mark.parametrize("text", ["", "   ", "the na of", "a b c", "?!"])
def test_a_text_with_no_tokens_falls_back_to_the_text_hash(text: str) -> None:
    assert tokens(text) == []
    assert bag_of_words_vector(text) == hashed_vector(text)
    assert FakeEmbedder().vector_for(text) == hashed_vector(text)


async def test_pins_still_win_over_the_bag_of_words() -> None:
    pinned = vector_with_similarity(hashed_vector("anchor"), 0.2)
    fake = FakeEmbedder({PROFILE: pinned})
    [mine, other] = await fake.embed([PROFILE, PROBLEM])
    assert mine == pytest.approx(pinned)
    assert other == bag_of_words_vector(PROBLEM)


@settings(max_examples=60, deadline=None)
@given(text=st.text(max_size=200), dim=st.sampled_from([16, 128, EMBED_DIM]))
def test_the_result_is_always_a_unit_vector_of_dim(text: str, dim: int) -> None:
    vector = bag_of_words_vector(text, dim)
    assert len(vector) == dim
    assert all(math.isfinite(x) for x in vector)
    assert abs(norm(vector) - 1) < 1e-9


def test_the_token_cache_is_bounded_and_compact() -> None:
    """Review round 1: at most ``TOKEN_CACHE_SIZE`` packed entries of about 8 KB each (about 8 MB when full)."""
    embeddings._token_vector.cache_clear()
    for start in range(0, TOKEN_CACHE_SIZE + 300, 100):
        bag_of_words_vector(" ".join(f"word{n}" for n in range(start, start + 100)))
    info = embeddings._token_vector.cache_info()
    assert info.maxsize == TOKEN_CACHE_SIZE == 1024
    assert info.currsize == TOKEN_CACHE_SIZE
    entry = embeddings._token_vector("word0", EMBED_DIM)
    assert isinstance(entry, bytes)
    assert sys.getsizeof(entry) < 8 * EMBED_DIM + 100
    assert sys.getsizeof(entry) * TOKEN_CACHE_SIZE < 9 * 2**20


def test_a_golden_vector_with_a_repeated_word() -> None:
    """Portability: the 1 + ln(tf) weights, the summation order and the fsum norm give these components on every
    platform (values pinned when the bag of words was introduced)."""
    vector = bag_of_words_vector("solar solar solar kiosks for fish traders fish")
    golden = {
        0: -0.010480192717945,
        1: -0.036845460571182,
        2: 0.042421242186400,
        511: 0.053403529723440,
        1023: -0.035006110294279,
    }
    for index, value in golden.items():
        assert vector[index] == pytest.approx(value, abs=1e-12), index  # 12 decimal places
