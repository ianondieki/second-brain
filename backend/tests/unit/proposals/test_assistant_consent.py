"""REQ-PROP-05, AC-SEC-6: the submission assistant's consent gate without a database.

``require_consent`` accepts only the owner's opt-in granted in this very login session; without it the LLM layer's own
guard still refuses the Tier-2 fields, with the fixed ``consent_required`` answer, and the fake provider sees no
request. With it, the owner's text is sanitised and nonce-framed, and the ledger keeps names and lengths only. The
API-level tests (Tier-1-only drafts, sign-out, audit) are in ``integration/proposals/test_assistant_consent_api.py``.
"""

from __future__ import annotations

import json
import re
from uuid import UUID

import pytest

from bridge.errors import ApiError
from bridge.llm.fakes import FakeLLMClient
from bridge.llm.guard import StaticConsents
from bridge.models.enums import ConsentPurpose
from bridge.proposals import assistant
from bridge.proposals.assistant import DraftText, SuggestionStatus
from tests.unit.proposals.assistant_fixtures import DRAFT, OWNER, SECRET, SESSION, answer, detail_of


def test_the_task_is_consent_covered_and_has_no_tools() -> None:
    from bridge.llm.registry import load
    from tests.unit.llm.helpers import settings

    spec = load(settings().llm_models_file).task(assistant.TASK)
    assert spec.purpose.consent is ConsentPurpose.TIER2_LLM_ASSISTANT
    assert not spec.allowed_tools  # docs/spec/09: explainers and writers have no tools


async def test_a_granted_session_sends_framed_sanitised_text_and_nothing_else() -> None:
    llm = FakeLLMClient([answer()], consents=StaticConsents([(OWNER, assistant.PURPOSE, SESSION)]))
    draft = DraftText(
        DRAFT.owned,
        tier1={"title": "Cold chain", "summary": "Alerts <b>now</b> [here](https://evil.example)"},
        tier2={"approach": SECRET},
    )
    got = await assistant.suggest(llm, draft, session_id=SESSION)
    assert got.status is SuggestionStatus.SUGGESTED
    [request] = llm.requests
    sent = "\n".join(block.text for message in request.messages for block in message.blocks)
    assert re.search(r'<submission nonce="[0-9a-f]{16}" field="confidential.approach" tier="tier2">', sent)
    assert "evil.example" not in sent  # the layer's sanitiser ran
    assert "<b>" not in sent
    assert SECRET in sent  # consent covers Tier 2 for this session
    assert not request.tools
    [entry] = llm.ledger.entries
    assert SECRET not in json.dumps(entry.inputs, default=str)  # the ledger keeps names and lengths only


async def test_without_the_sessions_consent_nothing_is_sent() -> None:
    """The layer's own guard refuses Tier 2 even if a caller forgot ``require_consent``; the answer is fixed."""
    other = UUID("01900000-0000-7000-8000-0000000000e2")
    for consents in (StaticConsents(), StaticConsents([(OWNER, assistant.PURPOSE, other)])):
        llm = FakeLLMClient([answer()], consents=consents)
        with pytest.raises(ApiError) as caught:
            await assistant.suggest(llm, DRAFT, session_id=SESSION)
        assert caught.value.status_code == 403
        assert detail_of(caught.value)["code"] == "consent_required"
        assert llm.requests == []


async def test_require_consent_is_per_session() -> None:
    held = StaticConsents([(OWNER, assistant.PURPOSE, SESSION)])
    await assistant.require_consent(held, OWNER, session_id=SESSION)
    with pytest.raises(ApiError) as caught:
        await assistant.require_consent(held, OWNER, session_id=UUID(int=7))
    assert detail_of(caught.value) == {
        "code": "consent_required",
        "message": assistant.CONSENT_REQUIRED,
    }
