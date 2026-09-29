"""The two seams of a delivered tag (P4, REQ-PROP-03): what happens when a Pitch reaches a verified (E2) organisation
beyond the tag itself. Each is owned by a parallel task and plugged in here, so the Pitch code never changes:

- ``open_engagement``: the ``SUBMITTED`` engagement of the tag (docs/spec/06 6.3, 6.9). **P5** (the tracker,
  ``feat/REQ-ENG-02-tracker``) provides ``open_engagement_for_tag``, which opens it through the state machine (its
  deadline from ``policy.yaml``). Until P5 merges, ``interim_open_engagement`` below inserts the row the way revision
  0003 allows (the database writes the genesis event); P5 replaces it in ``default_hooks`` and deletes it.
- ``grant_on_tag``: the owner's Tier-2 policy applied to the organisation (docs/spec/06 6.1, "auto-grant to orgs I
  tagged"). **P3** (``feat/REQ-SEC-01-tier2-access``) provides ``bridge.proposals.grants.grant_on_tag`` with exactly
  this signature; until P3 merges, ``grant_nothing_until_p3`` grants nothing (fail closed: no Tier-2 access is ever
  opened by a placeholder). P3 replaces it in ``default_hooks`` and deletes it.

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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.ids import uuid7


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


_ENGAGE = text(
    "INSERT INTO engagements (id, proposal_id, org_id, developer_id, version_id, origin, state)"
    " VALUES (:id, :proposal, :org, :developer, :version, 'tagged', 'SUBMITTED')"
)


async def interim_open_engagement(
    db: AsyncSession, *, developer_id: UUID, proposal_id: UUID, version_id: UUID, org_id: UUID, tag_id: UUID
) -> UUID:
    """INTERIM, replaced by P5's ``open_engagement_for_tag``: insert the ``SUBMITTED`` engagement (origin ``tagged``).
    Revision 0003's INSERT policy admits it only for the developer's open delivered tag of this proposal and
    organisation; its genesis event (seq 1, ``create``) is the database's. No deadline is set (P5's, from
    ``policy.yaml``)."""
    engagement_id = uuid7()
    await db.execute(
        _ENGAGE,
        {"id": engagement_id, "proposal": proposal_id, "org": org_id, "developer": developer_id, "version": version_id},
    )
    return engagement_id


async def grant_nothing_until_p3(db: AsyncSession, *, owner_id: UUID, proposal_id: UUID, org_id: UUID) -> UUID | None:
    """INTERIM, replaced by P3's ``bridge.proposals.grants.grant_on_tag``: no grant (fail closed)."""
    return None


def default_hooks() -> TagHooks:
    return TagHooks(open_engagement=interim_open_engagement, grant_on_tag=grant_nothing_until_p3)


def get_tag_hooks(request: Request) -> TagHooks:
    hooks: TagHooks | None = getattr(request.app.state, "tag_hooks", None)
    if hooks is None:
        hooks = default_hooks()
        request.app.state.tag_hooks = hooks
    return hooks


TagHooksDep = Annotated[TagHooks, Depends(get_tag_hooks)]
