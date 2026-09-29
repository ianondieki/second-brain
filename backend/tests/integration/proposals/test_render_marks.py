"""AC-REPO-2 (REQ-REPO-01, REQ-PROV-03; docs/spec/06 6.1, 6.4 item 3): a Tier-2 render includes the owner attribution
mark (handle before ``INTEREST_CONFIRMED``, display name after, using a fixture row of the Phase 2 ``engagements``
skeleton) and the viewer's name, organisation, ``view_id`` and EAT date in a tiled overlay and in document metadata;
each render writes one ``document_views`` row in the same request; the owner's "Who has seen this" panel lists the
view within 5 s; the page is never cached; organisations get Tier 2 only as that page, never as JSON."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine
from structlog.testing import capture_logs

from bridge.proposals.render import TILES, eat
from tests.integration.proposals.helpers import SECRET_APPROACH, SECRET_LINK, TIER2_MARKERS, Developers, rows
from tests.integration.proposals.tier2_scene import Scene, SceneFactory, add_engagement

VIEW_ROWS = (
    "SELECT d.id, d.viewer_user_id, d.org_id, d.owner_id, d.version_id, d.nda_acceptance_id, d.nda_template_version,"
    " d.render_kind, d.started_at, length(d.fingerprint_seed) AS seed, a.id AS own_nda, t.version AS own_nda_version"
    " FROM document_views d JOIN nda_acceptances a ON a.user_id = d.viewer_user_id AND a.proposal_id = d.proposal_id"
    " JOIN nda_templates t ON t.id = a.nda_template_id WHERE d.proposal_id = :p ORDER BY d.started_at, d.id"
)


def meta(html: str, name: str) -> str:
    found = re.search(rf'<meta name="bridge:{name}" content="([^"]*)">', html)
    assert found is not None, name
    return found.group(1)


async def render(scene: Scene) -> httpx.Response:
    response = await scene.viewer.get(scene.path("tier2"))
    assert response.status_code == 200, response.text
    return response


async def test_a_render_carries_both_marks_and_is_logged_as_one_view(
    scenes: SceneFactory, owner_engine: AsyncEngine
) -> None:
    scene = await scenes()
    response = await render(scene)
    html = response.text
    assert response.headers["content-type"].startswith("text/html")
    assert "no-store" in response.headers["cache-control"]
    assert "no-cache" in response.headers["cache-control"]
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")

    [view] = await rows(owner_engine, VIEW_ROWS, p=scene.proposal_id)
    assert (view.viewer_user_id, view.org_id, view.owner_id, view.version_id) == (
        scene.viewer_id,
        scene.org_id,
        scene.owner_id,
        scene.version_id,
    )
    assert (view.nda_acceptance_id, view.nda_template_version) == (view.own_nda, view.own_nda_version)
    assert (view.render_kind, view.seed) == ("html", 16)
    # Per-viewer mark: metadata and the tiled overlay name the viewer, the organisation, the view and the EAT date.
    when = eat(view.started_at)
    assert meta(html, "view-id") == str(view.id)
    assert meta(html, "viewer") == scene.viewer_name
    assert meta(html, "viewer-org") == scene.org_name
    assert meta(html, "viewed-on") == eat(view.started_at, seconds=True)
    line = f"{scene.viewer_name} · {scene.org_name} · {when} · view {view.id}"
    assert html.count(f"<span>{line}</span>") == TILES
    # Owner attribution: the handle (the engagement has not reached INTEREST_CONFIRMED), certificate and /verify.
    assert f"By {scene.owner_handle} · Certificate {scene.cert_id} · Registered " in html
    assert f"/verify/{scene.cert_id}" in html
    assert meta(html, "cert-id") == scene.cert_id
    assert SECRET_APPROACH in html
    assert SECRET_LINK in html

    # "Who has seen this": the owner sees the view at once (well within 5 s).
    panel = await scene.owner.get(f"/api/me/proposals/{scene.proposal_id}/views")
    assert panel.status_code == 200, panel.text
    [item] = panel.json()["items"]
    assert item["view_id"] == str(view.id)
    assert item["org"] == {"id": str(scene.org_id), "name": scene.org_name}
    assert item["viewer_name"] == scene.viewer_name
    assert (item["version_no"], item["render_kind"], item["duration"]) == (1, "html", None)
    assert item["nda_version"] == view.own_nda_version
    viewed_at = datetime.fromisoformat(item["viewed_at"])
    assert viewed_at == view.started_at
    assert datetime.now(UTC) - viewed_at < timedelta(seconds=5)

    events = await rows(
        owner_engine,
        "SELECT org_id, subject_id, payload FROM audit_events WHERE actor_user_id = :u AND action = 'tier2.viewed'",
        u=scene.viewer_id,
    )
    assert [(e.org_id, e.subject_id) for e in events] == [(scene.org_id, scene.version_id)]
    assert events[0].payload == {
        "proposal_id": str(scene.proposal_id),
        "view_id": str(view.id),
        "render_kind": "html",
        "nda_template_version": view.own_nda_version,
    }


async def test_each_render_is_its_own_view(scenes: SceneFactory, owner_engine: AsyncEngine) -> None:
    scene = await scenes()
    first, second = await render(scene), await render(scene)
    views = await rows(owner_engine, VIEW_ROWS, p=scene.proposal_id)
    assert [str(v.id) for v in views] == [meta(first.text, "view-id"), meta(second.text, "view-id")]
    panel = (await scene.owner.get(f"/api/me/proposals/{scene.proposal_id}/views")).json()
    assert [i["view_id"] for i in panel["items"]] == [str(v.id) for v in reversed(views)]  # newest first


async def test_the_owner_is_named_once_the_organisation_approved_to_proceed(
    scenes: SceneFactory, owner_engine: AsyncEngine
) -> None:
    scene = await scenes()
    async with owner_engine.begin() as conn:
        await add_engagement(conn, scene.proposal_id, scene.org_id, scene.owner_id, "SUBMITTED")
    assert f"By {scene.owner_handle} ·" in (await render(scene)).text
    async with owner_engine.begin() as conn:
        await conn.exec_driver_sql(
            "UPDATE engagements SET state = 'INTEREST_CONFIRMED' WHERE proposal_id = %(p)s", {"p": scene.proposal_id}
        )
    html = (await render(scene)).text
    assert "By Dev · Certificate" in html  # the owner's display name (helpers.add_developer)
    assert scene.owner_handle not in html


async def test_who_has_seen_this_is_the_owners_alone(
    scenes: SceneFactory, developers: Developers, owner_engine: AsyncEngine
) -> None:
    mine = await scenes()
    await render(mine)
    theirs = await scenes()  # (new current terms and NDA versions: build it after mine has rendered)
    other_view = meta((await render(theirs)).text, "view-id")
    panel = (await mine.owner.get(f"/api/me/proposals/{mine.proposal_id}/views")).json()
    assert len(panel["items"]) == 1
    assert other_view not in {i["view_id"] for i in panel["items"]}
    path = f"/api/me/proposals/{mine.proposal_id}/views"
    for outsider in (theirs.owner, mine.viewer, await developers()):
        response = await outsider.get(path)
        assert response.status_code == 404, response.text
    empty = await developers()
    assert (await empty.get(f"/api/me/proposals/{UUID(int=0)}/views")).status_code == 404


async def test_no_tier2_text_in_logs_or_audit_while_rendering(scenes: SceneFactory, owner_engine: AsyncEngine) -> None:
    scene = await scenes()
    with capture_logs() as logs:
        await render(scene)
        await scene.owner.get(f"/api/me/proposals/{scene.proposal_id}/views")
    events = await rows(
        owner_engine,
        "SELECT e.payload, d.details FROM audit_events e LEFT JOIN event_details d ON d.event_id = e.id"
        " WHERE e.actor_user_id = ANY (:users)",
        users=[scene.viewer_id, scene.owner_id],
    )
    assert events
    for text in (repr(logs), repr([tuple(e) for e in events])):
        for marker in TIER2_MARKERS:
            assert marker not in text


async def test_organisations_get_tier2_only_as_a_marked_page(scenes: SceneFactory) -> None:
    """No JSON form of Tier 2 for organisations: every route tagged tier2 that answers JSON carries no Tier-2 field,
    and the one that carries Tier 2 answers text/html only."""
    scene = await scenes()
    schema = scene.viewer.app.openapi()  # type: ignore[attr-defined]
    tier2_fields = {"approach", "architecture", "pricing", "notes", "links", "attachments", "confidential"}
    for path, operations in schema["paths"].items():
        for operation in operations.values():
            if "tier2" not in operation.get("tags", []):
                continue
            content = operation["responses"].get("200", operation["responses"].get("201", {})).get("content", {})
            if path.endswith("/tier2"):
                assert set(content) == {"text/html"}
                continue
            ref = content["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
            assert not tier2_fields & set(schema["components"]["schemas"][ref]["properties"]), path
