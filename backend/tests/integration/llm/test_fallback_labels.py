"""REQ-LLM-01 (D-37): on a local run the Anthropic route answers with the labelled "demo fallback" instead of a model
when the key is missing, when the platform's daily cap or the subject's monthly cap is spent, and when the kill switch
is on; nothing reaches the provider, and the reason is kept. Through the submission assistant's API, whose answer
carries ``demo_fallback: true`` (the UI's label) and whose audit event names the reason; the ``llm_calls`` ledger
records each refusal the budget guard made. (The fake and free routes' fallbacks are
``test_assistant_suggestions_api.py``'s and ``tests/unit/llm/test_routing*.py``'s.)
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge import clock
from bridge.ids import uuid7
from bridge.llm.budget import month_start
from tests.integration.llm.helpers import ROOMY_GLOBAL_CAP
from tests.integration.proposals.assistant_rig import ask, audit_rows, grant, install, llm_rows, new_draft, suggestion
from tests.integration.proposals.helpers import Developers, ProposalWorld, user_of

ROOMY = {"llm_global_daily_cap_usd": ROOMY_GLOBAL_CAP, "llm_prototype_total_cap_usd": ROOMY_GLOBAL_CAP}
LABELLED = {
    "demo_fallback": True,
    "status": "demo_fallback",
    "message": "Demo fallback: no model answered, so there is no suggestion.",
    "ai_drafted": False,
    "teaser": None,
    "placement": [],
}


async def spent_this_month(owner_engine: AsyncEngine, user_id: Any, cost: Decimal) -> None:
    """``cost`` already spent by ``user_id`` this month, from its first second (as the owner role: the app cannot write
    the ledger's past)."""
    earlier = month_start(clock.utcnow())
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO llm_calls (id, user_id, task, model, status, cost_usd, created_at)"
                " VALUES (:id, :user, 'seed', 'm', 'ok', :cost, :at)"
            ),
            {"id": uuid7(), "user": user_id, "cost": cost, "at": earlier},
        )


@pytest.mark.parametrize(
    ("case", "reason", "blocked"),
    [
        ("no-key", "no_key", []),  # routed away before any service runs: nothing to record
        ("daily-cap", "budget", ["blocked_budget"]),
        ("monthly-cap", "budget", ["blocked_budget"]),
        ("kill-switch", "kill_switch", ["blocked_kill_switch"]),
    ],
    ids=["no-key", "daily-cap", "monthly-cap", "kill-switch"],
)
async def test_the_anthropic_route_answers_the_labelled_fallback_and_sends_nothing(
    developers: Developers,
    owner_engine: AsyncEngine,
    proposal_world: ProposalWorld,
    case: str,
    reason: str,
    blocked: list[str],
) -> None:
    client = await developers()
    app = client.app  # type: ignore[attr-defined]
    update: dict[str, Any] = {} if case == "daily-cap" else dict(ROOMY)  # the test settings' daily cap is USD 0
    if case == "kill-switch":
        update["llm_kill_switch"] = True
    if case == "monthly-cap":  # the developer's free plan allows USD 0.50 a month (config/plans.yaml): all spent
        await spent_this_month(owner_engine, user_of(client), Decimal("0.50"))
    app.state.settings = app.state.settings.model_copy(update=update)
    adapter = install(client, suggestion(), provider="anthropic")
    # A local run (dev, test): failures are answered by the fallback; without a key the route itself is the fallback.
    app.state.llm_runtime = replace(app.state.llm_runtime, demo_fallback=True, anthropic_configured=case != "no-key")
    proposal_id = await new_draft(client, proposal_world)
    assert (await grant(client, proposal_id)).status_code == 200

    response = await ask(client, proposal_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body | {"version_id": None} == LABELLED | {"version_id": None}
    assert adapter.requests == []  # nothing reached the provider
    [event] = await audit_rows(owner_engine, user_of(client), "proposal.assistant_suggested")
    assert (event["status"], event["demo_fallback"], event["reason"]) == (
        "demo_fallback",
        True,
        f"demo_fallback:{reason}",
    )
    calls = [row.status for row in await llm_rows(owner_engine, user_of(client))]
    assert [status for status in calls if status != "ok"] == blocked  # the seeded month's spend is the one "ok" row
    assert "ok" not in calls or case == "monthly-cap"
