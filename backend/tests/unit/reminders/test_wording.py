"""REQ-REM-01 (docs/spec/09: the progress reporter's 100% factual consistency; D-37): the LLM writes no text in the
developer's EM7. It chooses among code-rendered variants: an ``opening`` from a fixed list of neutral phrases, the
``order`` of the code-rendered items (every item that needs the developer listed) and a ``next_step_variant`` from a
fixed list of phrasings around the code-rendered next step. Code validates the choice and renders every word; an
invalid choice, a demo fallback, a typed LLM error or an injection flag answers with the fixed text (orchestrator
ruling after the P6 re-review: free wording returns with the REQ-EVAL-01 progress-reporter eval set).

The P6 reviewers' probes (earlier free-wording checkers let them through) can never reach the rendered email: no
schema field takes free text, a probe is no enum value and no item id, and every valid choice renders only code
sentences and the fixed phrases. No network: fakes and respx only (AC-SEC-5).
"""

from __future__ import annotations

import itertools
import json
from typing import Any

import httpx
import pytest
import respx
from pydantic import ValidationError
from structlog.testing import capture_logs

from bridge.llm.demo_fallback import fallback_output
from bridge.llm.errors import LLMConfigError, LLMKillSwitch, LLMUnavailable
from bridge.llm.fakes import FakeLLMClient
from bridge.llm.prepare import check_schema
from bridge.llm.types import CallContext
from bridge.reminders.nudge import AI_LABEL, DeveloperFacts, Nudge, compose_nudge, fallback_wording, render_nudge
from bridge.reminders.wording import (
    NEXT_STEP_VARIANTS,
    OPENINGS,
    SYSTEM,
    TASK,
    NextStepVariant,
    NudgeWording,
    Opening,
    check_wording,
    choose,
    messages,
    word_nudge,
)
from tests.unit.llm.helpers import USER
from tests.unit.llm.routing_rig import routed, url
from tests.unit.reminders.builders import BASE_URL, DEV, MONDAY, NO_HOLIDAYS, ORG, S, days, engagement, milestone

CTX = CallContext(user_id=USER, trace_id="em7-test")
STEP = "Sign the mutual NDA for “Till reconciler”: it was due 3 Oct 2026."
GOOD: dict[str, Any] = {
    "injection_suspected": False,
    "opening": "your_day",
    "order": ["n2", "n1", "h2"],
    "next_step_variant": "start_with",
}
PROBES = (
    # P6 review, MAJOR 1 (round 1)
    "Sacco is waiting on your signature.",
    "Two things need you; Safaricom has paid you already.",
    "Twenty things need you today.",
    "Your third milestone needs you.",
    "You are owed 2026 shillings.",
    "Two things need you since 2 Oct.",
    "Submit it within a week or the agreement is cancelled.",
    # P6 re-review (round 2)
    "The other party did sign the mutual NDA.",
    "You did sign the mutual NDA.",
    "The other party did review your work.",
    "The other party will sign the mutual NDA today.",
    "Will needs you today.",
    "Please sign the mutual NDA for “Till reconciler” now: it was due 3 Oct 2026, and the other party did sign it.",
)


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


def test_the_schema_takes_no_free_text_and_its_placeholder_is_safe() -> None:
    schema = check_schema(NudgeWording)
    assert set(schema["properties"]) == {"injection_suspected", "opening", "order", "next_step_variant"}
    assert set(schema["$defs"]["Opening"]["enum"]) == {o.value for o in Opening} == set(OPENINGS)
    assert (
        set(schema["$defs"]["NextStepVariant"]["enum"]) == {v.value for v in NextStepVariant} == set(NEXT_STEP_VARIANTS)
    )
    assert schema["properties"]["order"]["items"] == {"type": "string"}
    placeholder = fallback_output(NudgeWording)
    assert placeholder.injection_suspected is True
    assert check_wording(placeholder, nudge()) == "injection_suspected"


