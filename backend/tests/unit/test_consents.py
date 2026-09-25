"""REQ-CON-01: every purpose has versioned text; the recorded hash is of the exact wording."""

from __future__ import annotations

import hashlib

from bridge.config import get_settings
from bridge.models.enums import ConsentPurpose
from bridge.profiles.consents import load_texts


def test_every_purpose_has_text_and_a_version() -> None:
    texts = load_texts(get_settings().consents_file)
    assert set(texts) == set(ConsentPurpose)
    for purpose, shown in texts.items():
        assert shown.version
        assert shown.text.strip()
        assert shown.sha256 == hashlib.sha256(shown.text.encode("utf-8")).digest()
        assert shown.purpose == purpose


def test_the_tier2_llm_purposes_are_separate() -> None:
    texts = load_texts(get_settings().consents_file)
    assert texts[ConsentPurpose.TIER2_LLM_ASSISTANT].text != texts[ConsentPurpose.TIER2_LLM_MODERATION].text


def test_texts_carry_no_review_markers() -> None:
    """Texts are shown verbatim and hashed as shown, so review markers live in YAML comments only."""
    for shown in load_texts(get_settings().consents_file).values():
        assert "[[" not in shown.text, shown.purpose
