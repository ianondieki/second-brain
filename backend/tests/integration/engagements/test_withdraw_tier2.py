"""REQ-ENG-10 with REQ-REPO-01 (P3): withdrawing through the tracker ends the organisation's Tier-2 access.

The developer's ``withdraw`` (P5) moves the engagement to WITHDRAWN through its event chain; P3's ``can_view_tier2``
(condition 8) and the database's ``app_tier2_granted`` read that state, so the organisation's reviewer, who opened the
full proposal a moment before, is refused (403 ``engagement_ended``) and no further view is logged.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.db import bind_tenant, create_session_factory
from bridge.engagements.commands import open_engagement_for_tag
from tests.integration.engagements.api_world import Tracker, clients
from tests.integration.proposals.helpers import rows
from tests.integration.proposals.tier2_scene import SceneFactory

VIEWS = "SELECT id FROM document_views WHERE proposal_id = :p"


async def test_after_withdrawn_the_organisations_tier2_render_is_refused(
    scenes: SceneFactory, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    scene = await scenes()
    opened = await scene.viewer.get(scene.path("tier2"))
    assert opened.status_code == 200, opened.text
    [tag] = await rows(
        owner_engine,
        "SELECT id FROM tags WHERE proposal_id = :p AND org_id = :o AND developer_id = :d",
        p=scene.proposal_id,
        o=scene.granted_org_id,
        d=scene.owner_id,
    )
    async with create_session_factory(app_engine)() as db:  # P4's entry point, as the Pitch flow will call it
        await bind_tenant(db, user_id=scene.owner_id)
        engagement: UUID = (await open_engagement_for_tag(db, tag.id)).id
        await db.commit()
    t = Tracker(engagement)
    async with clients(app_engine, get_settings(), scene.owner_id) as (developer,):
        withdrawn = await t.ok(developer, "withdraw")
        assert withdrawn["state"] == "WITHDRAWN"

    refused = await scene.viewer.get(scene.path("tier2"))
    assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "engagement_ended")
    assert len(await rows(owner_engine, VIEWS, p=scene.proposal_id)) == 1  # only the view before the withdrawal
    async with owner_engine.connect() as conn:
        status, closed = (
            await conn.execute(
                text("SELECT status::text, closed_at IS NOT NULL FROM tags WHERE id = :id"), {"id": tag.id}
            )
        ).one()
        # The database half of the predicate agrees, for the same reviewer in the organisation's context.
        await conn.execute(text("SET LOCAL ROLE bridge_app"))
        await conn.execute(
            text("SELECT set_config('app.user_id', :u, true), set_config('app.org_id', :o, true)"),
            {"u": str(scene.viewer_id), "o": str(scene.granted_org_id)},
        )
        granted = (
            await conn.execute(
                text("SELECT app_tier2_granted(:p, :v, :o)"),
                {"p": scene.proposal_id, "v": scene.version_id, "o": scene.granted_org_id},
            )
        ).scalar_one()
    assert (status, closed) == ("withdrawn", True)
    assert granted is False
