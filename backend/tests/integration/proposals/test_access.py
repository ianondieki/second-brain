"""AC-REPO-1 (REQ-REPO-01, REQ-SEC-01; docs/spec/06 6.1): with every condition of ``can_view_tier2`` met a Tier-2 GET
returns 200; removing any single condition makes it return 403 (404 where the tenancy rules hide existence) and write
a ``tier2.access_denied`` audit event naming the condition. The engagement conditions use fixture rows of the Phase 2
``engagements`` skeleton; the Master Enterprise Terms and Evaluation NDA conditions use fresh template versions.

Also: the owner reads their own Tier 2 (not logged), a refused viewer is never logged as a view, and no Tier-2 text
reaches a refusal, a log line or an audit payload.
"""

from __future__ import annotations

from contextlib import AsyncExitStack

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from structlog.testing import capture_logs

from tests.integration.proposals.helpers import SECRET_APPROACH, TIER2_MARKERS, Developers, rows, user_of
from tests.integration.proposals.tier2_scene import AUDITED, BREAKS, SceneFactory, add_member, viewer_client

DENIALS = (
    "SELECT org_id, subject_id, payload FROM audit_events WHERE actor_user_id = :u AND action = 'tier2.access_denied'"
)
VIEWS = "SELECT id FROM document_views WHERE proposal_id = :p"


@pytest.mark.parametrize("broken", list(BREAKS))
async def test_predicate_negatives(scenes: SceneFactory, owner_engine: AsyncEngine, broken: str) -> None:
    scene = await scenes(broken)
    status, code = BREAKS[broken]
    with capture_logs() as logs:
        response = await scene.viewer.get(scene.path("tier2"))
    assert response.status_code == status, response.text
    denials = await rows(owner_engine, DENIALS, u=scene.viewer_id)
    logged = await rows(owner_engine, VIEWS, p=scene.proposal_id)
    if code is None:
        assert SECRET_APPROACH in response.text
        assert denials == []
        assert len(logged) == 1
        return
    assert response.json()["detail"]["code"] == code
    [denial] = denials
    assert denial.subject_id == scene.proposal_id
    assert denial.payload == {
        "condition": AUDITED.get(broken, code),
        "purpose": "render",
        "org_id": str(scene.org_id),
    }
    # On the organisation's chain once the viewer is known to be its member; on the viewer's own chain otherwise.
    assert denial.org_id == (None if broken in AUDITED else scene.org_id)
    assert logged == []  # a refused viewer is never logged as a view
    for text in (response.text, repr(logs), repr([tuple(d) for d in denials])):
        for marker in TIER2_MARKERS:
            assert marker not in text


async def test_the_owner_reads_their_own_tier2_without_a_logged_view(
    scenes: SceneFactory, owner_engine: AsyncEngine
) -> None:
    scene = await scenes()
    owner = scene.owner
    owner.app.state.settings = scene.viewer.app.state.settings  # type: ignore[attr-defined]  # the flag on
    preview = f"/api/me/proposals/{scene.proposal_id}/tier2"
    response = await owner.get(preview)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"].startswith("no-store")
    assert SECRET_APPROACH in response.text
    assert '<meta name="bridge:render" content="owner-preview">' in response.text
    assert "bridge:view-id" not in response.text
    assert (await scene.viewer.get(preview)).status_code == 404  # the owner's alone
    # Through an organisation's path the owner is a stranger unless they are its member, and then still the owner.
    assert (await owner.get(scene.path("tier2"))).status_code == 404
    async with owner_engine.begin() as conn:
        await add_member(conn, scene.org_id, scene.owner_id, "{viewer}")
    assert (await owner.get(scene.path("tier2"))).status_code == 200
    nda = await owner.get(scene.path("nda"))
    assert nda.status_code == 409
    assert nda.json()["detail"]["code"] == "nda_not_needed"
    assert await rows(owner_engine, VIEWS, p=scene.proposal_id) == []
    reads = await rows(
        owner_engine,
        "SELECT payload FROM audit_events WHERE actor_user_id = :u AND action = 'proposal.tier2_read'"
        " AND payload ? 'render'",
        u=scene.owner_id,
    )
    assert [r.payload["render"] for r in reads] == ["html", "html"]


async def test_a_stranger_and_an_anonymous_caller_get_nothing(
    scenes: SceneFactory, developers: Developers, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    scene = await scenes()
    async with AsyncExitStack() as stack:
        stranger = await viewer_client(stack, app_engine, scene.owner, user_of(await developers()))
        response = await stranger.get(scene.path("tier2"))
        assert response.status_code == 404
        assert (await stranger.get(scene.path("nda"))).status_code == 404
    scene.viewer.cookies.clear()
    assert (await scene.viewer.get(scene.path("tier2"))).status_code == 401
    assert await rows(owner_engine, VIEWS, p=scene.proposal_id) == []
