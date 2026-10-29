"""Request and response bodies of the organisation's Team page (REQ-TEN-02; docs/platform/tasks/P28.md track C).

Names carry an ``Org``/``Niche``/``Escalation`` prefix: ``TeamOut``, ``TeamMemberOut`` and ``InvitationOut`` are already
the names of P27's team sheet and P22's team-up invitations in the OpenAPI document.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from bridge.models.enums import OrgRole

MAX_INVITE_ROLES = len(OrgRole)
MAX_NICHE_DEFAULTS = 100


class OrgTeamMember(BaseModel):
    """An active member. ``email`` only for an owner or admin reading (else null). The repository models no person's
    own organisation-side verification (E0/E1/E2 are the organisation's levels), so no verification field is sent."""

    user_id: UUID
    name: str
    email: str | None
    roles: list[OrgRole]
    joined_at: datetime


class OrgInvitation(BaseModel):
    """An open invitation (neither accepted nor revoked); ``expired`` on the shared clock (resend it to renew)."""

    id: UUID
    email: str
    roles: list[OrgRole]
    created_at: datetime
    expires_at: datetime
    expired: bool
    invited_by_name: str


class NicheDefault(BaseModel):
    niche_slug: str
    niche_name: str
    user_id: UUID
    name: str


class EscalationContact(BaseModel):
    user_id: UUID
    name: str


class OrgTeam(BaseModel):
    """The Team page: ``invitations`` is null for a member who is neither an owner nor an admin."""

    members: list[OrgTeamMember]
    invitations: list[OrgInvitation] | None
    niche_defaults: list[NicheDefault]
    escalation_contact: EscalationContact | None


class OrgInvitationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=254)
    roles: list[OrgRole] = Field(min_length=1, max_length=MAX_INVITE_ROLES)


class NicheDefaultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    niche_slug: str = Field(min_length=1, max_length=80)
    user_id: UUID


class NicheDefaultsIn(BaseModel):
    """The whole set: niches left out lose their default."""

    model_config = ConfigDict(extra="forbid")

    items: list[NicheDefaultIn] = Field(max_length=MAX_NICHE_DEFAULTS)


class EscalationContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None


class InvitationPreview(BaseModel):
    """What an invitation link shows before sign-in: the organisation's name and the roles, nothing else."""

    org_name: str
    roles: list[OrgRole]


class InvitationAccepted(BaseModel):
    org_id: UUID
    org_name: str
    roles: list[OrgRole]
