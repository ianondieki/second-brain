"""AC-SEC-2 (REQ-SEC-01, REQ-REPO-01; docs/spec/10): with ``FEATURE_TIER2_ENABLED=false`` every Tier-2 endpoint
returns 403 ``tier2_disabled`` regardless of NDA state. The routes are read from the OpenAPI document (tag ``tier2``),
so a new Tier-2 route cannot escape the test; each is called by a viewer who meets every condition (NDA accepted), by
the owner, by a signed-in stranger and anonymously, and nothing is recorded but the refusals. Tenancy comes first: on
an organisation's path a signed-in non-member gets 404, as on every organisation route (AC-SEC-1). AC-SEC-7 (deals)
is Phase 3."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from tests.integration.api import make_client
from tests.integration.proposals.helpers import Developers, rows, user_of
from tests.integration.proposals.tier2_scene import SceneFactory, viewer_client

EXPECTED = {
    ("GET", "/api/orgs/{org_id}/proposals/{proposal_id}/nda"),
    ("POST", "/api/orgs/{org_id}/proposals/{proposal_id}/nda"),
    ("GET", "/api/orgs/{org_id}/proposals/{proposal_id}/tier2"),
    ("GET", "/api/me/proposals/{proposal_id}/tier2"),
    ("POST", "/api/me/proposals/{proposal_id}/assistant/consent"),  # REQ-PROP-05: Tier 2 to an LLM
    ("POST", "/api/me/proposals/{proposal_id}/assistant/suggestions"),
}
WRITES = (
    "SELECT (SELECT count(*) FROM document_views WHERE proposal_id = :p)"
    " + (SELECT count(*) FROM nda_acceptances WHERE proposal_id = :p) AS n"
)


def tier2_routes(schema: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if "tier2" in operation.get("tags", [])
    }


async def test_tier2_flag(
    scenes: SceneFactory, developers: Developers, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    scene = await scenes()  # every condition met and the NDA accepted, the flag on for this client
    routes = tier2_routes(scene.viewer.app.openapi())  # type: ignore[attr-defined]
    assert routes >= EXPECTED
    terms = (await scene.viewer.get(scene.path("nda"))).json()
    body = {
        "template_id": terms["template_id"],
        "sha256": terms["sha256"],
        "logging_notice_version": terms["logging_notice"]["version"],
    }
    assert (await scene.viewer.get(scene.path("tier2"))).status_code == 200  # the flag is the only difference below
    [before] = await rows(owner_engine, WRITES, p=scene.proposal_id)

    async with AsyncExitStack() as stack:
        viewer = await viewer_client(stack, app_engine, scene.owner, scene.viewer_id, enabled=False)
        owner = await viewer_client(stack, app_engine, scene.owner, scene.owner_id, enabled=False)
        stranger = await viewer_client(stack, app_engine, scene.owner, user_of(await developers()), enabled=False)
        off = get_settings().model_copy(update={"feature_tier2_enabled": False})
        anonymous = await stack.enter_async_context(make_client(app_engine, off))
        for method, template in sorted(routes):
            url = template.format(org_id=scene.org_id, proposal_id=scene.proposal_id)
            org_route = "{org_id}" in template
            for client in (viewer, owner, stranger, anonymous):
                response = await client.request(method, url, json=body if method == "POST" else None)
                if org_route and client in (owner, stranger):  # signed in, not members: tenancy first
                    assert response.status_code == 404, (method, template, response.text)
                    continue
                assert response.status_code == 403, (method, template, response.text)
                assert response.json()["detail"]["code"] == "tier2_disabled"

    [after] = await rows(owner_engine, WRITES, p=scene.proposal_id)
    assert after.n == before.n
    refusals = await rows(
        owner_engine,
        "SELECT payload FROM audit_events WHERE actor_user_id = :u AND action = 'tier2.access_denied'",
        u=scene.viewer_id,
    )
    assert len(refusals) == len(routes)
    assert {r.payload["condition"] for r in refusals} == {"tier2_disabled"}
