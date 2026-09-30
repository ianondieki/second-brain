"""REQ-CON-01: every purpose has versioned text; the recorded hash is of the exact wording."""

from __future__ import annotations

import hashlib
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.config import get_settings
from bridge.llm.guard import session_consent_source
from bridge.models.enums import ConsentPurpose
from bridge.profiles.consents import SESSION_ONLY, SETTINGS_PURPOSES, load_texts, record_decisions


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


class _Recorder:
    """Stands in for the database session: keeps what ``record_decisions`` adds."""

    def __init__(self) -> None:
        self.rows: list[object] = []

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        return None


@pytest.mark.parametrize("source", ["signup", "settings", "demo_seed", "sessions:x", ""])
async def test_a_session_only_purpose_is_recorded_only_for_a_login_session(source: str) -> None:
    """Defence in depth behind the settings API's and signup's refusals (REQ-PROP-05, REQ-AUTH-01): a decision on a
    purpose decided per sign-in is recorded only with a ``session:`` source, whatever its value."""
    db = _Recorder()
    with pytest.raises(ValueError, match="per sign-in"):
        await record_decisions(
            cast(AsyncSession, db),
            get_settings(),
            user_id=uuid4(),
            decisions={ConsentPurpose.REMINDERS: True, ConsentPurpose.TIER2_LLM_ASSISTANT: False},
            source=source,
        )
    assert db.rows == []


async def test_session_sources_and_other_purposes_are_recorded() -> None:
    db = _Recorder()
    settings = get_settings()
    await record_decisions(
        cast(AsyncSession, db),
        settings,
        user_id=uuid4(),
        decisions={ConsentPurpose.TIER2_LLM_ASSISTANT: True},
        source=session_consent_source(uuid4()),
    )
    await record_decisions(
        cast(AsyncSession, db), settings, user_id=uuid4(), decisions={ConsentPurpose.REMINDERS: True}, source="signup"
    )
    assert len(db.rows) == 2
