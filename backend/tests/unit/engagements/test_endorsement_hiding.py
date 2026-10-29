"""P10 review MAJOR 1, round-2 MINOR 5 (F04): until the developer is named to the organisation, an endorsement by the
developer names the pseudonymous handle and no user id (``history._endorsement``). The API cannot reach it today (the
developer endorses no stage before ``INTEREST_CONFIRMED``, where the name is revealed), so a unit test holds the rule
for a later stage that may be endorsed earlier."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from bridge.engagements.history import _endorsement
from bridge.engagements.models import EngagementEndorsement
from bridge.ids import uuid7
from bridge.models.enums import EndorsementMethod, EngagementActorRole, EngagementParty, EngagementState


def endorsement(user_id: UUID | None, party: EngagementParty = EngagementParty.DEVELOPER) -> EngagementEndorsement:
    role = EngagementActorRole.DEVELOPER if party is EngagementParty.DEVELOPER else EngagementActorRole.REVIEWER
    return EngagementEndorsement(
        id=uuid7(),
        engagement_id=uuid7(),
        stage=EngagementState.CONTACT_MADE,
        stage_round=1,
        milestone_id=None,
        party=party,
        user_id=user_id,
        role=role if user_id is not None else EngagementActorRole.SYSTEM,
        method=EndorsementMethod.TOTP if user_id is not None else EndorsementMethod.AUTO,
        endorsed_at=datetime(2026, 9, 30, 9, 0, tzinfo=UTC),
    )


def test_the_hidden_developer_is_named_by_the_handle_and_no_id() -> None:
    developer = uuid7()
    out = _endorsement(endorsement(developer), {developer: "dev-handle"}, hidden=developer)
    assert (out.user_id, out.name, out.party) == (None, "dev-handle", EngagementParty.DEVELOPER)


def test_everyone_else_keeps_their_id() -> None:
    developer, reviewer = uuid7(), uuid7()
    names = {developer: "Amina Wanjiru", reviewer: "Rita Njeri"}
    by_reviewer = _endorsement(endorsement(reviewer, EngagementParty.ORG), names, hidden=developer)
    assert (by_reviewer.user_id, by_reviewer.name) == (reviewer, "Rita Njeri")
    named = _endorsement(endorsement(developer), names)  # the developer is named: nothing hidden
    assert (named.user_id, named.name) == (developer, "Amina Wanjiru")
    automatic = _endorsement(endorsement(None), names, hidden=developer)  # a job's endorsement names nobody
    assert (automatic.user_id, automatic.name) == (None, None)
