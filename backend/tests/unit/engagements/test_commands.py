"""REQ-ENG-01: the command runner's own checks, apart from the database (the integration suite runs the rest).

The terms of an agreement version stay within policy.yaml; a command's body is required where it has one; the
step-up is refused without TOTP; the document a party signs is the stage's own; a database refusal maps to
404/403/409 and anything else is re-raised.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy.exc import DBAPIError

from bridge.engagements import commands, service
from bridge.engagements import state_machine as sm
from bridge.engagements.policy import get_policy
from bridge.errors import ApiError
from bridge.models.enums import (
    EndorsementMethod,
    EngagementActorRole,
    EngagementParty,
    EngagementState,
    IpTerms,
    PaymentMethod,
    SignatureDocumentKind,
    StepUpMethod,
)

NOW = datetime(2026, 10, 5, 9, tzinfo=UTC)
TODAY = date(2026, 10, 5)
ID = UUID("01900000-0000-7000-8000-00000000000c")


def step(command: sm.Command = sm.Command.PROPOSE_TERMS, **changes: Any) -> commands.Step:
    decision = sm.Decision(
        command=command,
        party=EngagementParty.DEVELOPER,
        role=EngagementActorRole.DEVELOPER,
        from_state=EngagementState.NEGOTIATION,
        to_state=EngagementState.NEGOTIATION,
        end_reason=None,
        endorse=None,
        step_up=False,
        renews_deadline=False,
        notice=None,
    )
    values: dict[str, Any] = {
        "db": None,
        "settings": None,
        "policy": get_policy(),
        "party": None,
        "engagement": None,
        "decision": decision,
        "loaded": service.Loaded(sm.Facts(), 1),
        "inputs": commands.Inputs(),
        "meta": commands.RequestMeta(),
        "now": NOW,
        "holidays": frozenset(),
        "step_up": None,
    }
    values.update(changes)
    return commands.Step(**values)


def milestone(**changes: Any) -> commands.MilestoneInput:
    values: dict[str, Any] = {
        "deliverable": "Pilot",
        "amount_kes_minor": 100,
        "due_date": TODAY + timedelta(days=10),
        "review_window_bd": 5,
    }
    values.update(changes)
    return commands.MilestoneInput(**values)


def terms(**changes: Any) -> commands.TermsInput:
    values: dict[str, Any] = {
        "ip_terms": IpTerms.REVENUE_SHARE,
        "deemed_acceptance_days": 0,
        "milestones": (milestone(),),
    }
    values.update(changes)
    return commands.TermsInput(**values)


def test_terms_stay_within_the_policy() -> None:
    commands._check_terms(terms(), step())
    commands._check_terms(terms(exclusivity="Kenya only, 90 days", deemed_acceptance_days=90), step())
    policy = get_policy()
    for wrong in (
        terms(milestones=()),
        terms(milestones=(milestone(),) * (policy.max_milestones + 1)),
        terms(deemed_acceptance_days=policy.deemed_acceptance_days_max + 1),
        terms(exclusivity="   "),
        terms(milestones=(milestone(review_window_bd=policy.review_window_bd_max + 1),)),
        terms(milestones=(milestone(due_date=TODAY - timedelta(days=1)),)),
    ):
        with pytest.raises(sm.Invalid):
            commands._check_terms(wrong, step())


@pytest.mark.parametrize(
    ("command", "effect"),
    [
        (sm.Command.DECLINE, commands._decline),
        (sm.Command.APPROVE, commands._approve),
        (sm.Command.PROPOSE_TERMS, commands._propose_terms),
        (sm.Command.RECORD_PAYMENT, commands._record_payment),
    ],
)
async def test_a_command_with_a_body_needs_it(command: sm.Command, effect: commands.Effect) -> None:
    with pytest.raises(sm.Invalid):
        await effect(step(command))


async def test_a_confirmation_needs_the_amount_received() -> None:
    @dataclass
    class Row:
        amount_kes_minor: int = 100

    loaded = service.Loaded(sm.Facts(), 1, final_payment=cast(Any, Row()))
    with pytest.raises(sm.Invalid):
        await commands._confirm_payment(step(sm.Command.CONFIRM_PAYMENT, loaded=loaded))


async def test_a_payment_is_not_dated_in_the_future() -> None:
    payment = commands.PaymentInput(100, PaymentMethod.MPESA, TODAY + timedelta(days=1))
    with pytest.raises(sm.Invalid, match="future"):
        await commands._record_payment(step(sm.Command.RECORD_PAYMENT, inputs=commands.Inputs(payment=payment)))


def test_the_document_to_sign_is_the_stages_own() -> None:
    with pytest.raises(sm.Conflict) as agreement:
        commands._document_to_sign(step(sm.Command.SIGN_AGREEMENT))
    assert agreement.value.code == "no_final_agreement"
    for command in (sm.Command.SIGN_NDA, sm.Command.SIGN_CERTIFICATE):
        with pytest.raises(sm.Conflict) as missing:
            commands._document_to_sign(step(command))
        assert missing.value.code == "no_document"
    nda = service.DocumentRef(SignatureDocumentKind.MUTUAL_NDA, ID, bytes(32))
    found = commands._document_to_sign(step(sm.Command.SIGN_NDA, loaded=service.Loaded(sm.Facts(), 1, nda=nda)))
    assert found == (SignatureDocumentKind.MUTUAL_NDA, ID, bytes(32))


async def test_accepting_a_delivery_needs_the_signed_agreement() -> None:
    with pytest.raises(sm.Conflict, match="signed agreement"):
        await commands._accept_delivery(step(sm.Command.ACCEPT_DELIVERY))


def test_the_step_up_needs_totp_enrolled() -> None:
    @dataclass
    class User:
        totp_enabled_at: datetime | None = None

    @dataclass
    class Live:
        user: User

    party = service.Party(ID, cast(Any, Live(User())), sm.Actor(EngagementParty.DEVELOPER, sm.DEVELOPER), ID)
    with pytest.raises(ApiError) as refused:
        commands.verified_step_up(party, cast(Any, None))
    assert refused.value.status_code == 403
    assert cast(dict[str, Any], refused.value.detail)["code"] == "mfa_enrolment_required"


def test_a_signatures_ip_is_an_address_or_nothing() -> None:
    assert commands._ip("198.51.100.7") == "198.51.100.7"
    assert commands._ip("2001:db8::1") == "2001:db8::1"
    assert commands._ip("unknown") is None
    assert commands._ip(None) is None


class _Diag:
    def __init__(self, message: str) -> None:
        self.message_primary = message


class _Orig(Exception):
    def __init__(self, sqlstate: str, message: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate
        self.diag = _Diag(message)


def refusal(sqlstate: str, message: str = "refused") -> DBAPIError:
    return DBAPIError("statement", {}, _Orig(sqlstate, message))


def test_database_refusals_map_to_404_403_and_409() -> None:
    invisible = service.db_refusal(refusal("42501", "no engagement of the caller's with that id"))
    assert invisible is not None
    assert invisible.status_code == 404
    rls = service.db_refusal(refusal("42501", "new row violates row-level security policy"))
    assert rls is not None
    assert rls.status_code == 403
    for sqlstate in ("23514", "23505", "40001", "40P01"):
        conflict = service.db_refusal(refusal(sqlstate))
        assert conflict is not None
        assert conflict.status_code == 409
    assert service.db_refusal(refusal("42601")) is None  # a bug: re-raised
    error = service.api_error(sm.Conflict("illegal_transition", "no"))
    assert (error.status_code, cast(dict[str, Any], error.detail)["code"]) == (409, "illegal_transition")


def test_every_endorsing_and_signing_row_needs_the_step_up() -> None:
    """Security review P5, MINOR 3: the method recorded for an endorsement or signature is always the step-up this
    request verified, so every row that endorses or signs must require it."""
    for command, row in sm.TABLE.items():
        if row.endorse is not None or command in sm.SIGNING_COMMANDS:
            assert row.step_up, command


class _Db:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None


@dataclass
class _Engagement:
    id: UUID = ID


async def test_the_endorsement_method_is_the_verified_step_up() -> None:
    party = service.Party(ID, cast(Any, None), sm.Actor(EngagementParty.DEVELOPER, sm.DEVELOPER), ID)
    db = _Db()
    for method, expected in (
        (StepUpMethod.TOTP, EndorsementMethod.TOTP),
        (StepUpMethod.PASSKEY, EndorsementMethod.PASSKEY),
    ):
        verified = step(
            sm.Command.CONFIRM_CONTACT, db=db, party=cast(Any, party), engagement=_Engagement(), step_up=method
        )
        verified.party = cast(Any, _PartyWithUser(party))
        await commands._endorse(verified, ID, EngagementState.CONTACT_MADE)
        assert db.added[-1].method is expected  # type: ignore[attr-defined]
    unverified = step(
        sm.Command.CONFIRM_CONTACT, db=db, party=cast(Any, _PartyWithUser(party)), engagement=_Engagement()
    )
    with pytest.raises(RuntimeError, match="step-up"):
        await commands._endorse(unverified, ID, EngagementState.CONTACT_MADE)


class _PartyWithUser:
    """A Party whose user id needs no session."""

    def __init__(self, party: service.Party) -> None:
        self.actor = party.actor
        self.user_id = ID
