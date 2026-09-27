"""AC-SEC-6 (REQ-LLM-01, REQ-CON-01, REQ-PROP-05): for every registered LLM task fixture, without a live
purpose-specific consent (``tier2_llm_assistant`` / ``tier2_llm_moderation``), no Tier-2 field value ever reaches
the request sent to the transport, the ``llm_calls`` ledger inputs, the dead-letter queue, the human queue or the
logs. With the exact consent the value reaches the model (the positive control) and still never the ledger.

The task list comes from ``ai/models.yaml``, so a newly registered task is covered without editing this file.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from bridge.llm.budget import StaticCaps
from bridge.llm.cassettes import CassettePlayer
from bridge.llm.client import BatchItem
from bridge.llm.errors import ConsentRequired, LLMSchemaError, Tier2NotAllowed
from bridge.llm.fakes import FakeAdapter
from bridge.llm.guard import StaticConsents
from bridge.llm.ledger import CallStatus
from bridge.llm.registry import Purpose
from bridge.llm.types import CallContext, InputField, Message, Tier
from bridge.models.enums import ConsentPurpose
from tests.unit.llm.helpers import OWNER, real_registry
from tests.unit.llm.rig import Rig, registry_with, rig
from tests.unit.llm.schemas import Verdict, player

CANARY = "CANARY-T2-7f3a9c41"
TIER1_TEXT = "Public teaser: solar cold rooms for fish traders."
TASKS = sorted(real_registry().tasks)
CONSENT_TASKS = [t for t in TASKS if real_registry().task(t).purpose is not Purpose.TIER1_ONLY]
CTX = CallContext(user_id=OWNER, trace_id="ac-sec-6")


def fixture(task: str) -> list[Message]:
    """The task fixture: trusted instructions, one Tier-1 field and one Tier-2 field owned by OWNER."""
    return [
        Message.system(f"Fixture prompt for {task}."),
        Message.user(
            "Input:",
            InputField("teaser.summary", TIER1_TEXT),
            InputField("confidential.method", f"The method is {CANARY}.", tier=Tier.TIER2, owner_id=OWNER),
        ),
    ]


def everything_but(purpose: ConsentPurpose | None) -> StaticConsents:
    """Every consent the owner could hold except the one this task's purpose needs."""
    return StaticConsents({(OWNER, p) for p in ConsentPurpose if p is not purpose})


def leaks(r: Rig, sent: str, logs: str) -> list[str]:
    places = {
        "transport": sent,
        "ledger": repr(r.ledger.entries) + json.dumps([e.inputs for e in r.ledger.entries], default=str),
        "dead_letters": repr(r.dead_letters.letters),
        "human_queue": repr(r.human_queue.events),
        "logs": logs,
    }
    return [name for name, text in places.items() if CANARY in text]


def sent(tape: CassettePlayer) -> str:
    return b"".join(request.body for request in tape.requests).decode("utf-8")


def test_the_registry_has_both_kinds_of_task() -> None:
    assert CONSENT_TASKS, "no consent-covered task: the positive control would be empty"
    assert set(TASKS) - set(CONSENT_TASKS), "no Tier-1-only task"


@pytest.mark.parametrize("task", TASKS)
async def test_no_tier2_value_leaves_without_the_purpose_consent(task: str, capsys: pytest.CaptureFixture[str]) -> None:
    purpose = real_registry().task(task).purpose.consent
    tape = player()  # an empty cassette: any request would fail loudly
    r = rig(tape.adapter(), consents=everything_but(purpose))
    with pytest.raises((Tier2NotAllowed, ConsentRequired)):
        await r.service.complete(task, fixture(task), Verdict, ctx=CTX)
    assert tape.requests == []
    assert leaks(r, sent(tape), capsys.readouterr().out) == []
    [entry] = r.ledger.entries
    assert entry.status in {CallStatus.BLOCKED_TIER2, CallStatus.BLOCKED_CONSENT}
    assert entry.purpose == real_registry().task(task).purpose.value
    assert all("value" not in field for field in entry.inputs["fields"])  # refused before sanitising: no values


