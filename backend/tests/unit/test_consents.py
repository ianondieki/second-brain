"""REQ-CON-01: every purpose has versioned text; the recorded hash is of the exact wording."""

from __future__ import annotations

import hashlib

from bridge.config import get_settings
from bridge.models.enums import ConsentPurpose
from bridge.profiles.consents import SESSION_ONLY, SETTINGS_PURPOSES, load_texts


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


def test_the_assistant_opt_in_is_per_sign_in_and_says_so() -> None:
    """REQ-PROP-05 (D-39 item 6): the opt-in is decided per login session, never on the settings page, and its text
    says it ends at sign-out."""
    assert ConsentPurpose.TIER2_LLM_ASSISTANT in SESSION_ONLY
    assert ConsentPurpose.TIER2_LLM_ASSISTANT not in SETTINGS_PURPOSES
    assert set(SETTINGS_PURPOSES) | SESSION_ONLY == set(ConsentPurpose)
    shown = load_texts(get_settings().consents_file)[ConsentPurpose.TIER2_LLM_ASSISTANT]
    assert "During this sign-in only" in shown.text
    assert "sign out" in shown.text
    assert "my proposals" in shown.text  # per session, not per proposal (ADR-005 decision 4)
