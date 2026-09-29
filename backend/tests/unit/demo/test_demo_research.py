"""P11 demo seed (REQ-RES-01): the fixed answers behind the seeded research cards pass every check in code on the
saved excerpts, name no organisation (D-45), and ``SeededExampleClient`` answers only the research call, flagged as
no provider's model and costing nothing."""

from __future__ import annotations

from datetime import date

import pytest

from bridge.llm.errors import LLMConfigError
from bridge.llm.types import CallContext
from bridge.problems.research import checks, synthesis
from bridge.problems.research.policy import get_research_policy
from bridge.problems.research.sources import load_catalogue
from bridge.seed.demo.data import STAFF_ADMIN, all_accounts
from bridge.seed.demo.research import SEEDED_ANSWERS, SEEDED_EXAMPLE_MODEL, SeededExampleClient, seeded_answer

AS_OF = date(2026, 9, 29)


@pytest.mark.parametrize("niche", sorted(SEEDED_ANSWERS))
def test_every_seeded_answer_passes_the_checks(niche: str) -> None:
    catalogue, policy = load_catalogue(), get_research_policy()
    sent = {e.id: e for e in catalogue.usable(niche, "KE", AS_OF, policy)}
    [draft] = seeded_answer(niche).problems
    verdict = checks.check_draft(draft.draft(), sent, catalogue.allowlists["KE"], policy, AS_OF)
    assert isinstance(verdict, checks.Accepted), verdict
    assert verdict.agreement == 1
    assert verdict.text.named_orgs == ()
    assert verdict.confidence >= policy.discard_below


def test_one_seeded_card_per_saved_niche() -> None:
    assert set(SEEDED_ANSWERS) == set(load_catalogue().niches("KE"))


async def test_the_seeded_client_answers_the_research_call_only() -> None:
    client = SeededExampleClient(seeded_answer("health"))
    ctx = CallContext(trace_id="research:seed")
    result = await client.complete(synthesis.TASK, [], synthesis.ResearchSynthesis, ctx=ctx)
    assert (result.model, result.cost_usd, result.demo_fallback, result.attempts) == (SEEDED_EXAMPLE_MODEL, 0, False, 0)
    with pytest.raises(LLMConfigError):
        await client.complete("reminder_nudge", [], synthesis.ResearchSynthesis, ctx=ctx)
    with pytest.raises(LLMConfigError):
        await client.complete(synthesis.TASK, [], synthesis.ResearchSynthesis, ctx=ctx, tools=[{"type": "x_1"}])


def test_the_staff_admin_is_a_listed_demo_login() -> None:
    assert (STAFF_ADMIN.email, STAFF_ADMIN.display_name, "platform staff: admin") in all_accounts()
    assert STAFF_ADMIN.email.endswith(".example")
