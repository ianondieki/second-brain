"""AC-PROP-5 (REQ-PROP-01, REQ-MOD-01): a developer publishes a proposal with a newly pasted problem statement in one
flow; the Problem is created with ``source=developer``, published at once and linked, labelled "Developer-reported",
and appears in the moderation queue without blocking the publication."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.proposals.helpers import (
    Developers,
    ProposalWorld,
    Staff,
    cases_about,
    create,
    draft_body,
    publish,
    rows,
    user_of,
)

NEW_PROBLEM = {"title": "Evening milk spoils on the way", "statement": "Farmers lose a third of the evening milk."}


async def test_a_new_problem_is_published_linked_and_queued_without_blocking(
    developers: Developers, moderators: Staff, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    body = draft_body(proposal_world, link=False)
    body["new_problem"] = NEW_PROBLEM
    created = await create(owner, body)
    assert created["draft"]["problems"] == []

    response = await publish(owner, created["id"])
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["moderation"]["state"] == "clear"  # the publication is not blocked
    problem_id = out["new_problem_id"]
    assert problem_id is not None

    [problem] = await rows(owner_engine, "SELECT * FROM problems WHERE id = :id", id=problem_id)
    assert (problem.source, problem.status, problem.moderation_state) == ("developer", "published", "clear")
    assert (problem.created_by, problem.niche_id) == (user_of(owner), proposal_world.niche_id)
    assert (problem.title, problem.statement) == (NEW_PROBLEM["title"], NEW_PROBLEM["statement"])
    assert problem.published_at is not None
    links = await rows(
        owner_engine, "SELECT problem_id FROM proposal_problems WHERE proposal_version_id = :v", v=out["version_id"]
    )
    assert [str(link.problem_id) for link in links] == [problem_id]

    mine = (await owner.get(f"/api/me/proposals/{created['id']}")).json()
    assert mine["draft"] is None
    assert mine["current"]["new_problem"] is None  # draft-only data is gone once published

    reader = await developers(level="d0")
    card = (await reader.get(f"/api/proposals/{created['id']}")).json()
    assert [(p["id"], p["source"], p["label"]) for p in card["problems"]] == [
        (problem_id, "developer", "Developer-reported")
    ]
    picker = (await reader.get("/api/problems", params={"niche": proposal_world.parent_slug})).json()["items"]
    assert problem_id in [p["id"] for p in picker]

    moderator = await moderators()
    [case] = await cases_about(moderator, problem_id)
    assert case["subject_type"] == "problem"
    assert case["reasons"] == ["new_developer_problem"]
    assert (case["source"], case["status"], case["subject_state"]) == ("regex", "open", "clear")
    assert case["preview"] == {"title": NEW_PROBLEM["title"], "text": NEW_PROBLEM["statement"]}
    assert await cases_about(moderator, created["id"]) == []  # the teaser itself raised nothing


async def test_a_new_problem_can_take_its_own_niche(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    body = draft_body(proposal_world)
    body["new_problem"] = NEW_PROBLEM | {"niche_id": str(proposal_world.parent_id)}
    created = await create(owner, body)
    out = (await publish(owner, created["id"])).json()
    [problem] = await rows(owner_engine, "SELECT niche_id FROM problems WHERE id = :id", id=out["new_problem_id"])
    assert problem.niche_id == proposal_world.parent_id
    links = await rows(
        owner_engine, "SELECT problem_id FROM proposal_problems WHERE proposal_version_id = :v", v=out["version_id"]
    )
    assert {str(link.problem_id) for link in links} == {out["new_problem_id"], str(proposal_world.problem_id)}
