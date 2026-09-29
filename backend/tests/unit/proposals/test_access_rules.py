"""The order of ``can_view_tier2``'s conditions (REQ-REPO-01, REQ-SEC-01; docs/spec/06 6.1): each fact broken on its
own names its own condition, the first failure wins, the owner passes every organisation condition, and the NDA step
is offered only when nothing else is missing. The database half and the routes are covered by
``tests/integration/proposals/test_access.py``."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from bridge.ids import uuid7
from bridge.models.enums import EngagementState, OrgRole, OrgVerification
from bridge.proposals.access import (
    REVEALED_STATES,
    Access,
    Condition,
    Facts,
    GrantState,
    Target,
    email_domain,
    first_failure,
)

TARGET = Target(
    proposal_id=uuid7(),
    version_id=uuid7(),
    owner_id=uuid7(),
    version_no=1,
    cert_id="c3rt1d",
    registered_at=datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
    owner_handle="dev-handle",
    title="Cold-chain alerts",
)
MET = Facts(
    enabled=True,
    target=TARGET,
    roles=frozenset({OrgRole.REVIEWER}),
    verification=OrgVerification.E2,
    verified_domain="Buyer.Example.Test",
    email="rita@buyer.example.test",
    email_verified=True,
    totp_enrolled=True,
    mfa_fresh=True,
    master_terms=True,
    grant=GrantState.LIVE,
    engagement=EngagementState.UNDER_REVIEW,
    nda_acceptance_id=uuid7(),
)
BROKEN: dict[str, tuple[dict[str, Any], Condition]] = {
    "flag_off": ({"enabled": False}, Condition.FEATURE_DISABLED),
    "no_target": ({"target": None}, Condition.PROPOSAL_UNAVAILABLE),
    "not_member": ({"roles": None}, Condition.NOT_MEMBER),
    "org_e1": ({"verification": OrgVerification.E1}, Condition.ORG_NOT_E2),
    "org_suspended": ({"suspended": True}, Condition.ORG_SUSPENDED),
    "role_viewer": ({"roles": frozenset({OrgRole.VIEWER})}, Condition.ROLE),
    "role_owner_only": ({"roles": frozenset({OrgRole.OWNER, OrgRole.FINANCE})}, Condition.ROLE),
    "email_unverified": ({"email_verified": False}, Condition.EMAIL_UNVERIFIED),
    "off_domain": ({"email": "rita@elsewhere.example.test"}, Condition.DOMAIN),
    "subdomain": ({"email": "rita@mail.buyer.example.test"}, Condition.DOMAIN),
    "no_verified_domain": ({"verified_domain": None}, Condition.DOMAIN),
    "no_totp": ({"totp_enrolled": False}, Condition.TOTP),
    "stale_mfa": ({"mfa_fresh": False}, Condition.STEP_UP),
    "no_terms": ({"master_terms": False}, Condition.MASTER_TERMS),
    "no_grant": ({"grant": GrantState.NONE}, Condition.NO_GRANT),
    "revoked": ({"grant": GrantState.REVOKED}, Condition.GRANT_REVOKED),
    "withdrawn": ({"engagement": EngagementState.WITHDRAWN}, Condition.ENGAGEMENT_ENDED),
    "declined": ({"engagement": EngagementState.DECLINED}, Condition.ENGAGEMENT_ENDED),
    "terminated": ({"engagement": EngagementState.TERMINATED}, Condition.ENGAGEMENT_ENDED),
    "no_nda": ({"nda_acceptance_id": None}, Condition.NDA),
}


def test_every_condition_met_opens_tier2() -> None:
    assert first_failure(MET) is None
    assert first_failure(replace(MET, email="RITA@BUYER.EXAMPLE.TEST")) is None  # domains compare like citext


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_each_broken_fact_names_its_condition(case: str) -> None:
    changes, condition = BROKEN[case]
    assert first_failure(replace(MET, **changes)) == condition


def test_the_first_failure_wins_and_the_nda_comes_last() -> None:
    everything_else_missing = replace(MET, master_terms=False, grant=GrantState.NONE, nda_acceptance_id=None)
    assert first_failure(everything_else_missing) == Condition.MASTER_TERMS
    assert first_failure(replace(MET, nda_acceptance_id=None, grant=GrantState.NONE)) == Condition.NO_GRANT
    # Accepting the NDA needs every other condition: the NDA itself is not checked then.
    assert first_failure(replace(MET, nda_acceptance_id=None), check_nda=False) is None
    assert first_failure(replace(MET, grant=GrantState.NONE), check_nda=False) == Condition.NO_GRANT
    assert first_failure(replace(MET, enabled=False, roles=None)) == Condition.FEATURE_DISABLED


def test_the_owner_passes_every_organisation_condition_but_not_the_flag() -> None:
    owner = Facts(enabled=True, target=TARGET, is_owner=True)
    assert first_failure(owner) is None
    assert first_failure(replace(owner, enabled=False)) == Condition.FEATURE_DISABLED
    assert first_failure(replace(owner, target=None)) == Condition.PROPOSAL_UNAVAILABLE


def test_the_owner_is_named_only_once_the_organisation_approved_to_proceed() -> None:
    assert not Access(TARGET, owner=False, engagement=None).reveals_owner
    for state in (EngagementState.SUBMITTED, EngagementState.UNDER_REVIEW, EngagementState.ON_HOLD):
        assert not Access(TARGET, owner=False, engagement=state).reveals_owner
    for state in (EngagementState.INTEREST_CONFIRMED, EngagementState.NDA_SIGNED, EngagementState.CLOSED):
        assert Access(TARGET, owner=False, engagement=state).reveals_owner
    assert EngagementState.ORG_INTEREST not in REVEALED_STATES


def test_email_domain() -> None:
    assert email_domain("a.b@Example.TEST") == "example.test"
    assert email_domain("no-at-sign") == ""
