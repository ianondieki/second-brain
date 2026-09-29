"""AC-REPO-1 (REQ-REPO-01, REQ-SEC-01; docs/spec/06 6.1): with every condition of ``can_view_tier2`` met a Tier-2 GET
returns 200; removing any single condition makes it return 403 (404 where the tenancy rules hide existence) and write
a ``tier2.access_denied`` audit event naming the condition. The engagement conditions use engagements moved by their
parties through events (revision 0003); the Master Enterprise Terms and Evaluation NDA conditions use fresh template
versions.

Also: the owner reads their own Tier 2 (not logged) and needs no NDA, a refused viewer is never logged as a view, no
Tier-2 text reaches a refusal, a log line or an audit payload, a session still waiting for its second factor is asked
for it before anything else, and the Tier-2 row is read in the path organisation's tenant context.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from structlog.testing import capture_logs

from bridge.crypto.envelope import KeyWrapper
from bridge.proposals import tier2
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
    for shown in (response.text, repr(logs), repr([tuple(d) for d in denials])):
        for marker in TIER2_MARKERS:
            assert marker not in shown


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
    [current] = await rows(
        owner_engine,
        "SELECT id, sha256 FROM nda_templates WHERE id = app_current_nda_template('evaluation')",
    )
    body = {"template_id": str(current.id), "sha256": bytes(current.sha256).hex(), "logging_notice_version": "v1"}
    accept = await owner.post(scene.path("nda"), json=body)  # exactly the current terms, and still refused
    assert accept.status_code == 409
    assert accept.json()["detail"]["code"] == "nda_not_needed"
    assert await rows(owner_engine, "SELECT id FROM nda_acceptances WHERE user_id = :u", u=scene.owner_id) == []
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


async def test_a_session_waiting_for_its_second_factor_is_asked_for_it_before_anything_else(
    scenes: SceneFactory, developers: Developers, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    """A member and a stranger whose sessions still wait for the second factor get 401 ``mfa_required`` on every Tier-2
    route, flag on or off: no membership is looked up for them and no refusal is written in their name (security
    review of P3, MINOR 1)."""
    scene = await scenes()
    async with AsyncExitStack() as stack:
        clients = [
            scene.viewer,
            await viewer_client(stack, app_engine, scene.owner, scene.viewer_id, enabled=False),
            await viewer_client(stack, app_engine, scene.owner, user_of(await developers())),
        ]
        users = [scene.viewer_id, user_of(clients[2])]
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE sessions SET mfa_pending = true, mfa_verified_at = NULL WHERE user_id = ANY (:u)"),
                {"u": users},
            )
        body = {"template_id": str(scene.proposal_id), "sha256": "0" * 64, "logging_notice_version": "v1"}
        for client in clients:
            for method, leaf in (("GET", "tier2"), ("GET", "nda"), ("POST", "nda")):
                response = await client.request(method, scene.path(leaf), json=body if method == "POST" else None)
                assert response.status_code == 401, (method, leaf, response.text)
                assert response.json()["detail"]["code"] == "mfa_required"
    for user in users:
        assert await rows(owner_engine, DENIALS, u=user) == []
    assert await rows(owner_engine, VIEWS, p=scene.proposal_id) == []


async def test_the_tier2_row_is_read_in_the_path_organisations_tenant(
    scenes: SceneFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviewer belongs to two organisations; only the granting one is in the path. The Tier-2 row is read with
    ``app.user_id`` the reviewer and ``app.org_id`` that organisation (``app_tier2_granted`` narrows to it)."""
    scene = await scenes("another_org")  # a second organisation of the reviewer's, with everything but a grant
    seen: list[tuple[str, str]] = []
    original = tier2.load

    async def recording(db: AsyncSession, wrapper: KeyWrapper, proposal_id: UUID, version_id: UUID) -> Any:
        tenant = await db.execute(
            text("SELECT current_setting('app.user_id', true), current_setting('app.org_id', true)")
        )
        seen.append(tuple(tenant.one()))
        return await original(db, wrapper, proposal_id, version_id)

    monkeypatch.setattr(tier2, "load", recording)
    response = await scene.viewer.get(scene.path("tier2", scene.granted_org_id))
    assert response.status_code == 200, response.text
    assert SECRET_APPROACH in response.text
    assert seen == [(str(scene.viewer_id), str(scene.granted_org_id))]
    refused = await scene.viewer.get(scene.path("tier2"))  # the other organisation: refused before any read
    assert refused.json()["detail"]["code"] == "grant_required"
    assert len(seen) == 1