def test_the_model_sees_item_ids_with_code_briefs_and_no_organisation_text() -> None:
    subject = nudge()
    assert subject.fact_lines == (
        "Today is 5 Oct 2026.",
        "n1: milestone 1 of “Solar cold rooms”, due 6 Oct 2026",
        "n2: “Till reconciler”: sign the mutual NDA (due 3 Oct 2026)",
        "w1: “Till reconciler”: waiting for the organisation to sign the mutual NDA (due 3 Oct 2026)",
        "h1: “Solar cold rooms”: at risk",
        "h2: “Till reconciler”: at risk",
        f"Suggested next step: {STEP}",
    )
    system, user = messages(subject)
    (field,) = user.fields
    assert (field.name, field.owner_id, field.public) == ("reminder.facts", USER, False)
    for private in ("Secret Org", "Sacco C", "Confidential pilot"):
        assert private not in field.value
    prompt = " ".join(part.text for part in system.parts)  # type: ignore[union-attr]
    assert all(o.value in prompt for o in Opening)
    assert all(v.value in prompt for v in NextStepVariant)
    assert prompt == SYSTEM


async def test_a_valid_choice_is_rendered_by_code_and_labelled() -> None:
    client = FakeLLMClient([GOOD])
    wording = await word_nudge(client, nudge(), ctx=CTX)
    assert (wording.source, wording.reason, wording.order) == ("model", None, ("n2", "n1", "h2"))
    assert wording.headline == "Here is your day on Wazo. 2 things need you today, and 2 engagements need attention."
    assert wording.next_step == f"Start with this: {STEP}"
    (entry,) = client.ledger.entries
    assert (entry.task, entry.user_id) == (TASK, USER)
    message = render_nudge(nudge(), wording, to="dev@example.com", base_url=BASE_URL)
    needs = message.text.split("NEEDS YOU\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert needs == [
        "- “Till reconciler” with Sacco C: sign the mutual NDA (due 3 Oct 2026).",
        "- Milestone 1 “Confidential pilot” of “Solar cold rooms”: submit it for review by 6 Oct 2026.",
    ]
    health = message.text.split("HEALTH\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert [line.split(" with ")[0] for line in health] == ["- “Till reconciler”", "- “Solar cold rooms”"]
    assert AI_LABEL in message.text


def test_the_fixed_text_keeps_the_code_order() -> None:
    subject = nudge()
    fixed = fallback_wording(subject, "test")
    assert (fixed.headline, fixed.next_step, fixed.order) == (subject.fallback_headline, STEP, ())
    message = render_nudge(subject, fixed, to="dev@example.com", base_url=BASE_URL)
    assert message.text.index("Milestone 1") < message.text.index("sign the mutual NDA (due")
    assert AI_LABEL not in message.text


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"injection_suspected": True}, "injection_suspected"),
        ({"order": ["n2", "h2"]}, "rejected:missing_item"),  # n1 needs the developer: it must be listed
        ({"order": ["n2", "n1", "x9"]}, "rejected:unknown_item"),
        ({"order": ["n2", "n1", "n1"]}, "rejected:duplicate_item"),
    ],
)
async def test_an_invalid_choice_answers_with_the_fixed_text(changes: dict[str, Any], reason: str) -> None:
    subject = nudge()
    wording = await word_nudge(FakeLLMClient([reply(**changes)]), subject, ctx=CTX)
    assert (wording.source, wording.reason, wording.ai_drafted) == ("fallback", reason, False)
    assert (wording.headline, wording.next_step, wording.order) == (subject.fallback_headline, subject.next_step, ())


async def test_an_answer_outside_the_schema_answers_with_the_fixed_text() -> None:
    bad = reply(opening="warm_greeting")
    wording = await word_nudge(FakeLLMClient([bad, bad]), nudge(), ctx=CTX)  # one retry with the error, then refused
    assert (wording.source, wording.reason) == ("fallback", "llm_error:llm_schema")


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


