"""REQ-LLM-01 against PostgreSQL: AC-SEC-6 in the stored ledger, and the pre-call caps read from SQL (ADR-005
decision 5; docs/spec/09 Cost controls).

AC-SEC-6: a Tier-2 sentinel sent with and without the purpose consent (allowed, blocked, schema failure echoing it,
kill switch) appears in no stored column of any ``llm_calls`` row, read as the table owner, nor in the inputs staff
admin reads through ``app_llm_call_inputs()``. Caps: the subject's monthly cap (its plan's
``llm_monthly_cap_usd``; this month's rows of that subject only) and the global daily cap (every tenant's rows today,
summed by ``app_llm_spend_usd()`` although bridge_app sees none of them) refuse at the cap and record the refusal.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge import clock
from bridge.billing import plans
from bridge.config import get_settings
from bridge.db import bind_tenant
from bridge.ids import uuid7
from bridge.llm.budget import cap_from_limits, day_start, month_start
from bridge.llm.errors import ConsentRequired, LLMBudgetExceeded, LLMKillSwitch, LLMSchemaError, Tier2NotAllowed
from bridge.llm.fakes import FakeAdapter
from bridge.llm.guard import grant_session_consent
from bridge.llm.sql_ledger import SqlLedger
from bridge.llm.types import CallContext, InputField, Instruction, Message, Tier
from bridge.models.enums import PlanSide
from tests.integration.llm.conftest import People
from tests.integration.llm.helpers import TASK, login, reply, service, stored
from tests.unit.llm.rig import screen
from tests.unit.llm.schemas import Verdict

Factory = async_sessionmaker[AsyncSession]
CANARY = "CANARY-T2-SQL-5d1e8b27"
ASSISTANT = "submission_assistant"


def tier2_call(owner: UUID) -> list[Message]:
    return [
        Message.system("You suggest placements."),
        Message.user(
            Instruction("Suggest:"),
            InputField("teaser.summary", "Public teaser: solar cold rooms."),
            InputField("confidential.method", f"The method is {CANARY}.", tier=Tier.TIER2, owner_id=owner),
        ),
    ]


async def test_a_tier2_sentinel_never_reaches_any_stored_column(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    trace, session, other_session = f"sec6-{people.tag}", await login(factory, people.a), await login(factory, people.a)
    echo = {"injection_suspected": False, "verdict": "clean", "reason": "r", CANARY: 1}  # an answer quoting it
    quoting = {"injection_suspected": False, "verdict": "clean", "reason": f"keep {CANARY} private"}
    adapter = FakeAdapter([reply(quoting), reply(echo), reply(echo)])
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        await grant_session_consent(db, get_settings(), user_id=people.a, session_id=session)
        await db.commit()
        svc = service(db, factory, adapter)
        ctx = CallContext(user_id=people.a, trace_id=trace, session_id=session)
        await svc.complete(ASSISTANT, tier2_call(people.a), Verdict, ctx=ctx)  # consented: sent
        elsewhere = CallContext(user_id=people.a, trace_id=trace, session_id=other_session)
        with pytest.raises(ConsentRequired):  # the opt-in belongs to another login session
            await svc.complete(ASSISTANT, tier2_call(people.a), Verdict, ctx=elsewhere)
        with pytest.raises(Tier2NotAllowed):  # a Tier-1-only task
            await svc.complete(TASK, tier2_call(people.a), Verdict, ctx=ctx)
        with pytest.raises(LLMSchemaError):  # consented, the answer echoes the value twice
            await svc.complete(ASSISTANT, tier2_call(people.a), Verdict, ctx=ctx)
        with pytest.raises(LLMKillSwitch):
            await service(db, factory, adapter, llm_kill_switch=True).complete(
                ASSISTANT, tier2_call(people.a), Verdict, ctx=ctx
            )
    sent = [block.text for request in adapter.requests for m in request.messages for block in m.blocks]
    assert any(CANARY in text_ for text_ in sent)  # positive control: the consented purpose does send it
    rows = await stored(owner_engine, trace)
    assert [r["status"] for r in rows] == [
        "ok",
        "blocked_consent",
        "blocked_tier2",
        "schema_error",
        "schema_error",
        "blocked_kill_switch",
    ]
    assert [r["purpose"] for r in rows] == ["tier2_llm_assistant"] * 2 + [None] + ["tier2_llm_assistant"] * 3
    async with owner_engine.connect() as conn:  # every column of every row in the table, as text
        leaked = await conn.execute(
            text("SELECT count(*) FROM llm_calls c WHERE strpos(CAST(to_jsonb(c.*) AS text), :canary) > 0"),
            {"canary": CANARY},
        )
        assert leaked.scalar_one() == 0
    async with factory() as db:  # what staff admin reads: names, tiers and lengths of the Tier-2 field only
        await bind_tenant(db, user_id=people.admin)
        for row in rows:
            inputs = (await db.execute(text("SELECT app_llm_call_inputs(:id)"), {"id": row["id"]})).scalar_one()
            assert CANARY not in str(inputs)
            [tier2] = [f for f in inputs["fields"] if f["tier"] == "tier2"]
            assert set(tier2) <= {"name", "tier", "chars", "removed"}
            assert tier2["name"] == "confidential.method"


async def seed_spend(
    owner_engine: AsyncEngine, cost: Decimal, *, org: UUID | None, user: UUID | None, when: datetime | None = None
) -> None:
    """A spend row written as the owner (``when`` defaults to the database's now())."""
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO llm_calls (id, org_id, user_id, task, model, status, cost_usd, created_at)"
                " VALUES (:id, :org, :user, 'seed', 'm', 'ok', :cost, coalesce(:when, now()))"
            ),
            {"id": uuid7(), "org": org, "user": user, "cost": cost, "when": when},
        )


