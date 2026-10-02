"""REQ-REPO-01 (warn only) through the API: ``POST /api/me/proposals/{id}/disclosure-check``.

The rules answer an obvious "how" without a model; a plain teaser goes to the ``over_disclosure_check`` task (the
labelled demo fallback with the fake provider; the scripted answer on a free slot for demo accounts, Tier 1 only);
owner only; the assistant's daily limit counts this task's ledger rows. Nothing blocks publishing.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.proposals import disclosure, disclosure_router
from bridge.proposals.assistant_policy import AssistantPolicy
from bridge.proposals.disclosure import DisclosureVerdict
from tests.integration.proposals.assistant_rig import install, llm_rows, make_demo, new_draft
from tests.integration.proposals.helpers import (
    TIER2_MARKERS,
    Developers,
    ProposalWorld,
    create,
    draft_body,
    publish,
    published,
    user_of,
)
from tests.integration.proposals.test_assistant_limits_api import HeldAdapter

PATH = "/api/me/proposals/{}/disclosure-check"
HOW = "We use a gradient-boosted model over two years of readings to predict when a cooler fails."


def flagged() -> DisclosureVerdict:
    return DisclosureVerdict(
        injection_suspected=False, flagged=True, fields=["summary"], why="Say what farmers get, not how it predicts."
    )


async def test_the_rules_warn_without_a_model_and_publishing_still_works(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    adapter = install(client)  # a free slot with no scripted reply: a call would fail loudly
    proposal_id = await new_draft(client, proposal_world, summary=HOW)
    response = await client.post(PATH.format(proposal_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["flagged"], body["fields"], body["source"], body["why"], body["demo_fallback"]) == (
        True,
        ["summary"],
        "rules",
        disclosure.RULES_WHY,
        False,
    )
    assert adapter.requests == []
    assert await llm_rows(owner_engine, user_of(client)) == []
    assert (await publish(client, proposal_id)).status_code == 200  # warn only


async def test_a_plain_teaser_with_the_fake_provider_is_a_labelled_fallback(
    developers: Developers, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    install(client, provider="fake")
    proposal_id = await new_draft(client, proposal_world)
    body = (await client.post(PATH.format(proposal_id))).json()
    assert (body["flagged"], body["source"], body["demo_fallback"], body["why"]) == (
        False,
        "none",
        True,
        disclosure.DEMO_FALLBACK,
    )


async def test_a_demo_account_gets_the_models_warning_on_tier1_only(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    await make_demo(owner_engine, user_of(client))
    adapter = install(client, flagged())
    proposal_id = await new_draft(client, proposal_world)
    body = (await client.post(PATH.format(proposal_id))).json()
    assert (body["flagged"], body["fields"], body["source"], body["ai_drafted"]) == (True, ["summary"], "model", True)
    [request] = adapter.requests
    sent = "".join(b.text for m in request.messages for b in m.blocks)
    assert "An SMS goes out when a cooler warms up." in sent
    assert not any(marker in sent for marker in TIER2_MARKERS)
    [row] = await llm_rows(owner_engine, user_of(client))
    assert row.status == "ok"


async def test_owner_only(developers: Developers, proposal_world: ProposalWorld) -> None:
    owner, stranger = await developers(), await developers()
    for client in (owner, stranger):
        install(client, provider="fake")
    out = await published(owner, proposal_world)
    draft = await create(owner, draft_body(proposal_world))
    refused = await stranger.post(PATH.format(out["proposal_id"]))
    assert (refused.status_code, refused.json()["detail"]["code"]) == (404, "not_found")
    assert (await stranger.post(PATH.format(draft["id"]))).status_code == 404


async def test_the_assistants_daily_limit_counts_these_calls(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    limited = AssistantPolicy(
        max_calls_per_user_day=2, max_in_flight_per_user=1, tier2_overlap_words=8, max_reason_chars=300
    )
    monkeypatch.setattr(disclosure_router, "get_assistant_policy", lambda: limited)
    client = await developers()
    await make_demo(owner_engine, user_of(client))
    adapter = install(client, flagged(), flagged(), flagged())
    proposal_id = await new_draft(client, proposal_world)
    for _ in range(2):
        assert (await client.post(PATH.format(proposal_id))).status_code == 200
    refused = await client.post(PATH.format(proposal_id))
    assert refused.status_code == 429, refused.text
    assert refused.json()["detail"] == {"code": "disclosure_rate_limited", "message": disclosure.RATE_LIMITED}
    assert len(adapter.requests) == 2


async def test_two_processes_with_one_call_left_let_only_one_through(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two API processes (two apps, so two in-flight guards) for one user with one call left: the second waits on the
    per-user lock while the first is at the model, then counts its ledger row and is refused."""
    limited = AssistantPolicy(
        max_calls_per_user_day=2, max_in_flight_per_user=1, tier2_overlap_words=8, max_reason_chars=300
    )
    monkeypatch.setattr(disclosure_router, "get_assistant_policy", lambda: limited)
    first = await developers()
    owner = user_of(first)
    await make_demo(owner_engine, owner)
    second = await developers(user_id=owner)
    held = HeldAdapter(flagged(), flagged())
    install(first, adapter=held)
    other = install(second, flagged())
    proposal_id = await new_draft(first, proposal_world)
    held.release.set()
    assert (await first.post(PATH.format(proposal_id))).status_code == 200  # one of two used
    held.release.clear()
    held.entered.clear()

    racing = asyncio.create_task(first.post(PATH.format(proposal_id)))
    await asyncio.wait_for(held.entered.wait(), timeout=20)
    waiting = asyncio.create_task(second.post(PATH.format(proposal_id)))
    done, _ = await asyncio.wait({waiting}, timeout=1.0)
    assert not done  # blocked on the lock, not answered from a stale count
    held.release.set()
    won, lost = await asyncio.gather(racing, waiting)
    assert won.status_code == 200, won.text
    assert lost.status_code == 429, lost.text
    assert lost.json()["detail"]["code"] == "disclosure_rate_limited"
    assert other.requests == []
    assert len(await llm_rows(owner_engine, owner)) == 2
