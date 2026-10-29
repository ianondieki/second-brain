"""REQ-AUTH-01 (docs/spec/06 6.1; THREAT_MODEL §5): a developer handle is random, never derived from personal data.
The account-level checks (signup, collisions) are in ``tests/integration/test_auth_handles.py``."""

from __future__ import annotations

import inspect
import random
from collections import Counter

import pytest

from bridge.auth import handles
from tests.name_tokens import leaked, name_tokens


def test_a_handle_is_dev_and_eight_crockford_base32_characters() -> None:
    drawn = [handles.new_handle() for _ in range(2000)]
    assert all(handles.PATTERN.fullmatch(h) for h in drawn), [h for h in drawn if not handles.PATTERN.fullmatch(h)]
    assert all(h == h.lower() and h.isascii() and len(h) == 12 for h in drawn)
    assert not set("ilou") & set("".join(drawn))  # Crockford: no letter to misread as 1, 0 or v


def test_handles_are_drawn_at_random() -> None:
    drawn = [handles.new_handle() for _ in range(2000)]
    assert len(set(drawn)) == len(drawn)
    counts = Counter("".join(h.removeprefix(handles.PREFIX) for h in drawn))
    assert set(counts) == set(handles.ALPHABET)  # 16,000 draws over 32 characters: every one turns up
    assert max(counts.values()) < 2 * min(counts.values())  # about 500 each: no character is favoured


def test_new_handle_is_given_nothing_to_derive_it_from() -> None:
    assert inspect.signature(handles.new_handle).parameters == {}


def test_the_default_source_is_the_operating_systems_csprng() -> None:
    assert isinstance(handles._rng, random.SystemRandom)


def test_a_seeded_source_replays_the_same_handles(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the integration test relies on to prove a signup's handle depends on the random source alone."""
    monkeypatch.setattr(handles, "_rng", random.Random(7))
    first = [handles.new_handle() for _ in range(3)]
    monkeypatch.setattr(handles, "_rng", random.Random(7))
    assert [handles.new_handle() for _ in range(3)] == first


def test_name_tokens_cover_words_ascii_folds_and_the_old_slug() -> None:
    assert name_tokens("Achieng Otieno", "achieng.otieno") == {"achieng", "otieno"}
    assert name_tokens("Wanjĩrũ Ngũgĩ") >= {"wanjĩrũ", "wanjiru", "wanj", "ngũgĩ", "ngugi"}
    assert name_tokens("Zoë O'Brien-Müller") >= {"zoë", "zoe", "brien", "müller", "muller", "ller"}
    assert name_tokens("Li Na") == set()  # pieces under three characters are left out
    assert leaked("achieng-otieno-2b2356", "Achieng Otieno") == ["achieng", "otieno"]  # the old handle
    assert leaked("dev-7k2m9x4q", "Achieng Otieno") == []
