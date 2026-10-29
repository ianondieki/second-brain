"""The two seams of a delivered tag (P4, REQ-PROP-03): what happens when a Pitch reaches a verified (E2) organisation
beyond the tag itself. Each is owned by a parallel task and plugged in here, so the Pitch code never changes:

- ``open_engagement``: the ``SUBMITTED`` engagement of the tag (docs/spec/06 6.3, 6.9), opened by P5's
  ``bridge.engagements.commands.open_engagement_for_tag`` (its deadline from ``policy.yaml``; the database writes the
  genesis event) through the adapter below: its ``OpenRefused`` is the Pitch's 409 ``tag_conflict`` (the Pitch's own
  checks run first, so a refusal here is a lost race or a change between them).
- ``grant_on_tag``: the owner's Tier-2 policy applied to the organisation (docs/spec/06 6.1, "auto-grant to orgs I
  tagged"): P3's ``bridge.proposals.grants.grant_on_tag`` (an active ``auto_tagged`` grant under the default policy,
  none under ``manual``). A grant opens nothing on its own: ``can_view_tier2`` still needs every other condition,
  ``FEATURE_TIER2_ENABLED`` included. Held tags never reach this hook, so they grant nothing.

Contract (both): called in the developer's request and transaction, tenant bound to the developer, right after the
``delivered`` tag row is inserted (open, for an E2 organisation that is neither suspended nor delisted, on the
proposal's current registered version, published and clear, and the developer is not a member of the organisation);
first ``open_engagement``, then ``grant_on_tag``. Neither commits. An exception rolls the whole Pitch back (no tag,
no engagement, no grant, no email). Tests install their own ``TagHooks`` on ``app.state.tag_hooks``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.engagements import commands
from bridge.errors import ApiError
from bridge.proposals import grants


class OpenEngagement(Protocol):
    async def __call__(
        self,
        db: AsyncSession,
        *,
        developer_id: UUID,
        proposal_id: UUID,
        version_id: UUID,
        org_id: UUID,
        tag_id: UUID,
    ) -> UUID:
        """Open the ``SUBMITTED`` engagement of the tag and return its id."""
        ...


class GrantOnTag(Protocol):
    async def __call__(self, db: AsyncSession, *, owner_id: UUID, proposal_id: UUID, org_id: UUID) -> UUID | None:
        """Apply the owner's Tier-2 policy to the organisation: the live grant's id, or None (no grant)."""
        ...


@dataclass(frozen=True, slots=True)
class TagHooks:
    open_engagement: OpenEngagement
    grant_on_tag: GrantOnTag


async def open_engagement(
    db: AsyncSession, *, developer_id: UUID, proposal_id: UUID, version_id: UUID, org_id: UUID, tag_id: UUID
) -> UUID:
    """P5's ``open_engagement_for_tag`` as the ``OpenEngagement`` hook (the tag names the developer, proposal and
    organisation; the engagement takes the proposal's current registered version)."""
    try:
        return (await commands.open_engagement_for_tag(db, tag_id)).id
    except commands.OpenRefused as exc:
        raise ApiError(409, "tag_conflict", exc.message) from exc


def default_hooks() -> TagHooks:
    return TagHooks(open_engagement=open_engagement, grant_on_tag=grants.grant_on_tag)


def get_tag_hooks(request: Request) -> TagHooks:
    hooks: TagHooks | None = getattr(request.app.state, "tag_hooks", None)
    if hooks is None:
        hooks = default_hooks()
        request.app.state.tag_hooks = hooks
    return hooks


TagHooksDep = Annotated[TagHooks, Depends(get_tag_hooks)]
