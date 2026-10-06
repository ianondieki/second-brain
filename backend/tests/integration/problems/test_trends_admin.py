"""REQ-DEV-02, REQ-ADM-01 (D-60; P22 card B test B6, the staff half): the trend cards on the research admin API.

- Staff admin with a fresh second factor only: signed out and a developer 404, a moderator 403, a stale second factor
  403 ``step_up_required``.
- The queue lists cards newest first (``status`` filters) with their sources and trace id, never who decided; a
  decision publishes or rejects a candidate once (409 ``already_decided``), audited ``trend.card_decided``; a published
  card is a developer's to read, a candidate never.
- Publishing repeats the named-organisation rule on what is stored: a card naming an organisation, or carrying a
  capitalised name, that no stored source names is 409 ``unsourced_name`` (it may still be rejected); a card the job
  drafted from the fake adapter passes.
- ``POST /trend-runs``: 202, ``trends.draft`` queued through the outbox with the admin's id; the job run with those
  arguments stores the week's candidates.
"""

from __future__ import annotations

import json
from datetime import time
from typing import Any
from uuid import UUID

from bridge.db import create_session_factory
from bridge.ids import uuid7
from bridge.jobs.trends import Stored, WeeklyDeps, run_weekly
from bridge.problems.trends import fakes
from tests.integration.api import make_client
from tests.integration.events.api_world import (
    Clients,
    WeekDb,
    at,
    audit_actions,
    cast,
    code,
    owner_rows,
    owner_run,
    trend_card,
    trend_source,
)
from tests.integration.events.test_events_org import keys
from tests.integration.problems.test_trends_job import client

ADMIN = "/api/admin/research"
ROUTES: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("GET", "/trends", None),
    ("GET", f"/trends/{uuid7()}", None),
    ("POST", f"/trends/{uuid7()}/decision", {"decision": "publish"}),
    ("POST", "/trend-runs", None),
)


async def setup(week: WeekDb) -> Any:
    monday = week.monday()
    await at(week, monday)
    await owner_run(week, "DELETE FROM trend_cards")
    return monday, await cast(week)


async def test_the_trend_routes_are_staff_admin_only(week: WeekDb, as_user: Clients) -> None:
    _, p = await setup(week)
    developer, moderator = await as_user(p.developer), await as_user(p.moderator)
    stale = await as_user(p.admin, fresh=False)
    async with make_client(week.app) as anonymous:
        for method, path, sent in ROUTES:
            assert (await anonymous.request(method, ADMIN + path, json=sent)).status_code == 404, path
    for method, path, sent in ROUTES:
        assert (await developer.request(method, ADMIN + path, json=sent)).status_code == 404, path
        assert (await moderator.request(method, ADMIN + path, json=sent)).status_code == 403, path
        assert code(await stale.request(method, ADMIN + path, json=sent)) == (403, "step_up_required"), path


async def test_one_audited_decision_per_card_and_only_published_cards_reach_developers(
    week: WeekDb, as_user: Clients
) -> None:
    _, p = await setup(week)
    admin, developer = await as_user(p.admin), await as_user(p.developer)
    first = await trend_card(week, None, title="An older candidate", named_orgs=("GitHub",))
    await at(week, week.weeks[-1], time(12, 5))
    second = await trend_card(week, None, title="A newer candidate")
    queue = (await admin.get(f"{ADMIN}/trends", params={"status": "candidate"})).json()["items"]
    assert [item["id"] for item in queue] == [str(second), str(first)]
    assert not {"decided_by"} & keys(queue)
    detail = (await admin.get(f"{ADMIN}/trends/{first}")).json()
    assert (detail["named_orgs"], [s["excerpt_ref"] for s in detail["sources"]]) == (["GitHub"], ["tr-sec-001"])
    assert code(await developer.get(f"/api/me/trends/{first}")) == (404, "not_found")
    published = await admin.post(f"{ADMIN}/trends/{first}/decision", json={"decision": "publish"})
    assert published.status_code == 200, published.text
    assert (published.json()["status"], published.json()["published_at"] is not None) == ("published", True)
    assert code(await admin.post(f"{ADMIN}/trends/{first}/decision", json={"decision": "reject"})) == (
        409,
        "already_decided",
    )
    rejected = await admin.post(f"{ADMIN}/trends/{second}/decision", json={"decision": "reject"})
    assert rejected.json()["status"] == "rejected"
    assert code(await admin.post(f"{ADMIN}/trends/{uuid7()}/decision", json={"decision": "publish"})) == (
        404,
        "not_found",
    )
    assert (await developer.get(f"/api/me/trends/{first}")).status_code == 200
    assert (await developer.get(f"/api/me/trends/{second}")).status_code == 404
    [audited] = await audit_actions(week, first)
    assert (audited.action, audited.actor_kind, audited.actor_user_id, audited.org_id) == (
        "trend.card_decided",
        "staff",
        p.admin,
        None,
    )
    assert audited.payload == {"decision": "publish", "topic_slug": "security", "sources": 1}
    assert [r.status for r in await owner_rows(week, "SELECT status FROM trend_cards ORDER BY created_at")] == [
        "published",
        "rejected",
    ]