@pytest.mark.parametrize("subject", ["org", "user"])
async def test_the_monthly_cap_refuses_at_the_cap_counting_this_subject_and_month_only(
    factory: Factory, owner_engine: AsyncEngine, people: People, subject: Literal["org", "user"]
) -> None:
    """Neither has a subscription, so the side's free plan applies (its cap from config/plans.yaml)."""
    side = PlanSide.ORG if subject == "org" else PlanSide.DEVELOPER
    cap = cap_from_limits(plans.load(get_settings().plans_file).default_for(side).limits)
    assert cap is not None
    assert cap > 0
    org = people.org_a if subject == "org" else None
    noise = cap + 1  # each of these alone would pass the cap
    await seed_spend(owner_engine, noise, org=org, user=people.a, when=month_start(clock.utcnow()) - timedelta(hours=1))
    await seed_spend(owner_engine, noise, org=people.org_b, user=people.b)  # another tenant
    # the same user under the other subject: A's own spend for the organisation, A's organisation's for A
    await seed_spend(owner_engine, noise, org=None if subject == "org" else people.org_a, user=people.a)
    await seed_spend(owner_engine, cap / 2, org=org, user=people.a)
    trace = f"cap-{subject}-{people.tag}"
    ctx = CallContext(org_id=org, user_id=people.a, trace_id=trace)
    adapter = FakeAdapter([reply(), reply()])
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        svc = service(db, factory, adapter)
        result = await svc.complete(TASK, screen(), Verdict, ctx=ctx)  # half the cap spent: allowed
        assert (result.budget.spent_usd, result.budget.cap_usd) == (cap / 2 + result.cost_usd, cap)
        await seed_spend(owner_engine, cap / 2 - result.cost_usd, org=org, user=people.a)  # exactly at the cap
        assert (
            await SqlLedger(factory, caller=db).tenant_spent_usd(
                org_id=org, user_id=people.a, since=month_start(clock.utcnow())
            )
            == cap
        )
        with pytest.raises(LLMBudgetExceeded) as info:
            await svc.complete(TASK, screen(), Verdict, ctx=ctx)
    assert (info.value.scope, info.value.spent_usd, info.value.cap_usd) == ("tenant", cap, cap)
    assert len(adapter.requests) == 1
    assert [r["status"] for r in await stored(owner_engine, trace)] == ["ok", "blocked_budget"]


async def test_the_global_daily_cap_counts_every_tenant_through_the_definer(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    trace = f"global-{people.tag}"
    ctx = CallContext(org_id=people.org_a, user_id=people.a, trace_id=trace)
    adapter = FakeAdapter([reply(), reply()])
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        ledger = SqlLedger(factory, caller=db)
        before = await ledger.global_spent_usd(since=day_start(clock.utcnow()))
        await seed_spend(owner_engine, Decimal("3.25"), org=people.org_b, user=people.b)
        spent = await ledger.global_spent_usd(since=day_start(clock.utcnow()))
        assert spent - before == Decimal("3.25")  # organisation B's spend counts for A's check...
        hidden = await db.execute(text("SELECT count(*) FROM llm_calls WHERE org_id = :b"), {"b": people.org_b})
        assert hidden.scalar_one() == 0  # ...although A reads none of B's rows
        roomy = service(db, factory, adapter, llm_global_daily_cap_usd=spent + 1)
        await roomy.complete(TASK, screen(), Verdict, ctx=ctx)
        now_spent = await ledger.global_spent_usd(since=day_start(clock.utcnow()))
        at_cap = service(db, factory, adapter, llm_global_daily_cap_usd=now_spent)
        with pytest.raises(LLMBudgetExceeded) as info:
            await at_cap.complete(TASK, screen(), Verdict, ctx=ctx)
    assert (info.value.scope, info.value.spent_usd, info.value.cap_usd) == ("global", now_spent, now_spent)
    assert len(adapter.requests) == 1
    assert [r["status"] for r in await stored(owner_engine, trace)] == ["ok", "blocked_budget"]
