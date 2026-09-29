"""The 'Pitch to company' picker (REQ-PROP-03; docs/spec/06 6.3): the directory grouped by niche, as the Companies
page shows it (``bridge.directory.service.list_directory``: the same filters, keywords and cursor), with what a tag
would do for each organisation (E2 ``delivered``, E1 ``held_pending_verification``, E0 ``held_unclaimed``) and
whether the caller can pitch this proposal to it now (the conflict reasons of ``tags.conflicts``), plus the plan cap.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.config import Settings
from bridge.directory import service as directory
from bridge.directory.responsiveness import ResponsivenessSource
from bridge.directory.schemas import NicheRef, OrgCard
from bridge.models.enums import TagStatus
from bridge.proposals import tags
from bridge.proposals.tags import Reason, TagCap

OUTCOME_BY_BADGE: Final = {
    "e2": TagStatus.DELIVERED,
    "e1": TagStatus.HELD_PENDING_VERIFICATION,
    "e0": TagStatus.HELD_UNCLAIMED,
}


class PitchOption(BaseModel):
    card: OrgCard
    outcome: TagStatus = Field(description="What a tag does: delivered (E2), or held until the organisation verifies")
    available: bool
    reason: Reason | None
    message: str | None = Field(description="Why it is not available, or why a tag would be held")


class PitchGroup(BaseModel):
    niche: NicheRef | None
    orgs: list[PitchOption]


class PitchPicker(BaseModel):
    groups: list[PitchGroup]
    next_cursor: str | None
    cap: TagCap
    proposal_public: bool = Field(description="False until the proposal is published and clear of moderation")


async def picker(
    db: AsyncSession,
    settings: Settings,
    *,
    developer_id: UUID,
    proposal_id: UUID,
    filters: directory.DirectoryFilters,
    cursor: directory.Cursor | None,
    limit: int,
    responsiveness: ResponsivenessSource,
    now: datetime,
) -> PitchPicker:
    proposal = await tags.own_proposal(db, developer_id, proposal_id)
    page = await directory.list_directory(
        db, filters, cursor=cursor, limit=limit, responsiveness=responsiveness, now=now
    )
    ids = list(dict.fromkeys(card.id for group in page.groups for card in group.orgs))
    rows = (await db.execute(tags.ORGS, {"ids": ids})).all() if ids else []
    found = await tags.conflicts(db, developer_id=developer_id, proposal_id=proposal_id, orgs=rows)
    tag_cap, _ = await tags.cap(db, settings, developer_id=developer_id, proposal_id=proposal_id)
    groups = []
    for group in page.groups:
        options = []
        for card in group.orgs:
            outcome = OUTCOME_BY_BADGE[card.badge.level]
            conflict = found.get(card.id)
            options.append(
                PitchOption(
                    card=card,
                    outcome=outcome,
                    available=conflict is None,
                    reason=None if conflict is None else conflict.reason,
                    message=conflict.message(card.name) if conflict else tags.held_message(outcome, card.name),
                )
            )
        groups.append(PitchGroup(niche=group.niche, orgs=options))
    return PitchPicker(
        groups=groups, next_cursor=page.next_cursor, cap=tag_cap, proposal_public=tags.is_public(proposal)
    )
