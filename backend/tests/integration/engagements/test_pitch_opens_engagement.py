"""P4's Pitch opens the engagement through P5 (REQ-PROP-03 with REQ-ENG-01; `docs/platform/tasks/REQ-PROP-03.md`, the
P5 adapter): a delivered tag's engagement comes from ``open_engagement_for_tag``, so it carries the SUBMITTED
deadline from policy.yaml (the interim insert set none), and a refusal is the Pitch's 409 ``tag_conflict``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from bridge.engagements import commands
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import local_date
from bridge.engagements.policy import get_policy
from bridge.errors import ApiError
from bridge.models.enums import EngagementState
from bridge.proposals import tag_hooks
from tests.integration.proposals.helpers import Developers, ProposalWorld, rows
from tests.integration.proposals.pitch_helpers import PitchOrgs, pitch, pitchable


async def test_a_pitch_opens_the_engagement_with_its_deadline(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, owner_engine: AsyncEngine
) -> None:
    dev, proposal_id = await pitchable(developers, proposal_world)
    response = await pitch(dev, proposal_id, pitch_orgs.safaricom)
    assert response.status_code == 201, response.text
    [tag] = response.json()["tags"]
    [engagement] = await rows(
        owner_engine,
        "SELECT e.id, e.state, e.stage_entered_at, e.stage_deadline_at,"
        " (SELECT ev.stage_deadline_at FROM engagement_events ev WHERE ev.engagement_id = e.id AND ev.seq = 1)"
        " AS genesis_deadline FROM engagements e WHERE e.id = :id",
        id=UUID(tag["engagement_id"]),
    )
    assert engagement.state == "SUBMITTED"
    holidays = {
        r.observed_on
        for r in await rows(
            owner_engine,
            "SELECT observed_on FROM holidays WHERE country = 'KE' AND observed_on >= :d",
            d=local_date(engagement.stage_entered_at),
        )
    }
    expected: datetime | None = sm.stage_deadline(
        EngagementState.SUBMITTED, engagement.stage_entered_at, holidays, get_policy()
    )
    assert engagement.stage_deadline_at == expected
    assert engagement.genesis_deadline == expected  # the chain's first event carries it too


def test_the_default_hook_is_p5s_adapter() -> None:
    hooks = tag_hooks.default_hooks()
    assert hooks.open_engagement is tag_hooks.open_engagement
    assert not hasattr(tag_hooks, "interim_open_engagement")


async def test_a_refusal_is_the_pitchs_409(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(db: AsyncSession, tag_id: UUID) -> object:
        raise commands.OpenRefused("org_unavailable", "The organisation cannot receive engagements now.")

    monkeypatch.setattr(commands, "open_engagement_for_tag", refuse)
    ids = {"developer_id": UUID(int=1), "proposal_id": UUID(int=2), "version_id": UUID(int=3), "org_id": UUID(int=4)}
    with pytest.raises(ApiError) as conflict:
        await tag_hooks.open_engagement(None, tag_id=UUID(int=5), **ids)  # type: ignore[arg-type]
    assert conflict.value.status_code == 409
    assert conflict.value.detail == {
        "code": "tag_conflict",
        "message": "The organisation cannot receive engagements now.",
    }