@pytest.mark.parametrize("task", TASKS)
async def test_no_tier2_value_leaves_a_batch_without_the_purpose_consent(task: str) -> None:
    purpose = real_registry().task(task).purpose.consent
    adapter = FakeAdapter()
    r = rig(adapter, reg=registry_with(**{task: {"batchable": True}}), consents=everything_but(purpose))
    with pytest.raises((Tier2NotAllowed, ConsentRequired)):
        await r.service.batch_submit(task, [BatchItem("item-1", fixture(task))], Verdict, ctx=CTX)
    assert adapter.requests == []
    assert CANARY not in repr(r.ledger.entries)


@pytest.mark.parametrize("task", TASKS)
async def test_tier1_fields_run_for_every_task(task: str) -> None:
    tape = player("messages_verdict_ok")
    r = rig(tape.adapter(), caps=StaticCaps())
    messages = [
        Message.system(f"Fixture prompt for {task}."),
        Message.user("Input:", InputField("teaser.summary", TIER1_TEXT)),
    ]
    result = await r.service.complete(task, messages, Verdict, ctx=CTX)
    assert result.parsed.verdict == "clean"
    assert r.ledger.entries[0].inputs["fields"][0]["value"] == TIER1_TEXT


@pytest.mark.parametrize("task", CONSENT_TASKS)
async def test_with_the_exact_consent_tier2_reaches_the_model_but_never_the_ledger(
    task: str, capsys: pytest.CaptureFixture[str]
) -> None:
    purpose = real_registry().task(task).purpose.consent
    assert purpose is not None
    tape = player("messages_verdict_ok")
    r = rig(tape.adapter(), consents=StaticConsents({(OWNER, purpose)}))
    await r.service.complete(task, fixture(task), Verdict, ctx=CTX)
    assert CANARY in sent(tape)  # positive control: the consented purpose does send it
    assert leaks(r, "", capsys.readouterr().out) == []
    tier2: dict[str, Any] = next(f for f in r.ledger.entries[0].inputs["fields"] if f["tier"] == "tier2")
    assert set(tier2) == {"name", "tier", "chars", "removed"}


@pytest.mark.parametrize("task", CONSENT_TASKS)
async def test_dead_letters_never_carry_tier2_even_with_consent(task: str, capsys: pytest.CaptureFixture[str]) -> None:
    purpose = real_registry().task(task).purpose.consent
    assert purpose is not None
    tape = player("messages_schema_invalid_twice")
    r = rig(tape.adapter(), consents=StaticConsents({(OWNER, purpose)}))
    with pytest.raises(LLMSchemaError):
        await r.service.complete(task, fixture(task), Verdict, ctx=CTX)
    assert r.dead_letters.letters
    assert leaks(r, "", capsys.readouterr().out) == []


@pytest.mark.parametrize("task", CONSENT_TASKS)
async def test_withdrawn_consent_blocks_again(task: str) -> None:
    purpose = real_registry().task(task).purpose.consent
    assert purpose is not None
    consents = StaticConsents({(OWNER, purpose)})
    consents.withdraw(OWNER, purpose)
    tape = player()
    r = rig(tape.adapter(), consents=consents)
    with pytest.raises(ConsentRequired):
        await r.service.complete(task, fixture(task), Verdict, ctx=CTX)
    assert tape.requests == []


@pytest.mark.parametrize("task", TASKS)
async def test_an_echoed_key_never_reaches_errors_ledger_dead_letters_or_feedback(task: str) -> None:
    """The model answers with a key made of (Tier-2 or injected) text: schema feedback keeps only error types and
    declared field names, so the text never reaches the exception, the ledger, the dead letter or the retry turn."""
    echo = json.dumps({"injection_suspected": False, "verdict": "clean", "reason": "r", CANARY: 1})
    adapter = FakeAdapter([echo, echo])
    r = rig(adapter)
    messages = [
        Message.system(f"Fixture prompt for {task}."),
        Message.user("Input:", InputField("teaser.summary", TIER1_TEXT)),
    ]
    with pytest.raises(LLMSchemaError) as info:
        await r.service.complete(task, messages, Verdict, ctx=CTX)
    feedback = adapter.requests[1].messages[-1].blocks[-1].text
    assert "(extra key): extra_forbidden" in feedback
    places = [str(info.value), feedback, *(e.error or "" for e in r.ledger.entries)]
    places += [letter.detail for letter in r.dead_letters.letters]
    assert r.dead_letters.letters
    assert not [text for text in places if CANARY in text]