async def test_a_card_naming_someone_no_source_names_is_never_published(week: WeekDb, as_user: Clients) -> None:
    _, p = await setup(week)
    admin = await as_user(p.admin)
    declared = await trend_card(week, None, named_orgs=("Microsoft",))
    mentioned = await trend_card(
        week,
        None,
        summary="Unvalidated npm trusted publishing configurations now expire 48 hours after creation. Teams at"
        " Safaricom should validate a new setup soon after creating it.",
    )
    sourced = await trend_card(
        week,
        None,
        summary="Unvalidated npm trusted publishing configurations now expire 48 hours after creation. GitHub asks"
        " maintainers to validate a new setup soon after creating it.",
        sources=(trend_source(), trend_source(excerpt_ref="tr-sec-009", publisher="GitHub Docs")),
    )
    for card in (declared, mentioned):
        assert code(await admin.post(f"{ADMIN}/trends/{card}/decision", json={"decision": "publish"})) == (
            409,
            "unsourced_name",
        )
        assert (await admin.post(f"{ADMIN}/trends/{card}/decision", json={"decision": "reject"})).status_code == 200
    assert (await admin.post(f"{ADMIN}/trends/{sourced}/decision", json={"decision": "publish"})).status_code == 200


async def test_a_manual_run_queues_the_weekly_task_and_its_cards_can_be_published(
    week: WeekDb, as_user: Clients
) -> None:
    monday, p = await setup(week)
    admin = await as_user(p.admin)
    started = await admin.post(f"{ADMIN}/trend-runs")
    assert started.status_code == 202, started.text
    assert started.json()["task"] == "trends.draft"
    [job] = await owner_rows(
        week,
        "SELECT task_name, queue_name, lock, args FROM procrastinate_jobs WHERE id = :j",
        j=started.json()["job_id"],
    )
    assert (job.task_name, job.queue_name, job.lock) == ("trends.draft", "trends", "trends:draft")
    args = job.args if isinstance(job.args, dict) else json.loads(job.args)
    assert (args["user_id"], set(args)) == (str(p.admin), {"timestamp", "user_id"})
    stored = await run_weekly(
        WeeklyDeps(factory=create_session_factory(week.app), llm=lambda db: client("valid")),
        user_id=UUID(args["user_id"]),
    )
    assert isinstance(stored, Stored)
    assert stored.week_start == monday
    for card_id in stored.card_ids:  # the checks' cards pass the same rule on what is stored
        decided = await admin.post(f"{ADMIN}/trends/{card_id}/decision", json={"decision": "publish"})
        assert decided.status_code == 200, decided.text
    developer = await as_user(p.developer)
    week_out = (await developer.get("/api/me/week")).json()
    assert week_out["trend"]["id"] in {str(c) for c in stored.card_ids}
    assert week_out["trend"]["title"] in {fakes.SECURITY.title, fakes.DATABASES.title, fakes.KENYA.title}
    assert (await developer.get(f"/api/me/trends/{stored.card_ids[0]}")).json()["sources"][0]["publisher"] == "GitHub"
