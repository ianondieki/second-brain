"""REQ-NOT-03 (prototype part), REQ-NOT-04: the notification of each event is read from the state machine's table;
the other party is told, in fixed words."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from bridge.engagements import notify
from bridge.engagements import state_machine as sm
from bridge.engagements.models import EngagementEvent
from bridge.models.enums import EngagementActorRole, EngagementEndReason, EngagementParty, EngagementState

ENGAGEMENT = UUID("01900000-0000-7000-8000-00000000000b")
DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG


def event(command: str, role: EngagementActorRole, to_state: EngagementState, **extra: Any) -> EngagementEvent:
    return EngagementEvent(
        engagement_id=ENGAGEMENT,
        command=command,
        actor_role=role,
        from_state=EngagementState.SUBMITTED,
        to_state=to_state,
        end_reason=extra.pop("end_reason", None),
        payload=extra.pop("payload", {}),
    )


def test_every_notifying_row_has_words_for_each_party_that_may_run_it() -> None:
    for command, row in sm.TABLE.items():
        if row.notice is None:
            continue
        for party in row.actors:
            assert (command, party) in notify.SENTENCES, (command, party)
    assert all(sm.TABLE[command].notice for command, _ in notify.SENTENCES)


@pytest.mark.parametrize(
    ("command", "role", "to_state", "told", "kind"),
    [
        ("start_review", EngagementActorRole.REVIEWER, EngagementState.UNDER_REVIEW, DEV, "engagement.n03"),
        ("approve", EngagementActorRole.SIGNATORY, EngagementState.INTEREST_CONFIRMED, DEV, "engagement.n04"),
        ("withdraw", EngagementActorRole.DEVELOPER, EngagementState.WITHDRAWN, ORG, "engagement.withdrawn"),
        ("send_nda", EngagementActorRole.DEVELOPER, EngagementState.NDA_PENDING, ORG, "engagement.n07"),
        ("send_nda", EngagementActorRole.OWNER, EngagementState.NDA_PENDING, DEV, "engagement.n07"),
    ],
)
def test_the_other_party_is_told(
    command: str, role: EngagementActorRole, to_state: EngagementState, told: EngagementParty, kind: str
) -> None:
    composed = notify.compose(event(command, role, to_state), "Telco A", "Cold-chain alerts")
    assert composed is not None
    party, notice = composed
    assert (party, notice.kind) == (told, kind)
    assert notice.title == sm.STAGE_LABELS[to_state]
    assert notice.link == f"/engagements/{ENGAGEMENT}"
    assert '"Cold-chain alerts"' in notice.body


def test_events_without_a_notice_tell_nobody() -> None:
    for command, role in (
        ("create", EngagementActorRole.DEVELOPER),  # the genesis
        ("start_milestone", EngagementActorRole.DEVELOPER),  # a row without a notice
        ("approve", EngagementActorRole.SYSTEM),  # the prototype writes no system events
        ("approve", EngagementActorRole.DEVELOPER),  # no words for a party the row does not allow
    ):
        assert notify.compose(event(command, role, EngagementState.SUBMITTED), "Org", "Title") is None


def test_a_decline_carries_its_reason_attestation_and_text() -> None:
    internal = event(
        "decline",
        EngagementActorRole.REVIEWER,
        EngagementState.DECLINED,
        end_reason=EngagementEndReason.ALREADY_IN_PROGRESS_INTERNALLY,
        payload={"internal_start_date": "2026-05-01", "attested": True},
    )
    composed = notify.compose(internal, "Telco\nA", "T")
    assert composed is not None
    body = composed[1].body
    assert body.startswith('Telco A declined "T". Reason: already solved internally.')
    assert body.endswith("in progress internally since 2026-05-01.")
    other = event(
        "decline", EngagementActorRole.SIGNATORY, EngagementState.DECLINED, end_reason=EngagementEndReason.OTHER
    )
    composed = notify.compose(other, "Telco A", "T", reason_text="We are merging this unit.")
    assert composed is not None
    assert composed[1].body.endswith("Reason: other. Their reason: We are merging this unit.")


def test_an_organisations_interest_tells_the_developer_n17() -> None:
    """REQ-ENG-04: the genesis of an ORG_INTEREST engagement, by an organisation member, is N17 to the developer."""
    genesis = event("create", EngagementActorRole.SIGNATORY, EngagementState.ORG_INTEREST)
    composed = notify.compose(genesis, "Telco A (fixture)", "Cold-chain alerts")
    assert composed is not None
    party, notice = composed
    assert (party, notice.kind, notice.title) == (DEV, "engagement.n17", "Organisation interested")
    assert notice.body == 'Telco A (fixture) is interested in "Cold-chain alerts". Accept or decline on your tracker.'
    assert notice.link == f"/engagements/{ENGAGEMENT}"
    assert notify.is_interest(genesis)
    for role in (EngagementActorRole.DEVELOPER, EngagementActorRole.SYSTEM):  # nobody opens stage 0 but the org
        assert not notify.is_interest(event("create", role, EngagementState.ORG_INTEREST))
    assert not notify.is_interest(event("create", EngagementActorRole.SIGNATORY, EngagementState.SUBMITTED))
