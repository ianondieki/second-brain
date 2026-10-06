"""REQ-DEV-02, REQ-ADM-01 (D-60; P22 card B tests B1 and B2, the staff half): ``/api/admin/events``.

- Staff with a fresh second factor only: signed out, a developer and an organisation's member 404; a moderator may read
  and decide but not post a platform event (403); a stale second factor 403 ``step_up_required``.
- A staff admin posts a platform event ("Platform"), a draft on the queue like any other; a moderator publishes it on
  the version read, once (409 ``already_decided``), audited ``event.decided`` on the staff member's chain.
- A draft edited after it was read is 409 ``changed_since_review``; an event that ended is only rejected (409
  ``event_over``); an organisation that is no longer E2, or is suspended or delisted, has nothing published (409
  ``organisation_unavailable``; rejecting stays open). Staff cancel, audited.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any
from uuid import UUID

from bridge.ids import uuid7
from tests.integration.api import make_client
from tests.integration.events.api_world import (
    ADMIN,
    Clients,
    WeekDb,
    at,
    audit_actions,
    body,
    cast,
    code,
    nairobi,
    org_path,
    owner_run,
    post,
)

ROUTES: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("GET", "", None),
    ("GET", f"/{uuid7()}", None),
    ("POST", f"/{uuid7()}/decision", {"decision": "publish", "seen": "2026-10-06T10:00:00+03:00"}),
    ("POST", f"/{uuid7()}/cancel", None),
)


async def seen(client: Any, event_id: UUID) -> str:
    response = await client.get(f"{ADMIN}/{event_id}")
    assert response.status_code == 200, response.text
    found: str = response.json()["updated_at"]
    return found


async def decide(client: Any, event_id: UUID, decision: str, at_version: str) -> Any:
    return await client.post(f"{ADMIN}/{event_id}/decision", json={"decision": decision, "seen": at_version})


async def test_every_route_is_staff_only_with_a_fresh_second_factor(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    starts = nairobi(monday + timedelta(days=2), time(18, 0))
    developer, member = await as_user(p.developer), await as_user(p.org.owner)
    moderator, stale = await as_user(p.moderator), await as_user(p.admin, fresh=False)
    async with make_client(week.app) as anonymous:
        assert (await anonymous.post(ADMIN, json=body(starts))).status_code == 404
        for method, path, sent in ROUTES:
            assert (await anonymous.request(method, ADMIN + path, json=sent)).status_code == 404, path
    for method, path, sent in (*ROUTES, ("POST", "", body(starts))):
        assert (await developer.request(method, ADMIN + path, json=sent)).status_code == 404, path
        assert (await member.request(method, ADMIN + path, json=sent)).status_code == 404, path
        assert code(await stale.request(method, ADMIN + path, json=sent)) == (403, "step_up_required"), path
    assert (await moderator.post(ADMIN, json=body(starts))).status_code == 403
    assert (await moderator.get(ADMIN)).status_code == 200


async def test_a_platform_event_waits_on_the_queue_and_is_decided_once(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    admin, moderator, developer = await as_user(p.admin), await as_user(p.moderator), await as_user(p.developer)
    created = await admin.post(ADMIN, json=body(nairobi(monday + timedelta(days=4), time(10, 0))))
    assert created.status_code == 201, created.text
    event = created.json()
    assert (event["org_id"], event["organiser"], event["status"]) == (None, "Platform", "draft")
    event_id = UUID(event["id"])
    queue = (await moderator.get(ADMIN, params={"status": "draft"})).json()["items"]
    assert [item["id"] for item in queue] == [str(event_id)]
    assert (await moderator.get(ADMIN, params={"status": "published"})).json()["items"] == []
    version = await seen(moderator, event_id)
    assert (await decide(developer, event_id, "publish", version)).status_code == 404
    decided = await decide(moderator, event_id, "publish", version)
    assert decided.status_code == 200, decided.text
    assert (decided.json()["status"], decided.json()["decided_at"] is not None) == ("published", True)
    assert code(await decide(moderator, event_id, "reject", await seen(moderator, event_id))) == (
        409,
        "already_decided",
    )
    assert code(await decide(moderator, uuid7(), "publish", version)) == (404, "not_found")
    actions = await audit_actions(week, event_id)
    assert [(a.action, a.actor_kind, a.actor_user_id) for a in actions] == [
        ("event.created", "staff", p.admin),
        ("event.decided", "staff", p.moderator),
    ]
    assert actions[1].org_id is None
    assert actions[1].payload == {"decision": "publish", "org_id": None, "online": True}


async def test_a_draft_edited_after_it_was_read_is_reviewed_again(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    starts = nairobi(monday + timedelta(days=2), time(18, 0))
    reviewer, moderator = await as_user(p.org.reviewer), await as_user(p.moderator)
    event_id = UUID((await reviewer.post(org_path(p.org.id), json=body(starts))).json()["id"])
    read = await seen(moderator, event_id)
    await at(week, monday, time(12, 5))
    edited = await reviewer.put(org_path(p.org.id, f"/{event_id}"), json=body(starts, title="Changed after review"))
    assert edited.status_code == 200, edited.text
    assert code(await decide(moderator, event_id, "publish", read)) == (409, "changed_since_review")
    assert code(await decide(moderator, event_id, "reject", read)) == (409, "changed_since_review")
    again = await decide(moderator, event_id, "publish", await seen(moderator, event_id))
    assert (again.status_code, again.json()["title"]) == (200, "Changed after review")


async def test_an_event_that_ended_is_rejected_not_published(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    event_id = await post(week, p.org.reviewer, p.org.id, nairobi(monday, time(14, 0)))
    moderator = await as_user(p.moderator)
    await at(week, monday, time(16, 30))  # it ended at 16:00
    version = await seen(moderator, event_id)
    assert code(await decide(moderator, event_id, "publish", version)) == (409, "event_over")
    rejected = await decide(moderator, event_id, "reject", version)
    assert (rejected.status_code, rejected.json()["status"]) == (200, "rejected")


async def test_an_unavailable_organisation_has_nothing_published(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    starts = nairobi(monday + timedelta(days=3), time(9, 0))
    moderator = await as_user(p.moderator)
    events = [await post(week, p.org.reviewer, p.org.id, starts + timedelta(hours=n)) for n in range(3)]
    for change, event_id in zip(
        ("suspended_at = now()", "delisted_at = now()", "verification = 'e1'"), events, strict=True
    ):
        await owner_run(week, f"UPDATE organizations SET {change} WHERE id = :o", o=p.org.id)
        version = await seen(moderator, event_id)
        assert code(await decide(moderator, event_id, "publish", version)) == (409, "organisation_unavailable")
        assert (await decide(moderator, event_id, "reject", version)).status_code == 200
        await owner_run(
            week,
            "UPDATE organizations SET suspended_at = NULL, delisted_at = NULL, verification = 'e2' WHERE id = :o",
            o=p.org.id,
        )


async def test_staff_cancel_a_published_event(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    moderator = await as_user(p.moderator)
    event_id = await post(week, p.org.reviewer, p.org.id, nairobi(monday + timedelta(days=1), time(9, 0)))
    assert (await decide(moderator, event_id, "publish", await seen(moderator, event_id))).status_code == 200
    cancelled = await moderator.post(f"{ADMIN}/{event_id}/cancel")
    assert (cancelled.status_code, cancelled.json()["status"]) == (200, "cancelled")
    assert code(await moderator.post(f"{ADMIN}/{event_id}/cancel")) == (409, "not_cancellable")
    assert code(await moderator.post(f"{ADMIN}/{uuid7()}/cancel")) == (404, "not_found")
    [*_, last] = await audit_actions(week, event_id)
    assert (last.action, last.actor_kind, last.actor_user_id, last.org_id) == (
        "event.cancelled",
        "staff",
        p.moderator,
        None,
    )
    assert last.payload == {"was": "published", "org_id": str(p.org.id)}
