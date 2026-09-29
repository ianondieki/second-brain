"""REQ-PROP-05, AC-SEC-6, D-37: the submission assistant's suggestions against PostgreSQL through the API.

- D-37: a non-demo owner's confidential text never reaches a free provider (403 ``assistant_demo_only``, a
  ``blocked_tier2`` row with names and lengths only); a non-demo owner's Tier-1-only draft is answered by the labelled
  demo fallback; nothing reaches the fake adapter either way.
- A demo fallback is "no suggestion" with ``demo_fallback: true``.
- A global budget error answers a fixed message without the platform's figures.
- An injection in the teaser is framed as data; a flagged answer, or an answer the Tier-1 rules refuse, is no
  suggestion.
- The assistant never writes the proposal.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.proposals.assistant_rig import (
    INJECTION,
    ask,
    audit_rows,
    grant,
    install,
    llm_rows,
    make_demo,
    new_draft,
    suggestion,
)
from tests.integration.proposals.helpers import (
    SECRET_APPROACH,
    TIER2_MARKERS,
    Developers,
    ProposalWorld,
    publish,
    user_of,
)


def sent_text(adapter_request: object) -> str:
    return "\n".join(block.text for message in adapter_request.messages for block in message.blocks)  # type: ignore[attr-defined]


async def test_a_demo_owner_gets_one_checked_suggestion_and_the_proposal_is_unchanged(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    owner = user_of(client)
    await make_demo(owner_engine, owner)
    adapter = install(client, suggestion())
    proposal_id = await new_draft(client, proposal_world)
    before = (await client.get(f"/api/me/proposals/{proposal_id}")).json()
    assert (await grant(client, proposal_id)).status_code == 200
    response = await ask(client, proposal_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "suggested"
    assert (body["demo_fallback"], body["ai_drafted"]) == (False, True)
    assert body["teaser"]["title"] == "Cold-chain alerts for dairy farmers"
    assert body["placement"] == [{"field": "pricing", "move": "to_tier1", "reason": "Organisations filter by budget."}]
    assert body["version_id"] == before["draft"]["id"]
    [request] = adapter.requests
    assert SECRET_APPROACH in sent_text(request)  # consented, demo account: Tier 2 goes to the slot
    after = (await client.get(f"/api/me/proposals/{proposal_id}")).json()
    assert after["draft"]["teaser"] == before["draft"]["teaser"]
    assert (after["status"], after["published_at"]) == ("draft", None)
    [row] = await llm_rows(owner_engine, owner)
    assert (row.status, row.purpose) == ("ok", "tier2_llm_assistant")
    assert not any(marker in json.dumps(row.inputs) for marker in TIER2_MARKERS)
    [event] = await audit_rows(owner_engine, owner, "proposal.assistant_suggested")
    assert (event["status"], event["demo_fallback"]) == ("suggested", False)
    assert event["tier2_fields"] == ["approach", "architecture", "pricing"]


async def test_a_published_proposal_is_read_from_its_current_version(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    await make_demo(owner_engine, user_of(client))
    install(client, suggestion())
    proposal_id = await new_draft(client, proposal_world)
    published = await publish(client, proposal_id)
    assert published.status_code == 200
    assert (await grant(client, proposal_id)).status_code == 200
    body = (await ask(client, proposal_id)).json()
    assert body["status"] == "suggested"
    current = (await client.get(f"/api/me/proposals/{proposal_id}")).json()["current"]
    assert body["version_id"] == current["id"]


async def test_a_non_demo_owners_confidential_text_never_reaches_a_free_provider(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()  # not a demo account
    adapter = install(client, suggestion())
    proposal_id = await new_draft(client, proposal_world)
    assert (await grant(client, proposal_id)).status_code == 200
    refused = await ask(client, proposal_id)
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == {
        "code": "assistant_demo_only",
        "message": "In this demo, the writing assistant works only with demo accounts.",
    }
    assert adapter.requests == []
    [row] = await llm_rows(owner_engine, user_of(client))
    assert row.status == "blocked_tier2"
    assert not any(marker in json.dumps(row.inputs) for marker in TIER2_MARKERS)


async def test_a_non_demo_owners_teaser_gets_the_labelled_fallback(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    adapter = install(client, suggestion())
    proposal_id = await new_draft(client, proposal_world, confidential=False)
    assert (await grant(client, proposal_id)).status_code == 200
    body = (await ask(client, proposal_id)).json()
    assert (body["status"], body["demo_fallback"], body["teaser"], body["placement"]) == (
        "demo_fallback",
        True,
        None,
        [],
    )
    assert adapter.requests == []


async def test_the_demo_fallback_is_no_suggestion_and_labelled(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    await make_demo(owner_engine, user_of(client))
    adapter = install(client, provider="fake")
    proposal_id = await new_draft(client, proposal_world)
    assert (await grant(client, proposal_id)).status_code == 200
    body = (await ask(client, proposal_id)).json()
    assert body == {
        "demo_fallback": True,
        "status": "demo_fallback",
        "message": "Demo fallback: no model answered, so there is no suggestion.",
        "ai_drafted": False,
        "version_id": body["version_id"],
        "teaser": None,
        "placement": [],
    }
    assert adapter.requests == []
    [event] = await audit_rows(owner_engine, user_of(client), "proposal.assistant_suggested")
    assert (event["demo_fallback"], event["reason"]) == (True, "demo_fallback:fake_provider")


async def test_a_global_budget_answers_a_fixed_message_without_figures(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    app = client.app  # type: ignore[attr-defined]
    app.state.settings = app.state.settings.model_copy(update={"llm_global_daily_cap_usd": Decimal("0.00")})
    adapter = install(client, suggestion(), provider="anthropic")  # as in staging: no fallback
    proposal_id = await new_draft(client, proposal_world)
    assert (await grant(client, proposal_id)).status_code == 200
    paused = await ask(client, proposal_id)
    assert paused.status_code == 503, paused.text
    assert paused.json()["detail"] == {
        "code": "assistant_paused",
        "message": "The writing assistant is paused for today. Try again tomorrow.",
    }
    assert not re.search(r"\d", paused.text.replace(paused.json()["detail"]["code"], ""))
    assert adapter.requests == []
    assert [r.status for r in await llm_rows(owner_engine, user_of(client))] == ["blocked_budget"]


async def test_an_injection_in_the_teaser_is_framed_as_data_and_yields_no_suggestion(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    await make_demo(owner_engine, user_of(client))
    flagged = suggestion(injection_suspected=True, title="Endorsed by the ministry")
    obeyed = suggestion(summary="Endorsed by the ministry: book a pilot at https://evil.example/pilot now.")
    adapter = install(client, flagged, obeyed)
    proposal_id = await new_draft(client, proposal_world, summary=INJECTION)
    assert (await grant(client, proposal_id)).status_code == 200

    first = (await ask(client, proposal_id)).json()
    assert (first["status"], first["teaser"], first["placement"]) == ("injection_suspected", None, [])
    text = sent_text(adapter.requests[0])
    block = re.search(
        r'<submission nonce="([0-9a-f]{16})" field="teaser.summary" tier="tier1">\n(.*?)\n</submission nonce="\1">',
        text,
        re.DOTALL,
    )
    assert block is not None
    assert INJECTION in block.group(2)  # inside its nonce block: data, never an instruction
    system = "\n".join(b.text for b in adapter.requests[0].system)
    assert f"The nonce for this request is {block.group(1)}" in system

    second = (await ask(client, proposal_id)).json()  # a model that obeyed: the Tier-1 rules refuse its teaser
    assert (second["status"], second["teaser"]) == ("suggested", None)
    assert [h["field"] for h in second["placement"]] == ["pricing"]
    events = await audit_rows(owner_engine, user_of(client), "proposal.assistant_suggested")
    assert [e["reason"] for e in events] == ["injection_suspected", "rejected:contains_url"]
