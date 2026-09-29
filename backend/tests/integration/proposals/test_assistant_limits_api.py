"""REQ-PROP-05 (security review MAJOR 2): the submission assistant's per-user limits, through the API.

One suggestion in flight per user: a concurrent burst sends exactly one provider request, and every other request of
the burst answers 429 ``assistant_busy`` before the confidential text is read. A daily limit of the user's
``submission_assistant`` ledger rows (``policy.yaml`` ``assistant``) answers 429 ``assistant_rate_limited``. Neither
refusal reads Tier 2 or writes a ledger row.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.llm.adapter import ModelRequest, ModelResponse
from bridge.llm.fakes import FakeAdapter
from bridge.proposals import assistant, assistant_router
from bridge.proposals.assistant_policy import AssistantPolicy
from tests.integration.proposals.assistant_rig import (
    ask,
    audit_rows,
    grant,
    install,
    llm_rows,
    make_demo,
    new_draft,
    suggestion,
)
from tests.integration.proposals.helpers import Developers, ProposalWorld, user_of

BURST = 12


class HeldAdapter(FakeAdapter):
    """A provider that holds each request until ``release`` is set, so the burst overlaps the call in flight."""

    def __init__(self, *replies: object) -> None:
        super().__init__(replies)  # type: ignore[arg-type]
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def create(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        self.entered.set()
        await self.release.wait()
        reply = self._next(request)
        assert isinstance(reply, ModelResponse)
        return reply


async def test_a_burst_sends_one_request_and_the_rest_are_refused_before_reading(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    owner = user_of(client)
    await make_demo(owner_engine, owner)
    adapter = install(client, adapter=HeldAdapter(*[suggestion()] * BURST))
    assert isinstance(adapter, HeldAdapter)
    proposal_id = await new_draft(client, proposal_world)
    assert (await grant(client, proposal_id)).status_code == 200

    tasks = [asyncio.create_task(ask(client, proposal_id)) for _ in range(BURST)]
    await asyncio.wait_for(adapter.entered.wait(), timeout=20)
    pending: set[asyncio.Task[httpx.Response]] = set(tasks)
    async with asyncio.timeout(20):
        while len(pending) > 1:  # everyone but the one in flight answers while it is held
            _, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
    assert len(adapter.requests) == 1
    adapter.release.set()
    responses = await asyncio.gather(*tasks)

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200] + [429] * (BURST - 1)
    busy = [r.json()["detail"] for r in responses if r.status_code == 429]
    assert all(d == {"code": "assistant_busy", "message": assistant.BUSY} for d in busy)
    assert len(adapter.requests) == 1
    assert len(await llm_rows(owner_engine, owner)) == 1
    assert len(await audit_rows(owner_engine, owner, "proposal.assistant_suggested")) == 1  # only the one call
    assert (await ask(client, proposal_id)).status_code == 200  # the slot is released afterwards


async def test_the_daily_limit_counts_the_users_calls(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    limited = AssistantPolicy(
        max_calls_per_user_day=2, max_in_flight_per_user=1, tier2_overlap_words=8, max_reason_chars=300
    )
    monkeypatch.setattr(assistant_router, "get_assistant_policy", lambda: limited)
    client = await developers()
    owner = user_of(client)
    await make_demo(owner_engine, owner)
    adapter = install(client, *[suggestion()] * 3)
    proposal_id = await new_draft(client, proposal_world)
    assert (await grant(client, proposal_id)).status_code == 200
    for _ in range(2):
        assert (await ask(client, proposal_id)).status_code == 200
    refused = await ask(client, proposal_id)
    assert refused.status_code == 429, refused.text
    assert refused.json()["detail"] == {
        "code": "assistant_rate_limited",
        "message": "You have asked the writing assistant for many suggestions today. Try again tomorrow.",
    }
    assert len(adapter.requests) == 2
    assert len(await llm_rows(owner_engine, owner)) == 2
    assert len(await audit_rows(owner_engine, owner, "proposal.assistant_suggested")) == 2

    other = await developers()  # the limit is per user
    await make_demo(owner_engine, user_of(other))
    install(other, suggestion())
    theirs = await new_draft(other, proposal_world)
    assert (await grant(other, theirs)).status_code == 200
    assert (await ask(other, theirs)).status_code == 200
