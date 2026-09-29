"""REQ-LLM-01 P7 (D-37): only seeded demo data goes to a free provider.

The rule runs in ``LLMService`` after the Tier-2 consent guard and before sanitising, budgeting or sending. A Tier-2
field of a non-demo account is refused (``Tier2DemoOnly``: a ``blocked_tier2`` row, names and lengths only); a call
whose user is missing or not a demo account, or a field owned by one, is ``NotDemoData`` (no row: nothing was
attempted; the router answers with the labelled fake). The adapter never sees either.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from bridge.llm.client import LLMService
from bridge.llm.demo_data import DemoDataRule, StaticDemoAccounts
from bridge.llm.errors import ConsentRequired, LLMBlocked, NotDemoData, Tier2DemoOnly, Tier2NotAllowed
from bridge.llm.fakes import FakeAdapter
from bridge.llm.guard import StaticConsents
from bridge.llm.ledger import CallStatus
from bridge.llm.types import CallContext, InputField, Instruction, Message, Tier
from bridge.models.enums import ConsentPurpose
from tests.unit.llm.helpers import ORG, OTHER_OWNER, OWNER, SESSION, USER
from tests.unit.llm.rig import Rig, rig, screen
from tests.unit.llm.schemas import Verdict

TASK = "moderation_prescreen"
ASSISTANT = "submission_assistant"
OK = {"injection_suspected": False, "verdict": "clean", "reason": "fine"}
CANARY = "CANARY-D37-3f9a"


class CountingAccounts(StaticDemoAccounts):
    def __init__(self, ids: set[UUID]) -> None:
        super().__init__(ids)
        self.asked: list[UUID] = []

    async def is_demo(self, user_id: UUID) -> bool:
        self.asked.append(user_id)
        return await super().is_demo(user_id)


def tier2(owner: UUID, *, tier1_owner: UUID | None = None) -> list[Message]:
    return [
        Message.system("You suggest placements."),
        Message.user(
            Instruction("Suggest:"),
            InputField("teaser.summary", "Public teaser.", owner_id=tier1_owner),
            InputField("confidential.method", f"The method is {CANARY}.", tier=Tier.TIER2, owner_id=owner),
        ),
    ]


def demo_rig(demo: set[UUID], *, consents: StaticConsents | None = None) -> tuple[Rig, FakeAdapter]:
    adapter = FakeAdapter([OK])
    r = rig(adapter, consents=consents, data_rule=DemoDataRule(StaticDemoAccounts(demo)))
    return r, adapter


# ---------------------------------------------------------------------------------------------------- the rule


async def test_a_demo_users_call_passes() -> None:
    await DemoDataRule(StaticDemoAccounts({USER})).check_call(TASK, screen(), CallContext(user_id=USER, org_id=ORG))


@pytest.mark.parametrize(
    "ctx",
    [CallContext(user_id=OTHER_OWNER), CallContext(), CallContext(org_id=ORG)],
    ids=["non-demo-user", "platform-job", "organisation-job"],
)
async def test_a_call_without_a_demo_user_is_not_demo_data(ctx: CallContext) -> None:
    with pytest.raises(NotDemoData) as info:
        await DemoDataRule(StaticDemoAccounts({USER})).check_call(TASK, screen(), ctx)
    assert info.value.code == "llm_not_demo_data"
    assert isinstance(info.value, LLMBlocked)


async def test_a_field_owned_by_a_non_demo_account_is_not_demo_data() -> None:
    rule = DemoDataRule(StaticDemoAccounts({USER, OWNER}))
    with pytest.raises(NotDemoData):
        await rule.check_call(ASSISTANT, tier2(OWNER, tier1_owner=OTHER_OWNER), CallContext(user_id=USER))


@pytest.mark.parametrize("subject", [USER, OTHER_OWNER], ids=["demo-subject", "non-demo-subject"])
async def test_tier2_text_of_a_non_demo_account_is_refused_not_faked(subject: UUID) -> None:
    """D-37: refused even when the caller is a demo account, and before the non-demo caller is answered by the fake."""
    with pytest.raises(Tier2DemoOnly) as info:
        await DemoDataRule(StaticDemoAccounts({USER})).check_call(ASSISTANT, tier2(OWNER), CallContext(user_id=subject))
    assert isinstance(info.value, Tier2NotAllowed)
    assert info.value.code == "llm_tier2_demo_only"
    assert info.value.fields == ("confidential.method",)
    assert CANARY not in str(info.value)


async def test_each_account_is_looked_up_once_per_rule() -> None:
    accounts = CountingAccounts({USER, OWNER})
    rule = DemoDataRule(accounts)
    for _ in range(2):
        await rule.check_call(ASSISTANT, tier2(OWNER, tier1_owner=USER), CallContext(user_id=USER))
    assert sorted(accounts.asked) == sorted([OWNER, USER])


# ------------------------------------------------------------------------------------------- in LLMService


async def test_tier2_of_a_non_demo_account_is_a_blocked_row_and_never_sent() -> None:
    consents = StaticConsents([(OWNER, ConsentPurpose.TIER2_LLM_ASSISTANT, SESSION)])
    r, adapter = demo_rig({USER}, consents=consents)
    ctx = CallContext(user_id=OWNER, session_id=SESSION)
    with pytest.raises(Tier2DemoOnly):
        await r.service.complete(ASSISTANT, tier2(OWNER), Verdict, ctx=ctx)
    assert adapter.requests == []
    [row] = r.ledger.entries
    assert row.status is CallStatus.BLOCKED_TIER2
    assert CANARY not in repr(row.inputs)
    assert CANARY not in str(row.error)


async def test_a_non_demo_call_is_refused_unrecorded_before_anything_is_sent() -> None:
    r, adapter = demo_rig({USER})
    with pytest.raises(NotDemoData):
        await r.service.complete(TASK, screen(), Verdict, ctx=CallContext(user_id=OTHER_OWNER))
    assert adapter.requests == []
    assert r.ledger.entries == []


async def test_the_consent_guard_comes_first() -> None:
    r, adapter = demo_rig(set())
    with pytest.raises(ConsentRequired):
        await r.service.complete(ASSISTANT, tier2(OWNER), Verdict, ctx=CallContext(user_id=OWNER))
    assert [e.status for e in r.ledger.entries] == [CallStatus.BLOCKED_CONSENT]
    assert adapter.requests == []


async def test_a_demo_accounts_tier2_text_with_consent_is_sent() -> None:
    """D-37 allows seeded demo data, Tier 2 included, under the ordinary consent rule."""
    consents = StaticConsents([(OWNER, ConsentPurpose.TIER2_LLM_ASSISTANT, SESSION)])
    r, adapter = demo_rig({OWNER}, consents=consents)
    result = await r.service.complete(
        ASSISTANT, tier2(OWNER), Verdict, ctx=CallContext(user_id=OWNER, session_id=SESSION)
    )
    assert result.parsed.verdict == "clean"
    assert len(adapter.requests) == 1


async def test_without_a_rule_nothing_changes() -> None:
    """Anthropic keeps the T2.2 rules: the rule is set on free slot services only."""
    adapter = FakeAdapter([OK])
    service: LLMService = rig(adapter).service
    await service.complete(TASK, screen(), Verdict, ctx=CallContext(user_id=OTHER_OWNER))
    assert len(adapter.requests) == 1