async def test_the_fake_provider_is_a_demo_fallback_never_used_as_a_choice() -> None:
    rig = routed(provider="fake")
    with capture_logs() as logs:
        wording = await word_nudge(rig.client, nudge(), ctx=CTX)
    assert (wording.source, wording.reason) == ("fallback", "demo_fallback:fake_provider")
    assert [e for e in logs if e["event"] == "reminders.nudge_worded"] == [
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
    usage = {"prompt_tokens": 90, "completion_tokens": 30}
    return httpx.Response(200, json={"id": "c", "choices": [choice], "usage": usage})


async def test_a_non_demo_account_never_reaches_a_free_provider() -> None:
    rig = routed(provider="free", demo=())
    with respx.mock(assert_all_called=False) as router:
        route = router.post(url(1)).mock(return_value=chat(GOOD))
        wording = await word_nudge(rig.client, nudge(), ctx=CTX)
    assert not route.called
    assert (wording.source, wording.reason) == ("fallback", "demo_fallback:not_demo_data")
    assert rig.ledger.entries == []


async def test_a_demo_accounts_choice_comes_from_the_free_slot_which_sees_no_organisation_text() -> None:
    rig = routed(provider="free", demo=(USER,))
    with respx.mock(assert_all_called=True) as router:
        route = router.post(url(1)).mock(return_value=chat(GOOD))
        wording = await word_nudge(rig.client, nudge(), ctx=CTX)
    sent = route.calls[0].request.content.decode()
    assert "Till reconciler" in sent
    for private in ("Secret Org", "Sacco C", "Confidential pilot"):
        assert private not in sent
    assert (wording.source, wording.order) == ("model", ("n2", "n1", "h2"))


# -------------------------------------------------------------------------------------------- the reviewers' probes


@pytest.mark.parametrize("probe", PROBES)
def test_a_probe_is_no_valid_choice(probe: str) -> None:
    for field in ("opening", "next_step_variant"):
        with pytest.raises(ValidationError):
            NudgeWording.model_validate(reply(**{field: probe}))
    for free_text in ("headline", "next_step", "text"):  # there is no field for free text
        with pytest.raises(ValidationError):
            NudgeWording.model_validate(GOOD | {free_text: probe})
    as_item = NudgeWording.model_validate(reply(order=[*GOOD["order"], probe]))
    assert check_wording(as_item, nudge()) == "unknown_item"


@pytest.mark.parametrize("probe", PROBES)
@pytest.mark.parametrize("field", ["opening", "next_step_variant", "order", "headline"])
async def test_a_model_answering_a_probe_leaves_no_trace_in_the_email(probe: str, field: str) -> None:
    answer = reply(order=[*GOOD["order"], probe]) if field == "order" else reply(**{field: probe})
    subject = nudge()
    wording = await word_nudge(FakeLLMClient([answer, answer]), subject, ctx=CTX)
    assert wording.source == "fallback"
    message = render_nudge(subject, wording, to="dev@example.com", base_url=BASE_URL)
    assert probe not in message.text
    assert probe not in (message.html or "")


def _shared(text: str) -> list[str]:
    """The lines every rendering holds alike: the facts' sections (in any order), the call to action, the footer."""
    lines = text.splitlines()
    step = lines.index("NEXT STEP") + 1
    return sorted(line for i, line in enumerate(lines) if i not in (0, step) and line != AI_LABEL)


def test_every_valid_choice_renders_only_code_sentences_and_fixed_phrases() -> None:
    subject = nudge()
    fixed = render_nudge(subject, fallback_wording(subject, "test"), to="dev@example.com", base_url=BASE_URL).text
    orders = ([*p, "w1", "h1", "h2"] for p in itertools.permutations(["n1", "n2"]))
    for opening, variant, order in itertools.product(Opening, NextStepVariant, orders):
        choice = NudgeWording(injection_suspected=False, opening=opening, order=order, next_step_variant=variant)
        assert check_wording(choice, subject) is None
        text = render_nudge(subject, choose(subject, choice), to="dev@example.com", base_url=BASE_URL).text
        lines = text.splitlines()
        assert lines[0] == f"{OPENINGS[opening]} {subject.fallback_headline}"
        assert lines[1] == AI_LABEL
        assert lines[lines.index("NEXT STEP") + 1] == NEXT_STEP_VARIANTS[variant].format(step=subject.next_step)
        assert _shared(text) == _shared(fixed)  # the same code sentences, only reordered
        for probe in PROBES:
            assert probe not in text
