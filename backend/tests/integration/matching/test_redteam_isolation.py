"""AC-SCOUT-3 (REQ-SCOUT-02; D-43 (a)): a red-team scan with Tier-2 data, an older and a newer (draft) version and
another organisation's scout present. Every request the scout's model receives is captured: no Tier-2 marker, no text
of a version other than the current registered one, and nothing of the other organisation ever appears in the
prompt, in the ledger, in the matches or in the digest; the current teaser does (the positive control)."""

from __future__ import annotations

import json
from dataclasses import asdict
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.llm.fakes import FakeLLMClient
from bridge.matching.rationale import ScoutFit
from bridge.matching.scan import clock_now, run_periodic
from tests.integration.matching.scout_world import add_scout, build, deps, matches, rows
from tests.integration.proposals.helpers import (
    TIER2_MARKERS,
    Developers,
    ProposalWorld,
    create,
    draft_body,
    publish,
)

OLD_MARKER = "OLDVERSION-MARKER"
DRAFT_MARKER = "DRAFTVERSION-MARKER"
OTHER_MARKER = "OTHERTENANT-MARKER"


def wire(request: object) -> str:
    """Everything a request carries to the provider, as text."""
    return json.dumps(asdict(request), default=str)  # type: ignore[call-overload]


async def test_the_scout_prompt_holds_tier1_of_the_current_version_only(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    unique = f"redteam{uuid4().hex[:8]}"
    owner = await developers()
    body = draft_body(proposal_world, title=f"Cooler alerts {OLD_MARKER}", summary=f"Alerts for {unique} farms.")
    created = await create(owner, body)  # its confidential part carries the TIER2-SECRET markers
    pid = created["id"]
    assert (await publish(owner, pid)).status_code == 200
    renamed = await owner.patch(f"/api/me/proposals/{pid}", json={"teaser": {"title": "Cooler alerts v2"}})
    assert renamed.status_code == 200
    second = await publish(owner, pid)
    assert second.status_code == 200
    assert second.json()["version_no"] == 2
    draft = await owner.patch(f"/api/me/proposals/{pid}", json={"teaser": {"title": f"Cooler {DRAFT_MARKER}"}})
    assert draft.status_code == 200  # a newer draft, not published

    world = await build(owner_engine)
    scout = await add_scout(owner_engine, world.org, [proposal_world.niche_id], include_keywords=[unique])
    await add_scout(
        owner_engine, world.other, [proposal_world.niche_id], include_keywords=[unique, OTHER_MARKER.lower()]
    )
    reply = ScoutFit(injection_suspected=False, fit=70, rationale="Alerts for dairy farms that match the scout.")
    llm = FakeLLMClient([reply] * 4)
    scan_deps, email = deps(app_engine, llm=llm)
    await run_periodic(scan_deps, now=await clock_now(scan_deps.factory), force=True)

    pairs = list(zip(llm.ledger.entries, llm.requests, strict=True))  # one attempt per call: valid replies
    ours = [wire(r) for entry, r in pairs if entry.org_id == world.org.id]
    theirs = [wire(r) for entry, r in pairs if entry.org_id == world.other.id]
    assert ours, "the model was asked for our scout (the positive control)"
    assert theirs, "and for the other organisation's scout, in a call of its own"
    assert all("Cooler alerts v2" in text for text in ours)  # the current version's teaser
    captured = {
        "prompts": "\n".join(wire(r) for r in llm.requests),
        "ledger": repr(llm.ledger.entries) + json.dumps([e.inputs for e in llm.ledger.entries], default=str),
        "matches": repr(await matches(owner_engine, scout)),
        "digest": "\n".join(m.text + (m.html or "") for m in email.outbox),
    }
    for where, text in captured.items():
        for marker in (*TIER2_MARKERS, OLD_MARKER, DRAFT_MARKER):
            assert marker not in text, f"{marker} in the scout's {where}"
    for text in ours:  # one tenant per run: the other organisation's scout never reaches our prompt
        assert OTHER_MARKER.lower() not in text.lower()
    assert all(OTHER_MARKER.lower() in text.lower() for text in theirs)
    [match] = [m for m in await matches(owner_engine, scout) if str(m.proposal_id) == pid]
    [current] = await rows(owner_engine, "SELECT current_version_id FROM proposals WHERE id = :p", p=pid)
    assert match.version_id == current.current_version_id
