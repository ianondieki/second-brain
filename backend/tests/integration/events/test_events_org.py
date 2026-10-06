"""REQ-DEV-02 (D-60; P22 card B test B2 and the tenancy rules, the organisation's half): ``/api/orgs/{org}/events``.

- The editors (owner, admin, signatory, reviewer) of an E2 organisation post drafts (201); finance and viewer 403; a
  non-member (another organisation's editor, a developer) 404; an E1 organisation 403 ``verification_required`` and a
  suspended one 403 ``org_unavailable``; the daily cap 429 ``events_daily_limit``. Each post is audited.
- The form: text cleaned, a start in the past, a span over 3 days, a place that is neither online nor a venue in a
  county, an unknown county or the country, and a link off the https rule are 422 ``invalid_event`` with the field.
- The poster edits their own draft only (403 ``not_poster``, 409 ``not_draft``); an editor cancels (409
  ``not_cancellable`` after); a member reads their organisation's events in any status and never another's; no read
  carries who posted or who decided.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any
from uuid import UUID

import pytest

from bridge.events import service
from bridge.events.policy import EventsPolicy
from bridge.ids import uuid7
from tests.integration.events.api_world import (
    MOMBASA,
    NAIROBI_CITY,
    Clients,
    WeekDb,
    at,
    audit_actions,
    body,
    cast,
    code,
    decide,
    nairobi,
    org_path,
    owner_rows,
    owner_run,
    post,
    published,
)


def keys(found: Any) -> set[str]:
    """Every key of a JSON body, at any depth."""
    if isinstance(found, dict):
        return set(found) | {k for v in found.values() for k in keys(v)}
    if isinstance(found, list):
        return {k for v in found for k in keys(v)}
    return set()


async def test_editors_of_an_e2_organisation_post_drafts_and_everyone_else_is_refused(
    week: WeekDb, as_user: Clients
) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    starts = nairobi(monday + timedelta(days=2), time(18, 0))
    made = []
    for editor in (p.org.owner, p.org.signatory, p.org.reviewer):
        response = await (await as_user(editor)).post(org_path(p.org.id), json=body(starts, county=NAIROBI_CITY))
        assert response.status_code == 201, response.text
        made.append(response.json())
    first = made[0]
    assert (first["status"], first["org_id"], first["organiser"]) == ("draft", str(p.org.id), p.org.name)
    place = (first["county_code"], first["county_name"], first["venue"])
    assert place == (NAIROBI_CITY, "Nairobi City", "iHub, Senteu Plaza")
    assert first["decided_at"] is None
    assert not {"created_by", "decided_by"} & keys(first)
    for refused in (p.org.finance, p.org.viewer):
        assert (await (await as_user(refused)).post(org_path(p.org.id), json=body(starts))).status_code == 403
    for stranger in (p.rival.owner, p.developer):
        assert (await (await as_user(stranger)).post(org_path(p.org.id), json=body(starts))).status_code == 404
    e1 = await as_user(p.e1.owner)
    assert code(await e1.post(org_path(p.e1.id), json=body(starts))) == (403, "verification_required")
    await owner_run(week, "UPDATE organizations SET suspended_at = now() WHERE id = :o", o=p.rival.id)
    rival = await as_user(p.rival.owner)
    assert code(await rival.post(org_path(p.rival.id), json=body(starts))) == (403, "org_unavailable")
    [audited] = await audit_actions(week, UUID(first["id"]))
    assert (audited.action, audited.actor_kind, audited.actor_user_id, audited.org_id) == (
        "event.created",
        "user",
        p.org.owner,
        p.org.id,
    )
    assert audited.payload == {"online": False, "platform": False}
    rows = await owner_rows(
        week, "SELECT created_by, status FROM events WHERE org_id = :o ORDER BY created_at", o=p.org.id
    )
    assert [(r.created_by, r.status) for r in rows] == [
        (p.org.owner, "draft"),
        (p.org.signatory, "draft"),
        (p.org.reviewer, "draft"),
    ]


async def test_an_organisation_posts_at_most_the_daily_cap(
    week: WeekDb, as_user: Clients, monkeypatch: pytest.MonkeyPatch
) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    monkeypatch.setattr(service, "get_events_policy", lambda: EventsPolicy(daily_posts=2))
    reviewer = await as_user(p.org.reviewer)
    starts = nairobi(monday + timedelta(days=3), time(9, 0))
    for _ in range(2):
        assert (await reviewer.post(org_path(p.org.id), json=body(starts))).status_code == 201
    assert code(await reviewer.post(org_path(p.org.id), json=body(starts))) == (429, "events_daily_limit")
    await at(week, monday + timedelta(days=1), time(0, 5))  # a new Nairobi day
    assert (await reviewer.post(org_path(p.org.id), json=body(starts))).status_code == 201


@pytest.mark.parametrize(
    ("changes", "field", "error"),
    [
        ({"starts_at": "past"}, "starts_at", "start_past"),
        ({"ends_at": "4 days"}, "ends_at", "span_too_long"),
        ({"ends_at": "before"}, "ends_at", "end_before_start"),
        ({"join_url": None}, "join_url", "join_url_required"),
        ({"county_code": NAIROBI_CITY}, "county_code", "online_has_place"),
        ({"online": False, "venue": "iHub", "join_url": None}, "county_code", "county_required"),
        ({"online": False, "county_code": NAIROBI_CITY, "join_url": None}, "venue", "venue_required"),
        ({"online": False, "venue": "iHub", "county_code": "KE-99", "join_url": None}, "county_code", "unknown_county"),
        ({"online": False, "venue": "iHub", "county_code": "KE", "join_url": None}, "county_code", "unknown_county"),
        ({"title": chr(0x200B) + chr(0x202E) + " "}, "title", "blank"),
        ({"description": "Bell \x07 here"}, "description", "control_character"),
        ({"link": "http://example.com/x"}, "link", "invalid_url"),
        ({"join_url": "https://user@meet.example.test/x"}, "join_url", "invalid_url"),
        ({"title": "t" * 121}, "title", "too_long"),
    ],
)
async def test_the_form_is_checked_field_by_field(
    week: WeekDb, as_user: Clients, changes: dict[str, Any], field: str, error: str
) -> None:
    monday = week.shared_monday()
    await at(week, monday)
    p = await cast(week)
    starts = nairobi(monday + timedelta(days=1), time(10, 0))
    sent = body(starts) | changes
    if changes.get("starts_at") == "past":
        sent["starts_at"] = (starts - timedelta(days=2)).isoformat()
    if changes.get("ends_at") == "4 days":
        sent["ends_at"] = (starts + timedelta(days=3, minutes=1)).isoformat()
    if changes.get("ends_at") == "before":
        sent["ends_at"] = starts.isoformat()
    response = await (await as_user(p.org.reviewer)).post(org_path(p.org.id), json=sent)
    assert code(response) == (422, "invalid_event"), response.text
    assert (field, error) in {(e["field"], e["code"]) for e in response.json()["detail"]["errors"]}
    assert await owner_rows(week, "SELECT id FROM events WHERE org_id = :o", o=p.org.id) == []


async def test_text_is_cleaned_and_times_are_stored_in_utc(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    starts = nairobi(monday + timedelta(days=1), time(10, 0))
    sent = body(starts, title=f"  Rust{chr(0x200B)}  night {chr(0x202E)}", link="https://rust.example.test/night")
    created = (await (await as_user(p.org.owner)).post(org_path(p.org.id), json=sent)).json()
    assert created["title"] == "Rust night"
    assert created["link"] == "https://rust.example.test/night"
    [row] = await owner_rows(week, "SELECT starts_at, title FROM events WHERE id = :e", e=created["id"])
    assert row.starts_at == starts
    assert row.title == "Rust night"


async def test_the_poster_edits_their_own_draft_until_it_is_decided(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    starts = nairobi(monday + timedelta(days=2), time(18, 0))
    reviewer, owner = await as_user(p.org.reviewer), await as_user(p.org.owner)
    created = (await reviewer.post(org_path(p.org.id), json=body(starts))).json()
    path = org_path(p.org.id, f"/{created['id']}")
    edited = await reviewer.put(path, json=body(starts, title="Nairobi Rust meetup", county=MOMBASA))
    assert edited.status_code == 200, edited.text
    assert (edited.json()["title"], edited.json()["county_code"], edited.json()["online"]) == (
        "Nairobi Rust meetup",
        MOMBASA,
        False,
    )
    assert code(await owner.put(path, json=body(starts))) == (403, "not_poster")
    await decide(week, UUID(created["id"]), p.moderator)
    assert code(await reviewer.put(path, json=body(starts))) == (409, "not_draft")
    assert code(await reviewer.put(org_path(p.org.id, f"/{uuid7()}"), json=body(starts))) == (404, "not_found")
    actions = [a.action for a in await audit_actions(week, UUID(created["id"]))]
    assert actions[:2] == ["event.created", "event.updated"]


async def test_an_editor_cancels_and_members_read_their_own_events_only(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    starts = nairobi(monday + timedelta(days=2), time(18, 0))
    live = await published(week, p, starts)
    draft = await post(week, p.org.signatory, p.org.id, starts + timedelta(days=1))
    theirs = await post(week, p.rival.owner, p.rival.id, starts)
    viewer, owner = await as_user(p.org.viewer), await as_user(p.org.owner)
    listed = (await viewer.get(org_path(p.org.id))).json()
    assert [item["id"] for item in listed["items"]] == [str(draft), str(live)]  # newest first, any status
    assert [item["status"] for item in listed["items"]] == ["draft", "published"]
    assert not {"created_by", "decided_by"} & keys(listed)
    assert (await viewer.get(org_path(p.org.id, f"/{draft}"))).json()["status"] == "draft"
    assert (await viewer.get(org_path(p.org.id, f"/{theirs}"))).status_code == 404
    assert (await viewer.get(org_path(p.rival.id))).status_code == 404
    assert (await viewer.post(org_path(p.org.id, f"/{live}/cancel"))).status_code == 403
    assert (await owner.post(org_path(p.org.id, f"/{theirs}/cancel"))).status_code == 404
    cancelled = await owner.post(org_path(p.org.id, f"/{live}/cancel"))
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancelled_at"] is not None
    assert code(await owner.post(org_path(p.org.id, f"/{live}/cancel"))) == (409, "not_cancellable")
    [*_, last] = await audit_actions(week, live)
    assert (last.action, last.actor_user_id, last.org_id, last.payload["was"]) == (
        "event.cancelled",
        p.org.owner,
        p.org.id,
        "published",
    )
