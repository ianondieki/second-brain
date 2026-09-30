"""REQ-RES-01 / REQ-ADM-01: the research admin API (``/api/admin/research/*``; docs/spec/06 6.5; AC-RES-1, AC-RES-2;
D-45).

- Staff admin with TOTP and a fresh second factor only: everyone else gets 404 (signed out, a developer, staff without
  TOTP), a moderator 403, an admin with a stale second factor 403 ``step_up_required``.
- ``GET /sources`` lists the saved excerpts with freshness and the allowlist; ``POST /runs`` answers 202 with a
  running run and queues ``research.run`` in the same transaction; ``GET /runs[/{id}]`` reads them back.
- ``GET /candidates`` shows research cards awaiting review with sources, named organisations and the D-45 checklist
  placeholder; ``POST /candidates/{id}/decision`` runs the publish checks in code, then ``app_moderate_problem``:
  approve publishes (the card then shows with its citations and label), reject keeps it private, a second decision
  is 409, a tampered source or a naming card without the checklist is 409, and the database backstop still refuses
  a card the code would have let through.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Protocol
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.admin import research as research_api
from bridge.clock import utcnow
from bridge.db import bind_tenant, create_session_factory
from bridge.ids import uuid7
from bridge.problems.research import review
from tests.integration import world as w
from tests.integration.api import make_client, sign_in_as
from tests.integration.problems.research_rig import (
    SACCO_DRAFT,
    TELECOM_DRAFT,
    ResearchWorld,
    answer,
    execute,
    llm_runtime,
    make_research_world,
    rows,
    start,
)

BASE = "/api/admin/research"


class Client(Protocol):
    def __call__(self, user_id: UUID, *, fresh: bool = True) -> Awaitable[httpx.AsyncClient]: ...


@pytest.fixture
async def world(owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> ResearchWorld:
    found = await make_research_world(owner_engine)
    monkeypatch.setattr(research_api, "get_catalogue", lambda: found.catalogue)
    return found


@pytest.fixture
async def as_user(app_engine: AsyncEngine) -> AsyncIterator[Client]:
    async with AsyncExitStack() as stack:

        async def make(user_id: UUID, *, fresh: bool = True) -> httpx.AsyncClient:
            client = await stack.enter_async_context(make_client(app_engine))
            await sign_in_as(client, app_engine, user_id, mfa_verified=fresh)
            return client

        yield make


ROUTES: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("GET", "/sources", None),
    ("POST", "/runs", {"niche": "health"}),
    ("GET", "/runs", None),
    ("GET", f"/runs/{uuid7()}", None),
    ("GET", "/candidates", None),
    ("POST", f"/candidates/{uuid7()}/decision", {"decision": "approve"}),
)


async def _call(client: httpx.AsyncClient, method: str, path: str, body: dict[str, Any] | None) -> httpx.Response:
    return await client.request(method, BASE + path, json=body)


async def test_every_route_is_staff_admin_only_with_a_fresh_second_factor(
    world: ResearchWorld, as_user: Client, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    async with make_client(app_engine) as anonymous:
        for method, path, body in ROUTES:
            assert (await _call(anonymous, method, path, body)).status_code == 404, path
    async with owner_engine.begin() as conn:
        no_totp = await w.add_user(conn, f"nototp-{uuid7().hex[:8]}@example.test", "No TOTP", staff_role="admin")
        await conn.execute(text("UPDATE users SET totp_enabled_at = NULL WHERE id = :id"), {"id": no_totp})
    developer, admin_without_totp = await as_user(world.developer), await as_user(no_totp)
    moderator, stale = await as_user(world.moderator), await as_user(world.admin, fresh=False)
    for method, path, body in ROUTES:
        assert (await _call(developer, method, path, body)).status_code == 404, path
        assert (await _call(admin_without_totp, method, path, body)).status_code == 404, path
        assert (await _call(moderator, method, path, body)).status_code == 403, path
        refused = await _call(stale, method, path, body)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "step_up_required"), path
    assert await rows(owner_engine, "SELECT id FROM research_runs WHERE started_by = :u", u=world.admin) == []


async def test_a_stale_second_factor_is_refused_after_12_hours(
    world: ResearchWorld, as_user: Client, owner_engine: AsyncEngine
) -> None:
    admin = await as_user(world.admin)
    assert (await admin.get(BASE + "/runs")).status_code == 200
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE sessions SET mfa_verified_at = :t WHERE user_id = :u"),
            {"t": utcnow() - timedelta(hours=13), "u": world.admin},
        )
    assert (await admin.get(BASE + "/runs")).json()["detail"]["code"] == "step_up_required"


async def test_sources_list_the_saved_excerpts_with_their_freshness(world: ResearchWorld, as_user: Client) -> None:
    admin = await as_user(world.admin)
    body = (await admin.get(BASE + "/sources")).json()
    assert len(body["excerpts"]) == 19
    archived = {e["id"] for e in body["excerpts"] if e["freshness"] == "archived"}
    assert archived == {"ke-tel-005", "ke-agr-004"}
    assert {d["domain"] for d in body["allowlist"] if d["official"]} == {
        "kilimo.go.ke",
        "www.sasra.go.ke",
        "www.ca.go.ke",
    }
    assert len(body["allowlist"]) == 8


async def test_starting_a_run_answers_202_and_queues_the_job(
    world: ResearchWorld, as_user: Client, owner_engine: AsyncEngine
) -> None:
    admin = await as_user(world.admin)
    started = await admin.post(BASE + "/runs", json={"niche": world.slugs["health"]})
    assert started.status_code == 202, started.text
    run = started.json()
    assert (run["status"], run["niche"], run["country"], run["started_by"]) == (
        "running",
        world.slugs["health"],
        "KE",
        str(world.admin),
    )
    assert (run["searches"], run["fetches"], run["candidates"], run["demo_fallback"]) == (0, 0, 0, False)
    [job] = await rows(
        owner_engine,
        "SELECT task_name, queue_name, lock, args FROM procrastinate_jobs WHERE task_name = 'research.run'"
        " AND args->>'run_id' = :r",
        r=run["id"],
    )
    assert (job.queue_name, job.lock) == ("research", f"research:{run['id']}")
    assert job.args == {"run_id": run["id"], "user_id": str(world.admin)}
    again = await admin.post(BASE + "/runs", json={"niche": world.slugs["health"]})
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "run_in_progress")
    unknown = await admin.post(BASE + "/runs", json={"niche": "no-excerpts-here"})
    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (422, "no_saved_excerpts")
    for bad in ({"niche": "Health!"}, {"niche": world.slugs["health"], "country": "UG"}, {"niche": "x", "extra": 1}):
        assert (await admin.post(BASE + "/runs", json=bad)).status_code == 422
    listed = (await admin.get(BASE + "/runs")).json()["items"]
    assert run["id"] in [r["id"] for r in listed]
    assert (await admin.get(f"{BASE}/runs/{run['id']}")).json()["status"] == "running"
    assert (await admin.get(f"{BASE}/runs/{uuid7()}")).status_code == 404


async def _candidates(app_engine: AsyncEngine, world: ResearchWorld, niche: str, *drafts: dict[str, Any]) -> UUID:
    run_id = await start(app_engine, world, niche)
    outcome = await execute(app_engine, world, run_id, llm_runtime(answer(*drafts)))
    assert outcome is not None
    return run_id


async def _card_of(admin: httpx.AsyncClient, run_id: UUID) -> dict[str, Any]:
    items = (await admin.get(BASE + "/candidates")).json()["items"]
    [card] = [c for c in items if c["research_run_id"] == str(run_id)]
    return dict(card)


async def test_ac_res_1_approving_publishes_a_cited_card_through_app_moderate_problem(
    world: ResearchWorld, as_user: Client, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    run_id = await _candidates(app_engine, world, "networks-telecommunications", TELECOM_DRAFT)
    admin, reader = await as_user(world.admin), await as_user(world.developer)
    card = await _card_of(admin, run_id)
    assert (card["named_orgs"], card["checklist"], card["seeded_example"]) == ([], [], False)
    assert sorted(s["excerpt_ref"] for s in card["sources"]) == ["ke-tel-001", "ke-tel-002", "ke-tel-004"]
    assert card["confidence"] == "0.846"
    # AC-RES-2: a candidate is on no public endpoint, not even for the staff admin who may read it under RLS
    for client in (reader, admin):
        assert (await client.get(f"/api/problems/{card['id']}")).status_code == 404
        listed = await client.get("/api/problems", params={"niche": world.slugs["networks-telecommunications"]})
        assert listed.json()["items"] == []
    url = f"{BASE}/candidates/{card['id']}/decision"
    assert (await (await as_user(world.moderator)).post(url, json={"decision": "approve"})).status_code == 403
    decided = await admin.post(url, json={"decision": "approve"})
    assert decided.status_code == 200, decided.text
    assert decided.json() == {"id": card["id"], "status": "published", "moderation_state": "clear"}
    [row] = await rows(
        owner_engine,
        "SELECT status::text, moderation_state::text, moderator_id FROM problems WHERE id = :id",
        id=card["id"],
    )
    assert tuple(row) == ("published", "clear", world.admin)
    shown = await reader.get(f"/api/problems/{card['id']}")
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert body["label"].startswith("AI-drafted, human-reviewed on ")
    assert (body["ai_generated"], body["seeded_example"], body["source"]) == (True, False, "research_agent")
    assert sorted(c["url"] for c in body["citations"]) == sorted(
        e.url for e in world.catalogue.excerpts if e.id in {"ke-tel-001", "ke-tel-002", "ke-tel-004"}
    )
    assert all(c["quote"] and c["published_date"] for c in body["citations"])
    listed = (await reader.get("/api/problems", params={"niche": world.slugs["networks-telecommunications"]})).json()
    assert [p["id"] for p in listed["items"]] == [card["id"]]
    assert listed["items"][0]["label"] == body["label"]
    again = await admin.post(url, json={"decision": "reject"})
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "already_decided")
    [event] = await rows(
        owner_engine,
        "SELECT actor_kind::text AS kind, payload FROM audit_events WHERE action = 'research.candidate_decided'"
        " AND subject_id = :id",
        id=card["id"],
    )
    assert event.kind == "staff"
    assert event.payload == {
        "decision": "approve",
        "research_run_id": str(run_id),
        "named_orgs": 0,
        "checklist_confirmed": False,
    }


async def test_rejecting_keeps_the_card_private(
    world: ResearchWorld, as_user: Client, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    run_id = await _candidates(app_engine, world, "networks-telecommunications", TELECOM_DRAFT)
    admin, reader = await as_user(world.admin), await as_user(world.developer)
    card = await _card_of(admin, run_id)
    decided = await admin.post(f"{BASE}/candidates/{card['id']}/decision", json={"decision": "reject"})
    assert decided.json() == {"id": card["id"], "status": "rejected", "moderation_state": "rejected"}
    assert (await reader.get(f"/api/problems/{card['id']}")).status_code == 404
    assert card["id"] not in [c["id"] for c in (await admin.get(BASE + "/candidates")).json()["items"]]


async def test_d45_a_card_naming_an_organisation_needs_the_checklist(
    world: ResearchWorld, as_user: Client, app_engine: AsyncEngine
) -> None:
    run_id = await _candidates(app_engine, world, "microfinance-saccos", SACCO_DRAFT)
    admin = await as_user(world.admin)
    card = await _card_of(admin, run_id)
    assert card["named_orgs"] == ["SACCO Societies Regulatory Authority"]
    assert card["checklist"] == [review.CHECKLIST_PLACEHOLDER]
    url = f"{BASE}/candidates/{card['id']}/decision"
    refused = await admin.post(url, json={"decision": "approve"})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "checklist_required")
    approved = await admin.post(url, json={"decision": "approve", "checklist_confirmed": True})
    assert approved.json()["status"] == "published"


async def test_a_tampered_source_fails_the_publish_checks(
    world: ResearchWorld, as_user: Client, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    """The quotes are verified verbatim against the saved excerpts at approval (AC-RES-1), not only at drafting."""
    run_id = await _candidates(app_engine, world, "networks-telecommunications", TELECOM_DRAFT)
    admin = await as_user(world.admin)
    card = await _card_of(admin, run_id)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE problem_sources SET quote = quote || ' (edited)' WHERE problem_id = :id AND excerpt_ref = :r"),
            {"id": card["id"], "r": "ke-tel-002"},
        )
    refused = await admin.post(f"{BASE}/candidates/{card['id']}/decision", json={"decision": "approve"})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "publish_check_failed")
    assert "source_not_saved" in refused.json()["detail"]["message"]


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("title", "Operators\u202e struggle", "control_character"),  # a bidi override, stored and served reordered
        ("statement", "Smaller operators say safaricom keeps most mobile money.", "named_org_without_official"),
        ("statement", "Smaller operators say Safari\u200bcom keeps most mobile money.", "control_character"),
        ("statement", "Smaller operators say M\u2011Pesa keeps most mobile money.", "named_org_without_official"),
        ("statement", "The market leader earned Sh89m from mobile money.", "unsupported_number"),  # MAJOR 1
    ],
)
async def test_approval_re_reads_the_text_for_hidden_names_scales_and_format_characters(
    world: ResearchWorld,
    as_user: Client,
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    column: str,
    value: str,
    reason: str,
) -> None:
    """P11 review MAJOR 2 at the publish gate: the definer stores format characters (it refuses only C0 and DEL),
    so approval re-reads the stored text with NFKC, the format-character rule and the any-case, any-dash names."""
    run_id = await _candidates(app_engine, world, "networks-telecommunications", TELECOM_DRAFT)
    admin = await as_user(world.admin)
    card = await _card_of(admin, run_id)
    async with owner_engine.begin() as conn:
        await conn.execute(text(f"UPDATE problems SET {column} = :v WHERE id = :id"), {"v": value, "id": card["id"]})
    refused = await admin.post(f"{BASE}/candidates/{card['id']}/decision", json={"decision": "approve"})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "publish_check_failed")
    assert reason in refused.json()["detail"]["message"]


async def _definer_candidate(app_engine: AsyncEngine, world: ResearchWorld, *excerpt_ids: str) -> UUID:
    """A card citing these saved excerpts, made through the definer (which checks the sources' form only: the source
    rule and freshness are the publish gate's)."""
    run_id = await start(app_engine, world, "networks-telecommunications")
    sources = []
    for excerpt_id in excerpt_ids:
        excerpt = world.catalogue.get(excerpt_id)
        assert excerpt is not None
        sources.append(
            {
                "url": excerpt.url,
                "publisher": excerpt.publisher,
                "source_type": excerpt.source_type,
                "published_date": excerpt.published_date.isoformat(),
                "retrieved_at": excerpt.retrieved_at.isoformat(),
                "quote": excerpt.quote,
                "excerpt_ref": excerpt.id,
            }
        )
    factory = create_session_factory(app_engine)
    async with factory() as db:
        await bind_tenant(db, user_id=world.admin)
        problem_id: UUID = (
            await db.execute(
                text(
                    "SELECT app_create_research_candidate(:run, 'Smaller operators are squeezed', 'Smaller operators"
                    " say the regime disadvantages them.', '', NULL, 0.5, '{}', CAST(:sources AS jsonb))"
                ),
                {"run": run_id, "sources": json.dumps(sources)},
            )
        ).scalar_one()
        await db.commit()
    return problem_id


async def _one_source_candidate(app_engine: AsyncEngine, world: ResearchWorld) -> UUID:
    return await _definer_candidate(app_engine, world, "ke-tel-004")


async def test_approval_refuses_a_card_whose_sources_have_aged_out_on_the_clock(
    world: ResearchWorld, as_user: Client, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    """Minor (a) of the P11 review: freshness is judged at approval on the shared clock. Moved 366 days ahead (the
    test clock's limit), ke-tel-002 (2026-02-27) and ke-tel-004 (2026-01-16) are past 18 months, so a card citing only
    them is refused although its two publishers would otherwise pass."""
    problem_id = await _definer_candidate(app_engine, world, "ke-tel-002", "ke-tel-004")
    admin = await as_user(world.admin)
    async with owner_engine.begin() as conn:
        before = (await conn.execute(text("SELECT enabled, clock_offset FROM test_clock"))).one()
        await conn.execute(text("UPDATE test_clock SET enabled = true, clock_offset = interval '366 days'"))
    try:
        refused = await admin.post(f"{BASE}/candidates/{problem_id}/decision", json={"decision": "approve"})
    finally:
        async with owner_engine.begin() as conn:
            restore = {"e": before.enabled, "o": before.clock_offset}
            await conn.execute(text("UPDATE test_clock SET enabled = :e, clock_offset = :o"), restore)
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "publish_check_failed")
    assert "sources_archived" in refused.json()["detail"]["message"]
    approved = await admin.post(f"{BASE}/candidates/{problem_id}/decision", json={"decision": "approve"})
    assert approved.json()["status"] == "published"  # back on today's clock both are fresh


async def test_one_publisher_fails_in_code_and_the_backstop_holds_without_the_code(
    world: ResearchWorld, as_user: Client, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    problem_id = await _one_source_candidate(app_engine, world)
    admin = await as_user(world.admin)
    url = f"{BASE}/candidates/{problem_id}/decision"
    refused = await admin.post(url, json={"decision": "approve"})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "publish_check_failed")
    assert "needs_official_or_two_publishers" in refused.json()["detail"]["message"]
    monkeypatch.setattr(review, "publish_violation", lambda *args: (None, ()))  # the code check switched off
    backstop = await admin.post(url, json={"decision": "approve"})
    assert (backstop.status_code, backstop.json()["detail"]["code"]) == (409, "publish_check_failed")
    assert (await admin.get(BASE + "/candidates")).status_code == 200  # the refusal rolled back cleanly


async def test_deciding_an_unknown_or_non_research_problem_is_404(world: ResearchWorld, as_user: Client) -> None:
    admin = await as_user(world.admin)
    missing = await admin.post(f"{BASE}/candidates/{uuid7()}/decision", json={"decision": "approve"})
    assert missing.status_code == 404
    bad = await admin.post(f"{BASE}/candidates/{uuid7()}/decision", json={"decision": "maybe"})
    assert bad.status_code == 422
