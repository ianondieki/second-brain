"""AC-DIR-1 (REQ-DIR-04, REQ-NOT-01; docs/spec/06 6.2): tagging an E0 organisation creates a ``held_unclaimed`` tag
and sends zero emails, asserted against the mail sink (the fake provider's outbox) and the delivery ledger. The same
holds for an E1 organisation (``held_pending_verification``), whose members see only a count. Held tags open no
engagement and no grant, write no in-app row, and the prototype sends no invitation either.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.proposals.helpers import Developers, ProposalWorld, rows, user_of
from tests.integration.proposals.pitch_helpers import (
    Members,
    PitchOrgs,
    RecordingHooks,
    counts,
    install,
    org_mail,
    pitch,
    pitchable,
    sent,
)

E0_MESSAGE = (
    "{org} isn't on the platform yet. Your proposal is saved and they'll see it if they join and verify."
    " We don't email them on your behalf."
)


async def test_an_e0_tag_is_held_and_sends_nothing(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, owner_engine: AsyncEngine
) -> None:
    dev, proposal_id = await pitchable(developers, proposal_world)
    hooks = install(dev, RecordingHooks())
    response = await pitch(dev, proposal_id, pitch_orgs.telkom)
    assert response.status_code == 201, response.text
    result = response.json()
    [tag] = result["tags"]
    assert (tag["status"], tag["open"], tag["engagement_id"]) == ("held_unclaimed", True, None)
    assert tag["message"] == E0_MESSAGE.format(org=pitch_orgs.telkom.name)
    assert tag["org"]["badge"]["level"] == "e0"
    assert (result["sent_count"], result["saved_count"], result["email_sent"]) == (0, 1, False)
    # Zero emails: nothing reached the mail sink, nothing is in the ledger, and nothing else was written to anyone.
    assert sent(dev) == []
    assert await counts(owner_engine, user_of(dev)) == {
        "tags": 1,
        "engagements": 0,
        "deliveries": 0,
        "in_app": 0,
        "pitched": 1,
    }
    assert await org_mail(owner_engine, [pitch_orgs.telkom]) == 0
    assert hooks.engagements == []
    assert hooks.grants == []
    assert (
        await rows(owner_engine, "SELECT id FROM directory_invitations WHERE org_id = :o", o=pitch_orgs.telkom.id) == []
    )


async def test_an_e1_tag_is_held_and_its_members_see_only_a_count(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    owner_engine: AsyncEngine,
    member_client: Members,
) -> None:
    dev, proposal_id = await pitchable(developers, proposal_world)
    response = await pitch(dev, proposal_id, pitch_orgs.claimed, pitch_orgs.telkom)
    assert response.status_code == 201, response.text
    assert [t["status"] for t in response.json()["tags"]] == ["held_pending_verification", "held_unclaimed"]
    assert sent(dev) == []
    assert (await counts(owner_engine, user_of(dev)))["deliveries"] == 0
    assert await org_mail(owner_engine, [pitch_orgs.claimed, pitch_orgs.telkom]) == 0
    owner = await member_client(pitch_orgs.claimed.member)  # type: ignore[arg-type]
    inbox = await owner.get(f"/api/orgs/{pitch_orgs.claimed.id}/inbox")
    assert inbox.status_code == 200, inbox.text
    assert (inbox.json()["items"], inbox.json()["held_count"]) == ([], 1)
    assert proposal_id not in inbox.text  # the count only: not the proposal, its title or the developer
    assert proposal_world.niche_label not in inbox.text
