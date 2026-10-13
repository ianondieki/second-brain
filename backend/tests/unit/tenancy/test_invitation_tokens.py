"""REQ-TEN-02 (P28 track C): an invitation link's token and who may grant which roles.

- The token is 32 random bytes in URL-safe base64 (``bridge.auth.crypto.new_token``); only its SHA-256 is stored, and a
  malformed token is refused before any database read (``token_digest`` is None).
- The token is a path segment of ``/api/invitations/{token}`` and ``…/accept``: the access log never shows it.
- Only an owner invites (or resends, or revokes) an owner or a signatory: an admin gets 403 ``protected_role``.
"""

from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Iterator
from typing import cast
from uuid import uuid4

import pytest
from uvicorn.logging import AccessFormatter

from bridge.auth.crypto import new_token
from bridge.auth.sessions import LiveSession
from bridge.errors import ApiError
from bridge.logging import configure_logging, redact_secret_segments
from bridge.models.enums import OrgRole
from bridge.tenancy import invitations
from bridge.tenancy.deps import OrgContext
from bridge.tenancy.team import manages


def org(*roles: OrgRole) -> OrgContext:
    return OrgContext(uuid4(), frozenset(roles), cast(LiveSession, None))


def test_a_new_token_is_well_formed_and_only_its_sha256_is_kept() -> None:
    tokens = {new_token() for _ in range(50)}
    assert len(tokens) == 50  # random
    for token in tokens:
        assert len(token) == invitations.TOKEN_CHARS
        assert invitations.token_digest(token) == hashlib.sha256(token.encode()).digest()


@pytest.mark.parametrize(
    "token",
    [
        "",
        "short",
        "A" * 42,
        "A" * 44,
        "A" * 42 + "=",  # padding
        "A" * 42 + "/",  # standard base64's alphabet, not URL-safe
        "A" * 42 + ".",
        "A" * 21 + " " + "A" * 21,
        "A" * 42 + "\n",
        "Ａ" * 43,  # full-width letters  # noqa: RUF001
    ],
)
def test_a_malformed_token_is_refused_before_the_database(token: str) -> None:
    assert invitations.token_digest(token) is None


def test_addresses_are_compared_trimmed_and_in_lower_case() -> None:
    assert invitations.normalise_email("  Amina.Wanjiru@Example.TEST ") == "amina.wanjiru@example.test"


ACCESS = logging.getLogger("uvicorn.access")


@pytest.fixture
def access_log() -> Iterator[io.StringIO]:
    """What uvicorn's access logger writes, formatted as uvicorn formats it (as ``tests/unit/test_logging.py``)."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    level = ACCESS.level
    ACCESS.addHandler(handler)
    ACCESS.setLevel(logging.INFO)
    yield stream
    ACCESS.removeHandler(handler)
    ACCESS.setLevel(level)


@pytest.mark.parametrize("suffix", ["", "/accept", "/accept?x=1"])
def test_an_invitation_token_never_reaches_the_access_log(access_log: io.StringIO, suffix: str) -> None:
    configure_logging()
    token = new_token()
    ACCESS.info('%s - "%s %s HTTP/%s" %d', "203.0.113.9:50000", "GET", f"/api/invitations/{token}{suffix}", "1.1", 200)
    line = access_log.getvalue()
    assert "/api/invitations/[redacted]" in line
    assert token not in line


@pytest.mark.parametrize("path", ["/api/orgs/x/invitations", "/api/orgs/x/invitations/y/resend", "/api/me/teams"])
def test_the_organisation_s_own_invitation_routes_keep_their_segments(path: str) -> None:
    assert redact_secret_segments(path) == path


@pytest.mark.parametrize("roles", [{OrgRole.OWNER}, {OrgRole.SIGNATORY}, {OrgRole.REVIEWER, OrgRole.SIGNATORY}])
def test_an_admin_never_grants_a_protected_role(roles: set[OrgRole]) -> None:
    with pytest.raises(ApiError) as refused:
        invitations.check_grantable(org(OrgRole.ADMIN), roles)
    assert refused.value.status_code == 403
    assert refused.value.detail["code"] == "protected_role"  # type: ignore[index]
    invitations.check_grantable(org(OrgRole.OWNER), roles)  # an owner grants them


@pytest.mark.parametrize("roles", [{OrgRole.ADMIN}, {OrgRole.REVIEWER, OrgRole.FINANCE}, {OrgRole.VIEWER}])
def test_an_admin_grants_the_unprotected_roles(roles: set[OrgRole]) -> None:
    invitations.check_grantable(org(OrgRole.ADMIN), roles)


def test_owners_and_admins_manage_the_team_and_no_one_else() -> None:
    assert manages(org(OrgRole.OWNER))
    assert manages(org(OrgRole.ADMIN))
    for role in (OrgRole.REVIEWER, OrgRole.SIGNATORY, OrgRole.FINANCE, OrgRole.VIEWER):
        assert not manages(org(role))
