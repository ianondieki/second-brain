"""REQ-REM-01 (docs/spec/09; D-37): the LLM words two lines of the developer's EM7 from code-computed facts only.

The model's words are used only when they reword the facts; the fixed fallback text (marked, with its reason) answers
a demo fallback, a typed LLM error, an injection flag or any reply that adds a fact. Local runs route through
``RoutedLLMClient``: a non-demo account's facts never reach a free provider (respx sees no request), a seeded demo
account's do. No network: fakes and respx only (AC-SEC-5).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from bridge.llm.demo_fallback import fallback_output
from bridge.llm.errors import LLMConfigError, LLMKillSwitch, LLMUnavailable
from bridge.llm.fakes import FakeLLMClient
from bridge.llm.prepare import check_schema
from bridge.llm.types import CallContext
from bridge.reminders.nudge import DeveloperFacts, Nudge, compose_nudge
from bridge.reminders.wording import TASK, NudgeWording, check_wording, messages, word_nudge
from tests.unit.llm.helpers import USER
from tests.unit.llm.routing_rig import routed, url
from tests.unit.reminders.builders import DEV, MONDAY, NO_HOLIDAYS, ORG, S, days, engagement, milestone

CTX = CallContext(user_id=USER, trace_id="em7-test")
GOOD = {
    "injection_suspected": False,
    "headline": "Two things need you today, and two engagements are at risk.",
    "next_step": "Please sign the mutual NDA for “Till reconciler” now: it was due 3 Oct 2026.",
}


def nudge() -> Nudge:
    building = engagement(org_name="Secret Org Ltd", milestones=(milestone(days(1), deliverable="Confidential pilot"),))
    nda = engagement(
        S.NDA_PENDING,
        title="Till reconciler",
        org_name="Sacco C",
        awaiting=frozenset({DEV, ORG}),
        stage_deadline_on=days(-2),
    )
    return compose_nudge(DeveloperFacts(USER, MONDAY, (building, nda)), NO_HOLIDAYS)


def reply(**changes: Any) -> dict[str, Any]:
    return GOOD | changes


def test_the_output_schema_is_strict_and_its_placeholder_is_safe() -> None:
    check_schema(NudgeWording)
    placeholder = fallback_output(NudgeWording)
    assert placeholder.injection_suspected is True
    assert check_wording(placeholder, nudge()) == "injection_suspected"


def test_the_facts_go_as_one_field_owned_by_the_developer_without_organisation_text() -> None:
    system, user = messages(nudge())
    assert system.role == "system"
    (field,) = user.fields
    assert (field.name, field.owner_id, field.public) == ("reminder.facts", USER, False)
    assert "Secret Org" not in field.value
    assert "Confidential pilot" not in field.value
    assert "Suggested next step: Sign the mutual NDA for “Till reconciler”: it was due 3 Oct 2026." in field.value


async def test_model_wording_that_only_rewords_the_facts_is_used() -> None:
    client = FakeLLMClient([GOOD])
    wording = await word_nudge(client, nudge(), ctx=CTX)
    assert (wording.headline, wording.next_step, wording.source, wording.reason) == (
        GOOD["headline"],
        GOOD["next_step"],
        "model",
        None,
    )
    assert wording.ai_drafted
    (entry,) = client.ledger.entries
    assert (entry.task, entry.user_id) == (TASK, USER)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"injection_suspected": True}, "injection_suspected"),
        ({"headline": "Four things need you today."}, "rejected:invented_number"),
        ({"headline": "17 things need you today."}, "rejected:invented_number"),
        ({"headline": "Your milestone is due in November."}, "rejected:invented_date"),
        ({"headline": "Sign it by Friday."}, "rejected:invented_date"),
        ({"headline": "Do it tomorrow."}, "rejected:invented_date"),
        ({"headline": "You are 80% done."}, "rejected:headline_symbol"),
        ({"headline": "The engagement is off track."}, "rejected:invented_status"),
        ({"headline": "Sacco C and Safaricom are waiting on you."}, "rejected:invented_word"),
        ({"headline": "See https://bridge.example for details."}, "rejected:headline_link_or_contact"),
        ({"headline": "Mail jane@example.com today."}, "rejected:headline_link_or_contact"),
        ({"headline": "**Two** things need you."}, "rejected:headline_symbol"),
        ({"headline": "Call 0712 345 678 today."}, "rejected:headline_link_or_contact"),
        ({"headline": "Two things\nneed you."}, "rejected:headline_not_one_line"),
        ({"headline": "x" * 161}, "rejected:headline_length"),
        ({"headline": "  "}, "rejected:headline_length"),
        ({"next_step": "Sign the mutual NDA for “Till reconciler” now."}, "rejected:next_step_changed"),
        ({"next_step": "y" * 241}, "rejected:next_step_length"),
    ],
)
async def test_a_reply_that_adds_a_fact_answers_with_the_fixed_text(changes: dict[str, Any], reason: str) -> None:
    subject = nudge()
    wording = await word_nudge(FakeLLMClient([reply(**changes)]), subject, ctx=CTX)
    assert (wording.source, wording.reason, wording.ai_drafted) == ("fallback", reason, False)
    assert (wording.headline, wording.next_step) == (subject.fallback_headline, subject.next_step)


async def test_no_client_answers_with_the_fixed_text() -> None:
    wording = await word_nudge(None, nudge(), ctx=CTX)
    assert (wording.source, wording.reason) == ("fallback", "not_eligible")


class Raising:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def complete(self, *args: object, **kwargs: object) -> Any:
        raise self.error


@pytest.mark.parametrize(
    ("error", "reason"),
    [(LLMUnavailable("no key"), "llm_error:llm_unavailable"), (LLMKillSwitch(), "llm_error:llm_kill_switch")],
)
async def test_a_typed_llm_error_answers_with_the_fixed_text(error: Exception, reason: str) -> None:
    wording = await word_nudge(Raising(error), nudge(), ctx=CTX)  # type: ignore[arg-type]
    assert (wording.source, wording.reason) == ("fallback", reason)


async def test_a_callers_mistake_is_a_bug_and_propagates() -> None:
    with pytest.raises(LLMConfigError):
        await word_nudge(Raising(LLMConfigError("bad task")), nudge(), ctx=CTX)  # type: ignore[arg-type]


async def test_the_fake_provider_is_a_demo_fallback_never_used_as_wording() -> None:
    rig = routed(provider="fake")
    with capture_logs() as logs:
        wording = await word_nudge(rig.client, nudge(), ctx=CTX)
    assert (wording.source, wording.reason) == ("fallback", "demo_fallback:fake_provider")
    worded = [entry for entry in logs if entry["event"] == "reminders.nudge_worded"]
    assert worded == [
        {
            "event": "reminders.nudge_worded",
            "log_level": "info",
            "source": "fallback",
            "reason": "demo_fallback:fake_provider",
            "trace_id": "em7-test",
        }
    ]


def chat(body: dict[str, Any]) -> httpx.Response:
    choice = {"index": 0, "message": {"role": "assistant", "content": json.dumps(body)}, "finish_reason": "stop"}
    return httpx.Response(
        200, json={"id": "c", "choices": [choice], "usage": {"prompt_tokens": 90, "completion_tokens": 30}}
    )


async def test_a_non_demo_account_never_reaches_a_free_provider() -> None:
    rig = routed(provider="free", demo=())
    with respx.mock(assert_all_called=False) as router:
        route = router.post(url(1)).mock(return_value=chat(GOOD))
        wording = await word_nudge(rig.client, nudge(), ctx=CTX)
    assert not route.called
    assert (wording.source, wording.reason) == ("fallback", "demo_fallback:not_demo_data")
    assert rig.ledger.entries == []


async def test_a_demo_account_is_worded_by_the_free_slot_from_its_facts_only() -> None:
    rig = routed(provider="free", demo=(USER,))
    with respx.mock(assert_all_called=True) as router:
        route = router.post(url(1)).mock(return_value=chat(GOOD))
        wording = await word_nudge(rig.client, nudge(), ctx=CTX)
    assert route.call_count == 1
    sent = route.calls[0].request.content.decode()
    assert "Till reconciler" in sent
    assert "Secret Org" not in sent
    assert "Confidential pilot" not in sent
    assert (wording.source, wording.headline) == ("model", GOOD["headline"])


async def test_a_free_slots_invented_fact_still_answers_with_the_fixed_text() -> None:
    rig = routed(provider="free", demo=(USER,))
    with respx.mock(assert_all_called=True) as router:
        router.post(url(1)).mock(return_value=chat(reply(headline="Safaricom paid you KES 50,000.")))
        wording = await word_nudge(rig.client, nudge(), ctx=CTX)
    assert (wording.source, wording.reason) == ("fallback", "rejected:invented_number")
