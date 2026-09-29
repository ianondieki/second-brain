"""REQ-PROP-05, AC-SEC-6: the submission assistant's consent, against PostgreSQL through the API.

The opt-in (``tier2_llm_assistant``) is given per login session from the editor: it checks the wording's version,
writes an audit event on grant and on withdrawal, and ends at sign-out. Without it the suggestions route answers 403
``consent_required`` and nothing reaches any provider (the fake adapter sees no request and ``llm_calls`` has no row,
not even a refused one). Owner only: 404 for anyone else. The owner here is a demo account, so a missing gate would
let the call through to the free slot.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.api import sign_in_as
from tests.integration.proposals.assistant_rig import (
    PATH,
    ask,
    audit_rows,
    grant,
    install,
    llm_rows,
    make_demo,
    new_draft,
    suggestion,
)
from tests.integration.proposals.helpers import Developers, ProposalWorld, publish, rows, user_of


@pytest.mark.parametrize("confidential", [True, False], ids=["with-tier2", "tier1-only"])
async def test_nothing_is_sent_without_the_sessions_consent(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld, confidential: bool
) -> None:
    client = await developers()
    await make_demo(owner_engine, user_of(client))
    adapter = install(client, suggestion())
    proposal_id = await new_draft(client, proposal_world, confidential=confidential)
    refused = await ask(client, proposal_id)
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == {
        "code": "consent_required",
        "message": "Turn on the writing assistant for this sign-in first.",
    }
    assert adapter.requests == []
    assert await llm_rows(owner_engine, user_of(client)) == []  # not even a refused row: nothing was attempted
    assert await audit_rows(owner_engine, user_of(client), "proposal.assistant_suggested") == []


async def test_the_opt_in_lasts_this_session_only_and_ends_at_sign_out(
    developers: Developers, app_engine: AsyncEngine, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    owner = user_of(client)
    await make_demo(owner_engine, owner)
    adapter = install(client, suggestion(), suggestion())
    proposal_id = await new_draft(client, proposal_world)
    granted = await grant(client, proposal_id)
    assert granted.status_code == 200, granted.text
    assert granted.json()["granted"] is True
    assert granted.json()["scope"] == "this_session"
    assert "this sign-in only" in granted.json()["text"]
    assert (await ask(client, proposal_id)).json()["status"] == "suggested"
    assert len(adapter.requests) == 1

    other = await developers(user_id=owner)  # the same person in another browser: another login session
    install(other)
    assert (await other.get(PATH.format(proposal_id) + "/consent")).json()["granted"] is False
    assert (await ask(other, proposal_id)).status_code == 403

    assert (await client.post("/api/auth/logout")).status_code == 204
    await sign_in_as(client, app_engine, owner, mfa_verified=False)
    assert (await client.get(PATH.format(proposal_id) + "/consent")).json()["granted"] is False
    again = await ask(client, proposal_id)
    assert again.status_code == 403
    assert again.json()["detail"]["code"] == "consent_required"
    assert len(adapter.requests) == 1
    sources = await rows(
        owner_engine,
        "SELECT source FROM consents WHERE user_id = :u AND purpose = 'tier2_llm_assistant'",
        u=owner,
    )
    assert [r.source[:8] for r in sources] == ["session:"]


async def test_grant_and_withdrawal_are_audited_and_withdrawal_stops_the_assistant(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    owner = user_of(client)
    await make_demo(owner_engine, owner)
    adapter = install(client, suggestion())
    proposal_id = await new_draft(client, proposal_world)
    version = (await client.get("/api/consents")).json()["version"]
    assert (await grant(client, proposal_id)).status_code == 200
    withdrawn = await client.delete(PATH.format(proposal_id) + "/consent")
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["granted"] is False
    assert (await ask(client, proposal_id)).status_code == 403
    assert adapter.requests == []
    trail = await audit_rows(owner_engine, owner, "consent.changed")
    assert trail == [
        {"tier2_llm_assistant": granted, "scope": "session", "text_version": version, "proposal_id": proposal_id}
        for granted in (True, False)
    ]
    decisions = await rows(
        owner_engine,
        "SELECT granted, text_version FROM consents WHERE user_id = :u ORDER BY created_at, id",
        u=owner,
    )
    assert [tuple(r) for r in decisions] == [(True, version), (False, version)]


async def test_a_stale_wording_is_refused_and_nothing_is_recorded(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    proposal_id = await new_draft(client, proposal_world)
    stale = await client.post(PATH.format(proposal_id) + "/consent", json={"version": "2026-09-25.1"})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "consent_text_changed"
    assert await rows(owner_engine, "SELECT 1 FROM consents WHERE user_id = :u", u=user_of(client)) == []
    assert await audit_rows(owner_engine, user_of(client), "consent.changed") == []


@pytest.mark.parametrize("published", [True, False], ids=["published", "draft"])
async def test_the_assistant_is_the_owners_only(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld, published: bool
) -> None:
    """A stranger who holds a live opt-in of their own (a demo account, so D-37 would not stop a call) gets 404 on
    another developer's proposal, published or not, and nothing reaches the provider. A published teaser is readable
    under RLS, so only the route's owner filter stands between it and the stranger's call (review MAJOR 1)."""
    owner = await developers()
    await make_demo(owner_engine, user_of(owner))
    proposal_id = await new_draft(owner, proposal_world)
    if published:
        assert (await publish(owner, proposal_id)).status_code == 200
    stranger = await developers()
    await make_demo(owner_engine, user_of(stranger))
    adapter = install(stranger, suggestion(), suggestion())
    own_id = await new_draft(stranger, proposal_world)
    assert (await grant(stranger, own_id)).status_code == 200  # the stranger's opt-in is live in this session
    path = PATH.format(proposal_id)
    version = (await stranger.get("/api/consents")).json()["version"]
    for response in (
        await stranger.post(path + "/consent", json={"version": version}),
        await stranger.get(path + "/consent"),
        await stranger.delete(path + "/consent"),
        await ask(stranger, proposal_id),
        await ask(stranger, "01900000-0000-7000-8000-000000000000"),
    ):
        assert response.status_code == 404, response.text
    assert adapter.requests == []
    decisions = await rows(owner_engine, "SELECT granted FROM consents WHERE user_id = :u", u=user_of(stranger))
    assert [r.granted for r in decisions] == [True]  # only the grant from the stranger's own proposal
    assert await audit_rows(owner_engine, user_of(stranger), "proposal.assistant_suggested") == []


async def test_a_deleted_proposal_gets_no_assistant(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    await make_demo(owner_engine, user_of(client))
    adapter = install(client, suggestion())
    proposal_id = await new_draft(client, proposal_world)
    assert (await publish(client, proposal_id)).status_code == 200
    assert (await grant(client, proposal_id)).status_code == 200
    assert (await client.delete(f"/api/me/proposals/{proposal_id}")).status_code == 200  # hidden, record kept
    hidden = await ask(client, proposal_id)
    assert hidden.status_code == 409
    assert hidden.json()["detail"]["code"] == "proposal_hidden"
    assert adapter.requests == []
