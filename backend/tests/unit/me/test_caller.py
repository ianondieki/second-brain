"""REQ-UX-01, REQ-UX-05 (P25-B): who is asking, without a database.

Given an account, when the palette or the calendar asks who it is, then its side is ``GET /api/auth/me``'s (staff,
else a developer profile, else a membership, else a developer); an organisation member's open organisations are the
ones ``org_member`` admits (a role needing two-step sign-in needs it on and given in this session); and their links
name the organisation only when they belong to more than one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from bridge.auth.models import Session, User
from bridge.auth.sessions import LiveSession
from bridge.me import caller
from bridge.models.enums import OrgRole, StaffRole
from bridge.tenancy.models import Organization
from bridge.tenancy.service import MyMembership

NOW = datetime(2026, 10, 8, 9, tzinfo=UTC)
ORG_A, ORG_B = UUID(int=0xA), UUID(int=0xB)


@pytest.mark.parametrize(
    ("staff", "developer", "member", "side"),
    [
        (True, True, True, "staff"),
        (False, True, True, "developer"),
        (False, False, True, "org"),
        (False, False, False, "developer"),
    ],
)
def test_the_side_is_the_one_me_reports(staff: bool, developer: bool, member: bool, side: str) -> None:
    assert caller.side_of(staff=staff, developer=developer, member=member) == side


def test_an_organisation_needing_a_second_factor_is_open_only_with_one() -> None:
    memberships = [(ORG_A, [OrgRole.VIEWER]), (ORG_B, [OrgRole.FINANCE, OrgRole.OWNER])]
    assert caller.open_orgs(memberships, second_factor=False) == (ORG_A,)
    assert caller.open_orgs(memberships, second_factor=True) == (ORG_A, ORG_B)


def live(*, staff: StaffRole | None = None, totp: bool = False, verified: bool = False) -> LiveSession:
    user = User(id=UUID(int=1), email="x@example.test", display_name="X", staff_role=staff)
    user.totp_enabled_at = NOW if totp else None
    row = Session(user_id=user.id, mfa_pending=False)
    row.mfa_verified_at = NOW if verified else None
    return LiveSession(token="t", row=row, user=user)


def membership(org_id: UUID, *roles: OrgRole) -> MyMembership:
    return MyMembership(Organization(id=org_id, legal_name=f"Org {org_id.int}"), list(roles))


def test_a_member_of_one_organisation_gets_plain_links() -> None:
    found = caller.caller_from(live(), [membership(ORG_A, OrgRole.VIEWER)], developer=False)
    assert found == caller.Caller(UUID(int=1), "org", (ORG_A,), several=False)


def test_a_member_of_several_keeps_the_count_even_when_one_is_closed_to_this_session() -> None:
    both = [membership(ORG_A, OrgRole.VIEWER), membership(ORG_B, OrgRole.OWNER)]
    assert caller.caller_from(live(totp=True), both, developer=False) == caller.Caller(
        UUID(int=1), "org", (ORG_A,), several=True
    )
    assert caller.caller_from(live(totp=True, verified=True), both, developer=False).orgs == (ORG_A, ORG_B)
    assert caller.caller_from(live(verified=True), both, developer=False).orgs == (ORG_A,)  # no TOTP on the account


def test_developers_and_staff_carry_no_organisation() -> None:
    owner = [membership(ORG_A, OrgRole.OWNER)]
    assert caller.caller_from(live(totp=True, verified=True), owner, developer=True) == caller.Caller(
        UUID(int=1), "developer"
    )
    assert caller.caller_from(live(staff=StaffRole.ADMIN), owner, developer=False) == caller.Caller(
        UUID(int=1), "staff"
    )
