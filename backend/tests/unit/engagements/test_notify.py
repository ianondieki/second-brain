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
R, S = EngagementActorRole, EngagementState


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
    portal = "dev" if told is DEV else "org"  # each party opens the engagement in its own portal
    assert notice.link == f"/{portal}/engagements/{ENGAGEMENT}"
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
    assert notice.link == f"/dev/engagements/{ENGAGEMENT}"
    assert notify.is_interest(genesis)
    for role in (EngagementActorRole.DEVELOPER, EngagementActorRole.SYSTEM):  # nobody opens stage 0 but the org
        assert not notify.is_interest(event("create", role, EngagementState.ORG_INTEREST))
    assert not notify.is_interest(event("create", EngagementActorRole.SIGNATORY, EngagementState.SUBMITTED))


def side(
    command: str, role: EngagementActorRole, from_state: EngagementState, to_state: EngagementState, **extra: Any
) -> EngagementEvent:
    built = event(command, role, to_state, **extra)
    built.from_state = from_state
    return built


@pytest.mark.parametrize(
    ("command", "role", "from_state", "to_state", "told", "kind", "words"),
    [
        ("request_info", R.REVIEWER, S.UNDER_REVIEW, S.INFO_REQUESTED, DEV, "engagement.n03", "asked you a question"),
        ("answer_info", R.DEVELOPER, S.INFO_REQUESTED, S.UNDER_REVIEW, ORG, "engagement.n03", "answered your question"),
        (
            "cancel_request",
            R.REVIEWER,
            S.INFO_REQUESTED,
            S.UNDER_REVIEW,
            DEV,
            "engagement.n03",
            "withdrew its question",
        ),
        ("pause", R.DEVELOPER, S.NEGOTIATION, S.ON_HOLD, ORG, "engagement.n20", "on hold until 20 Oct 2026"),
        ("pause", R.OWNER, S.NEGOTIATION, S.ON_HOLD, DEV, "engagement.n20", "Telco A put"),
        ("resume", R.SIGNATORY, S.ON_HOLD, S.NEGOTIATION, DEV, "engagement.n20", "resumed"),
        ("resume", R.DEVELOPER, S.ON_HOLD, S.NEGOTIATION, ORG, "engagement.n20", "The developer resumed"),
    ],
)
def test_a_side_state_tells_the_other_party_and_goes_by_email(
    command: str,
    role: EngagementActorRole,
    from_state: EngagementState,
    to_state: EngagementState,
    told: EngagementParty,
    kind: str,
    words: str,
) -> None:
    """N03 (information requested and answered), N20 (on hold, resumed early): the other party, in-app and by the
    status email; the note's text is never in the notice."""
    built = side(command, role, from_state, to_state, payload={"resume_at": "2026-10-20", "paused_due_on": "2026-10-9"})
    composed = notify.compose(built, "Telco A", "Cold-chain alerts")
    assert composed is not None
    party, notice = composed
    assert (party, notice.kind, notice.title) == (told, kind, sm.STAGE_LABELS[to_state])
    assert words in notice.body
    assert '"Cold-chain alerts"' in notice.body
    assert notify.emailed(built)
    assert notify.compose_system(built, "Telco A", "Cold-chain alerts") == []  # a party's event is not the system's


def test_a_hold_without_its_date_still_reads() -> None:
    built = side("pause", R.DEVELOPER, S.NEGOTIATION, S.ON_HOLD)
    composed = notify.compose(built, "Telco A", "T")
    assert composed is not None
    assert "until its resume date" in composed[1].body


@pytest.mark.parametrize(
    ("from_state", "reason", "kind", "words"),
    [
        (S.SUBMITTED, EngagementEndReason.NO_REVIEW, "engagement.n01", "nobody started the review in time"),
        (S.UNDER_REVIEW, EngagementEndReason.NO_DECISION, "engagement.n03", "no decision was made in time"),
        (S.INTEREST_CONFIRMED, EngagementEndReason.CONTACT_NOT_MADE, "engagement.n05", "first contact was not made"),
        (S.ORG_INTEREST, EngagementEndReason.NO_DEV_RESPONSE, "engagement.n17", "the interest was not answered"),
        (S.INFO_REQUESTED, EngagementEndReason.NO_DEV_RESPONSE, "engagement.n03", "the organisation's question was"),
    ],
)
def test_an_expiry_tells_both_parties_why(
    from_state: EngagementState, reason: EngagementEndReason, kind: str, words: str
) -> None:
    """The system's expiry is told to both parties under the matrix row of the stage it ended, with the reason."""
    built = side("expire", R.SYSTEM, from_state, S.EXPIRED, end_reason=reason)
    assert notify.compose(built, "Telco A", "Cold-chain alerts") is None  # never as one party's act
    told = notify.compose_system(built, "Telco\nA", "Cold-chain alerts")
    assert [(party, notice.kind, notice.title) for party, notice in told] == [
        (DEV, kind, "Expired"),
        (ORG, kind, "Expired"),
    ]
    developer, organisation = (notice for _, notice in told)
    assert developer.body.startswith(f'Your engagement with Telco A on "Cold-chain alerts" expired: {words}')
    assert organisation.body.startswith(f'The engagement on "Cold-chain alerts" expired: {words}')
    assert (developer.link, organisation.link) == (f"/dev/engagements/{ENGAGEMENT}", f"/org/engagements/{ENGAGEMENT}")
    assert notify.emailed(built)


def test_a_hold_resumed_on_its_date_tells_both_parties() -> None:
    built = side("resume", R.SYSTEM, S.ON_HOLD, S.CONTACT_MADE)
    told = notify.compose_system(built, "Telco A", "Cold-chain alerts")
    assert [(party, notice.kind, notice.title) for party, notice in told] == [
        (DEV, "engagement.n20", "First contact"),
        (ORG, "engagement.n20", "First contact"),
    ]
    assert told[0][1].body.startswith('"Cold-chain alerts" is no longer on hold')


def test_other_system_events_and_party_events_tell_nobody_by_email() -> None:
    for built in (
        side("approve", R.SYSTEM, S.UNDER_REVIEW, S.INTEREST_CONFIRMED),  # not the system's
        side("expire", R.SYSTEM, S.NEGOTIATION, S.EXPIRED, end_reason=EngagementEndReason.NO_REVIEW),  # never expires
        side("resume", R.SYSTEM, S.INFO_REQUESTED, S.UNDER_REVIEW),  # a question is only ever answered
        side("expire", R.SYSTEM, S.SUBMITTED, S.EXPIRED),  # no reason
    ):
        assert notify.compose_system(built, "Org", "Title") == []
    genesis = event("create", R.SYSTEM, S.SUBMITTED)
    genesis.from_state = None
    assert notify.compose_system(genesis, "Org", "Title") == []
    assert not notify.emailed(event("start_review", R.REVIEWER, S.UNDER_REVIEW))
