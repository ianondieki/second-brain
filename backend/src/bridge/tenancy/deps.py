"""Organisation-scoped access (REQ-TEN-01; docs/spec/08 error semantics).

``org_member(*roles)`` resolves ``{org_id}`` from the path: a caller who is not an active member gets **404** (the
organisation's existence is not confirmed); a member lacking the role, or lacking TOTP where the role requires it,
gets **403**. On success the transaction is scoped to that organisation (``app.org_id``) for RLS.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends

from bridge.auth.deps import CurrentSession, Db
from bridge.auth.sessions import LiveSession
from bridge.db import bind_tenant
from bridge.errors import forbidden, not_found
from bridge.models.enums import MFA_REQUIRED_ORG_ROLES, OrgRole
from bridge.tenancy.service import membership_of


@dataclass(frozen=True, slots=True)
class OrgContext:
    org_id: UUID
    roles: frozenset[OrgRole]
    live: LiveSession


def org_member(*required: OrgRole) -> Callable[..., Awaitable[OrgContext]]:
    async def dependency(org_id: UUID, live: CurrentSession, db: Db) -> OrgContext:
        membership = await membership_of(db, org_id, live.user.id)
        if membership is None:
            raise not_found()
        await bind_tenant(db, user_id=live.user.id, org_id=org_id)
        roles = frozenset(OrgRole(r) for r in membership.roles)
        if roles & MFA_REQUIRED_ORG_ROLES:
            if live.user.totp_enabled_at is None:
                raise forbidden("mfa_enrolment_required", "Turn on two-step sign-in to use this organisation.")
            if live.row.mfa_verified_at is None:
                raise forbidden("mfa_required", "Enter the code from your authenticator app.")
        if required and not roles & set(required):
            raise forbidden()
        return OrgContext(org_id, roles, live)

    return dependency


OrgMember = Annotated[OrgContext, Depends(org_member())]
OrgAdmin = Annotated[OrgContext, Depends(org_member(OrgRole.OWNER, OrgRole.ADMIN))]
OrgOwner = Annotated[OrgContext, Depends(org_member(OrgRole.OWNER))]
