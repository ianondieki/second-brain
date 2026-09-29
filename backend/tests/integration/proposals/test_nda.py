"""The Evaluation NDA step (REQ-REPO-01; docs/spec/06 6.1): show the current terms with the viewer-logging notice,
accept exactly what was shown, recorded once per person, organisation, proposal and template version with its hash
and notice version; a new version needs a new acceptance; accepting needs every other condition of Tier-2 access."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.legal.nda import LOGGING_NOTICE, LOGGING_NOTICE_VERSION
from tests.integration.proposals.helpers import rows
from tests.integration.proposals.tier2_scene import SceneFactory, new_template

ACCEPTANCES = (
    "SELECT a.id, a.nda_template_id, a.template_sha256, a.logging_notice_version, a.accepted_at, t.version"
    " FROM nda_acceptances a JOIN nda_templates t ON t.id = a.nda_template_id"
    " WHERE a.user_id = :u AND a.proposal_id = :p ORDER BY a.accepted_at, a.id"
)
EVENTS = "SELECT org_id, payload FROM audit_events WHERE actor_user_id = :u AND action = 'tier2.nda_accepted'"


def accept_body(terms: dict[str, Any]) -> dict[str, Any]:
    return {
        "template_id": terms["template_id"],
        "sha256": terms["sha256"],
        "logging_notice_version": terms["logging_notice"]["version"],
    }


async def test_the_nda_is_shown_then_accepted_once_per_version(scenes: SceneFactory, owner_engine: AsyncEngine) -> None:
    scene = await scenes("no_nda")
    blocked = await scene.viewer.get(scene.path("tier2"))
    assert blocked.json()["detail"]["code"] == "nda_required"

    shown = await scene.viewer.get(scene.path("nda"))
    assert shown.status_code == 200, shown.text
    terms = shown.json()
    assert terms["body"].startswith("DRAFT")
    assert terms["is_placeholder"] is True
    assert terms["logging_notice"] == {"version": LOGGING_NOTICE_VERSION, "text": LOGGING_NOTICE}
    assert (terms["acceptance_id"], terms["accepted_at"]) == (None, None)

    first = await scene.viewer.post(scene.path("nda"), json=accept_body(terms))
    again = await scene.viewer.post(scene.path("nda"), json=accept_body(terms))
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()
    [row] = await rows(owner_engine, ACCEPTANCES, u=scene.viewer_id, p=scene.proposal_id)
    assert str(row.id) == first.json()["acceptance_id"]
    assert (str(row.nda_template_id), bytes(row.template_sha256).hex()) == (terms["template_id"], terms["sha256"])
    assert row.logging_notice_version == LOGGING_NOTICE_VERSION
    [event] = await rows(owner_engine, EVENTS, u=scene.viewer_id)
    assert event.org_id == scene.org_id
    assert event.payload == {
        "acceptance_id": str(row.id),
        "nda_template_id": terms["template_id"],
        "nda_version": terms["version"],
        "template_sha256": terms["sha256"],
        "logging_notice_version": LOGGING_NOTICE_VERSION,
    }
    accepted = (await scene.viewer.get(scene.path("nda"))).json()
    assert accepted["acceptance_id"] == str(row.id)
    assert accepted["accepted_at"] is not None
    assert (await scene.viewer.get(scene.path("tier2"))).status_code == 200

    # A new version: the old acceptance no longer opens Tier 2, and the stale version cannot be accepted.
    async with owner_engine.begin() as conn:
        await new_template(conn, "evaluation_nda")
    assert (await scene.viewer.get(scene.path("tier2"))).json()["detail"]["code"] == "nda_required"
    stale = await scene.viewer.post(scene.path("nda"), json=accept_body(terms))
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "nda_outdated"
    renewed = (await scene.viewer.get(scene.path("nda"))).json()
    assert renewed["template_id"] != terms["template_id"]
    assert renewed["acceptance_id"] is None
    assert (await scene.viewer.post(scene.path("nda"), json=accept_body(renewed))).status_code == 201
    assert (await scene.viewer.get(scene.path("tier2"))).status_code == 200
    assert len(await rows(owner_engine, ACCEPTANCES, u=scene.viewer_id, p=scene.proposal_id)) == 2


async def test_accepting_exactly_what_was_shown(scenes: SceneFactory, owner_engine: AsyncEngine) -> None:
    scene = await scenes("no_nda")
    terms = (await scene.viewer.get(scene.path("nda"))).json()
    for wrong in (
        {"sha256": "0" * 64},
        {"logging_notice_version": "v0"},
        {"template_id": str(scene.proposal_id)},
    ):
        response = await scene.viewer.post(scene.path("nda"), json=accept_body(terms) | wrong)
        assert response.status_code == 409, wrong
        assert response.json()["detail"]["code"] == "nda_outdated"
    malformed = await scene.viewer.post(scene.path("nda"), json=accept_body(terms) | {"sha256": "XYZ"})
    assert malformed.status_code == 422
    assert await rows(owner_engine, ACCEPTANCES, u=scene.viewer_id, p=scene.proposal_id) == []


async def test_the_nda_step_needs_every_other_condition(scenes: SceneFactory, owner_engine: AsyncEngine) -> None:
    """Without a grant (or any other condition) the NDA is neither shown nor recorded: nobody signs an NDA for a
    proposal they cannot open."""
    scene = await scenes("no_grant")
    shown = await scene.viewer.get(scene.path("nda"))
    assert shown.status_code == 403
    assert shown.json()["detail"]["code"] == "grant_required"
    body = {"template_id": str(scene.proposal_id), "sha256": "0" * 64, "logging_notice_version": "v1"}
    refused = await scene.viewer.post(scene.path("nda"), json=body)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "grant_required"
    denials = await rows(
        owner_engine,
        "SELECT payload->>'purpose' AS purpose FROM audit_events WHERE actor_user_id = :u"
        " AND action = 'tier2.access_denied'",
        u=scene.viewer_id,
    )
    assert [d.purpose for d in denials] == ["nda", "nda"]
    # The scene's acceptance was written by the fixture; the refused POST added none.
    assert len(await rows(owner_engine, ACCEPTANCES, u=scene.viewer_id, p=scene.proposal_id)) == 1
