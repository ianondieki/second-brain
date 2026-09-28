"""REQ-LLM-01 (ADR-005 decision 5; T2.1 schema v2): the ``llm_calls`` ledger in PostgreSQL, as ``bridge_app`` under
Row-Level Security.

One row per call attempt, blocked and refused ones included, with the call's tenant, tokens, cost, latency, status,
stop reason and trace id, committed on its own so it survives the caller's rollback; organisation A reads none of
organisation B's rows; ``inputs`` is unreadable by bridge_app and read by staff admin only, through
``app_llm_call_inputs()``. AC-SEC-6 and the caps against SQL are in ``test_sql_caps_and_tier2.py``.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge import clock
from bridge.config import get_settings
from bridge.db import bind_tenant
from bridge.ids import uuid7
from bridge.llm import registry
from bridge.llm.budget import month_start
from bridge.llm.errors import LLMBudgetExceeded, LLMConfigError, LLMKillSwitch, LLMRefused, Tier2NotAllowed
from bridge.llm.fakes import FakeAdapter
from bridge.llm.models import LlmCall
from bridge.llm.sql_ledger import SqlLedger
from bridge.llm.types import CallContext, InputField, Instruction, Message, Tier
from tests.integration.llm.conftest import People
from tests.integration.llm.helpers import TASK, USAGE, reply, service, stored
from tests.unit.llm.rig import screen
from tests.unit.llm.schemas import Verdict

SPEC = registry.load(get_settings().llm_models_file).task(TASK)
Factory = async_sessionmaker[AsyncSession]


async def test_one_row_per_call_with_its_tenant_tokens_cost_latency_and_trace(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    trace = f"one-{people.tag}"
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        svc = service(db, factory, FakeAdapter([reply()]))
        ctx = CallContext(org_id=people.org_a, user_id=people.a, trace_id=trace)
        result = await svc.complete(TASK, screen(), Verdict, ctx=ctx)
    [row] = await stored(owner_engine, trace)
    assert (row["org_id"], row["user_id"], row["task"], row["model"]) == (people.org_a, people.a, TASK, SPEC.model)
    assert row["purpose"] is None  # a Tier-1-only task needs no consent purpose
    assert (row["input_tokens"], row["output_tokens"], row["cache_read_tokens"], row["cache_write_tokens"]) == (
        USAGE.input_tokens,
        USAGE.output_tokens,
        USAGE.cache_read_input_tokens,
        USAGE.cache_creation_input_tokens,
    )
    assert row["cost_usd"] == result.cost_usd > 0
    assert (row["status"], row["stop_reason"], row["trace_id"]) == ("ok", "end_turn", trace)
    assert row["latency_ms"] is not None
    assert row["latency_ms"] >= 0
    assert abs(row["created_at"] - clock.utcnow()) < timedelta(minutes=5)
    [field] = row["inputs"]["fields"]  # the sanitised Tier-1 value, as the model saw it
    assert (field["name"], field["tier"], field["value"]) == ("teaser.summary", "tier1", "Solar kiosks for markets")
    assert re.fullmatch(r"[0-9a-f]{64}", row["inputs"]["prompt_sha256"])


async def test_blocked_and_refused_calls_are_rows_that_survive_the_callers_rollback(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    trace = f"blocked-{people.tag}"
    ctx = CallContext(org_id=people.org_a, user_id=people.a, trace_id=trace)
    tier2 = [
        Message.system("You screen teasers."),
        Message.user(Instruction("Screen:"), InputField("confidential.m", "x", tier=Tier.TIER2, owner_id=people.a)),
    ]
    adapter = FakeAdapter([reply(stop_reason="refusal")])
    marker = uuid7()
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        await db.execute(  # the caller's own work, never committed
            text(
                "INSERT INTO llm_calls (id, user_id, task, model, status, trace_id)"
                " VALUES (:id, :u, 'c', 'm', 'ok', :t)"
            ),
            {"id": marker, "u": people.a, "t": trace},
        )
        with pytest.raises(LLMKillSwitch):
            await service(db, factory, adapter, llm_kill_switch=True).complete(TASK, screen(), Verdict, ctx=ctx)
        with pytest.raises(Tier2NotAllowed):
            await service(db, factory, adapter).complete(TASK, tier2, Verdict, ctx=ctx)
        no_budget = service(db, factory, adapter, llm_global_daily_cap_usd=Decimal(0))
        with pytest.raises(LLMBudgetExceeded):
            await no_budget.complete(TASK, screen(), Verdict, ctx=ctx)
        with pytest.raises(LLMRefused):
            await service(db, factory, adapter).complete(TASK, screen(), Verdict, ctx=ctx)
        await db.rollback()
    rows = await stored(owner_engine, trace)
    assert [r["status"] for r in rows] == ["blocked_kill_switch", "blocked_tier2", "blocked_budget", "refusal"]
    assert marker not in {r["id"] for r in rows}  # the caller's write rolled back; the ledger's rows did not
    assert len(adapter.requests) == 1  # only the refused attempt reached the model
    for row in rows[:3]:  # nothing sent, nothing billed; the rows still name the targeted model and the tenant
        assert (row["model"], row["cost_usd"], row["input_tokens"], row["output_tokens"]) == (SPEC.model, 0, 0, 0)
        assert (row["org_id"], row["user_id"], row["stop_reason"]) == (people.org_a, people.a, None)
    for row in rows[:2]:  # refused before sanitising: names and lengths only
        assert all("value" not in f for f in row["inputs"]["fields"])
    assert (rows[3]["stop_reason"], rows[3]["output_tokens"]) == ("refusal", USAGE.output_tokens)
    assert rows[3]["cost_usd"] > 0


async def count(factory: Factory, user: UUID | None, sql: str, *, org: UUID | None = None, **params: object) -> int:
    """``sql`` as bridge_app bound to ``user`` (and ``org``), as a request is."""
    async with factory() as db:
        await bind_tenant(db, user_id=user, org_id=org)
        return int((await db.execute(text(sql), params)).scalar_one())


async def test_organisation_a_reads_none_of_organisation_bs_rows(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    traces = {"a": f"iso-a-{people.tag}", "b": f"iso-b-{people.tag}"}
    for label, user, org in (("a", people.a, people.org_a), ("b", people.b, people.org_b)):
        async with factory() as db:
            await bind_tenant(db, user_id=user)
            ctx = CallContext(org_id=org, user_id=user, trace_id=traces[label])
            await service(db, factory, FakeAdapter([reply()])).complete(TASK, screen(), Verdict, ctx=ctx)
    by_trace = "SELECT count(*) FROM llm_calls WHERE trace_id = :t"
    by_org = "SELECT count(*) FROM llm_calls WHERE org_id = :o"
    assert await count(factory, people.a, by_trace, t=traces["a"]) == 1
    assert await count(factory, people.a, by_trace, t=traces["b"]) == 0
    assert await count(factory, people.a, by_org, o=people.org_b) == 0
    assert await count(factory, people.a, by_trace, org=people.org_a, t=traces["b"]) == 0
    assert await count(factory, people.viewer, by_trace, t=traces["a"]) == 1  # every active member reads its org's
    assert await count(factory, people.viewer, by_trace, t=traces["b"]) == 0
    assert await count(factory, None, by_trace, t=traces["a"]) == 0  # no tenant context reads nothing
    assert await count(factory, people.admin, by_trace, t=traces["b"]) == 1  # staff admin reads every row

    # A's session neither sums B's spend nor records a call for B or for B's user; nor does an unbound session.
    refused, adapter = f"iso-x-{people.tag}", FakeAdapter([reply()])
    async with factory() as db:
        await bind_tenant(db, user_id=people.a, org_id=people.org_a)
        with pytest.raises(LLMConfigError):
            await SqlLedger(factory, caller=db).tenant_spent_usd(
                org_id=people.org_b, user_id=None, since=month_start(clock.utcnow())
            )
        for ctx in (
            CallContext(org_id=people.org_b, user_id=people.a),
            CallContext(org_id=people.org_b),
            CallContext(user_id=people.b),
        ):
            with pytest.raises(LLMConfigError):
                await service(db, factory, adapter).complete(
                    TASK, screen(), Verdict, ctx=replace(ctx, trace_id=refused)
                )
    async with factory() as db:
        ctx = CallContext(org_id=people.org_a, trace_id=refused)
        with pytest.raises(LLMConfigError):
            await service(db, factory, adapter).complete(TASK, screen(), Verdict, ctx=ctx)
    assert adapter.requests == []
    assert await stored(owner_engine, refused) == []


async def test_a_call_for_an_organisation_the_bound_user_is_no_active_member_of_is_refused_before_sending(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    """A request bound to its user only (no organisation) may call for an organisation that user is an active member
    of, whatever the role; any other organisation is refused unsent and unrecorded (RLS would refuse the row after the
    paid call, and would sum none of that organisation's spend)."""
    refused, allowed, adapter = f"member-x-{people.tag}", f"member-ok-{people.tag}", FakeAdapter([reply()])
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        ctx = CallContext(org_id=people.org_b, user_id=people.a, trace_id=refused)
        with pytest.raises(LLMConfigError, match="no active member"):
            await service(db, factory, adapter).complete(TASK, screen(), Verdict, ctx=ctx)
    assert adapter.requests == []

    viewer = CallContext(org_id=people.org_a, user_id=people.viewer, trace_id=allowed)
    async with factory() as db:  # positive control: a viewer is an active member of org_a
        await bind_tenant(db, user_id=people.viewer)
        await service(db, factory, adapter).complete(TASK, screen(), Verdict, ctx=viewer)
    [row] = await stored(owner_engine, allowed)
    assert (row["org_id"], row["user_id"], row["status"]) == (people.org_a, people.viewer, "ok")
    assert len(adapter.requests) == 1

    async with owner_engine.begin() as conn:  # the viewer leaves org_a: a removed member is no active member
        await conn.execute(
            text("UPDATE memberships SET status = 'removed' WHERE org_id = :o AND user_id = :u"),
            {"o": people.org_a, "u": people.viewer},
        )
    async with factory() as db:
        await bind_tenant(db, user_id=people.viewer)
        with pytest.raises(LLMConfigError, match="no active member"):
            await service(db, factory, adapter).complete(TASK, screen(), Verdict, ctx=replace(viewer, trace_id=refused))
    assert len(adapter.requests) == 1
    assert await stored(owner_engine, refused) == []


async def test_inputs_are_unreadable_by_bridge_app_and_read_by_staff_admin_only(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    trace = f"inputs-{people.tag}"
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        ctx = CallContext(user_id=people.a, trace_id=trace)
        await service(db, factory, FakeAdapter([reply()])).complete(TASK, screen(), Verdict, ctx=ctx)
    [row] = await stored(owner_engine, trace)
    read = "SELECT app_llm_call_inputs(:id)"
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        mapped = (await db.execute(select(LlmCall).where(LlmCall.id == row["id"]))).scalar_one()
        assert mapped.task == TASK  # the mapper never selects inputs
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.execute(text("SELECT inputs FROM llm_calls WHERE id = :id"), {"id": row["id"]})
    for caller in (people.a, people.viewer, None):
        async with factory() as db:
            await bind_tenant(db, user_id=caller)
            with pytest.raises(DBAPIError, match="staff admin only"):
                await db.execute(text(read), {"id": row["id"]})
    async with factory() as db:
        await bind_tenant(db, user_id=people.admin)
        inputs = (await db.execute(text(read), {"id": row["id"]})).scalar_one()
    assert inputs == row["inputs"]
    assert inputs["fields"][0]["value"] == "Solar kiosks for markets"
