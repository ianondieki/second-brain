"""Demo seed steps for This week (P22 track B; REQ-DEV-02; D-60, D-61), so Home's strip, ``/dev/week``, the event
page, ``/admin/events``, the organisation's Events and the research page's trends have something to show on ``make
demo``. Part of ``python -m bridge.seed --demo``, after the quiz.

- **Four events** on the shared clock (``DEMO_EVENTS``, days counted from today in Nairobi), each posted through the API
  by its poster signed in as themselves and, except the draft, published by the demo staff admin through
  ``POST /api/admin/events/{id}/decision`` on the version read: Telco A's reviewer posts one at a venue in Nairobi City
  (Amina's county), the staff admin an online "Platform" one, SACCO B's reviewer one in Machakos (another county, so
  the strip's filter shows) and a draft left on the queue. When the Nairobi event is made, Amina (who has no county in
  the dataset) gets Nairobi City on her profile through ``PATCH /api/me/profile`` if hers is still empty, and presses
  Remind me on it (``POST /api/me/events/{id}/reminder``).
- **Three trend cards** written by hand below (``SEEDED_TRENDS``) from the saved excerpts of
  ``backend/seed/trend_excerpts.yaml``, through the trends' checks in code (``check_answer``), stored through
  ``app_create_trend_candidate`` as the owner role (no user bound, as the weekly job) with no generating call (so they
  are seeded examples, never labelled AI-drafted), and two of them published by the demo staff admin through ``POST
  /api/admin/research/trends/{id}/decision`` (the named-organisation rule on what is stored, then
  ``app_decide_trend_card``, audited); the third waits on the queue. No model is called.

Idempotent and safe on a used demo (P9's rules): an event whose title has an event that has not ended (any status:
someone may have cancelled it in the app) gets nothing new, and once all of them ended a new run posts them again on
the new days; a trend card whose title exists gets nothing new (a seeded candidate meant to be published, left by a
run that stopped, is published); Amina's county is set only when empty, and her reminder only in the run that made the
event.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.engagements.calendar import NAIROBI
from bridge.models.enums import OrgRole
from bridge.problems.research.checks import Citation
from bridge.problems.research.policy import get_research_policy
from bridge.problems.research.sources import TECH, CatalogueKind, Freshness, freshness, get_catalogue
from bridge.problems.trends.checks import AnswerDraft, TrendDraft, check_answer
from bridge.problems.trends.policy import get_trends_policy
from bridge.problems.trends.run import candidate
from bridge.problems.trends.store import card_json
from bridge.seed.demo.data import AMINA, SACCO_B, STAFF_ADMIN, TELCO_A, DemoOrg
from bridge.seed.demo.runtime import Actors, DemoReport, DemoSeedError, _one

NAIROBI_CITY: Final = "KE-30"


def _reviewer(org: DemoOrg) -> str:
    [seat] = [seat for seat in org.seats if OrgRole.REVIEWER in seat.roles]
    return seat.email


@dataclass(frozen=True, slots=True)
class DemoEvent:
    key: str
    title: str
    description: str
    poster: str  # an editor of ``org``, or the staff admin for a platform event
    org: str | None  # the organisation's legal name; None: the platform's
    day: int  # days after today in Nairobi
    start: time
    hours: float
    county: str | None  # None: online
    venue: str | None
    join_url: str | None
    link: str | None = None
    publish: bool = True  # False: left a draft on the staff queue
    reminded_by: str | None = None  # the developer who presses Remind me when it is made


DEMO_EVENTS: Final = (
    DemoEvent(
        key="nairobi",
        title="Nairobi mobile money developers meetup (demo)",
        description="Short talks on building with mobile money APIs, then open questions.\nBring a laptop.",
        poster=_reviewer(TELCO_A),
        org=TELCO_A.legal_name,
        day=2,
        start=time(18, 0),
        hours=2.5,
        county=NAIROBI_CITY,
        venue="Telco A Innovation Hub, Westlands (demo)",
        join_url=None,
        link="https://events.telco-a.example/meetup",
        reminded_by=AMINA.email,
    ),
    DemoEvent(
        key="online",
        title="Secure package publishing clinic, online (demo)",
        description="A one-hour clinic on publishing packages safely: trusted publishing, tokens and reviews.",
        poster=STAFF_ADMIN.email,
        org=None,
        day=4,
        start=time(10, 0),
        hours=1.5,
        county=None,
        venue=None,
        join_url="https://meet.example/demo-publishing-clinic",
    ),
    DemoEvent(
        key="machakos",
        title="Machakos SACCO builders evening (demo)",
        description="SACCO staff and developers compare notes on member apps and USSD services.",
        poster=_reviewer(SACCO_B),
        org=SACCO_B.legal_name,
        day=3,
        start=time(17, 0),
        hours=2,
        county="KE-22",
        venue="SACCO B Hall, Machakos (demo)",
        join_url=None,
    ),
    DemoEvent(
        key="draft",
        title="Data protection for app builders, online (demo)",
        description="What the Data Protection Act asks of an app that stores members' details.",
        poster=_reviewer(SACCO_B),
        org=SACCO_B.legal_name,
        day=6,
        start=time(9, 0),
        hours=3,
        county=None,
        venue=None,
        join_url="https://meet.example/demo-data-protection",
        publish=False,
    ),
)

# Written by hand from the saved excerpts (backend/seed/trend_excerpts.yaml): every figure is in a cited quote and every
# organisation named is a cited publisher; the checks in code verify both on every seed run.
SEEDED_TRENDS: Final = (
    TrendDraft(
        title="Unvalidated npm trusted publishing configurations now expire",
        summary="Unvalidated npm trusted publishing configurations now expire 48 hours after creation and can no"
        " longer authorize publishing. Developers in Kenya who publish npm packages should validate a new trusted"
        " publishing setup soon after creating it.",
        topic_slug="security",
        named_orgs=("GitHub",),
        citations=(Citation("tr-sec-001", "now expire 48 hours after creation"),),
    ),
    TrendDraft(
        title="pgvector 0.8.7 is now available with a buffer overflow fix",
        summary="pgvector 0.8.7 is now available. This release fixes a buffer overflow with IVFFlat index builds,"
        " which can lead to arbitrary code execution. Teams that use pgvector for search in their apps should plan"
        " the upgrade.",
        topic_slug="databases",
        named_orgs=(),
        citations=(Citation("tr-dat-002", "fixes a buffer overflow with IVFFlat index builds"),),
    ),
    TrendDraft(
        title="New licence conditions published in the Kenya Gazette",
        summary="The new licence conditions were published in the Kenya Gazette on August 7, 2026. They take effect"
        " on September 7, following the statutory 30-day period. Developers in Kenya whose services fall under them"
        " should read the conditions.",
        topic_slug="kenya-ict",
        named_orgs=(),
        citations=(Citation("tr-ke-002", "will take effect on September 7, following the statutory 30-day period"),),
    ),
)
PUBLISHED_TRENDS: Final = frozenset({"security", "databases"})  # the third waits on the queue

_TODAY: Final = "SELECT app_nairobi_today() AS today"
_LIVE_EVENT: Final = (
    "SELECT id, status FROM events WHERE title = :title AND ends_at > app_clock_now() ORDER BY created_at DESC LIMIT 1"
)
_COUNTY: Final = "SELECT county_code FROM developer_profiles WHERE user_id = :u"
_CARD: Final = "SELECT id, status FROM trend_cards WHERE title = :title ORDER BY created_at LIMIT 1"
_CREATE_CARD: Final = "SELECT app_create_trend_candidate(CAST(:card AS jsonb), CAST(:sources AS jsonb)) AS id"


async def nairobi_today(owner: AsyncEngine) -> date:
    found: date = (await _one(owner, _TODAY)).today
    return found


def event_body(plan: DemoEvent, today: date) -> dict[str, Any]:
    starts = datetime.combine(today + timedelta(days=plan.day), plan.start, tzinfo=NAIROBI)
    return {
        "title": plan.title,
        "description": plan.description,
        "starts_at": starts.isoformat(),
        "ends_at": (starts + timedelta(hours=plan.hours)).isoformat(),
        "online": plan.county is None,
        "venue": plan.venue,
        "county_code": plan.county,
        "join_url": plan.join_url,
        "link": plan.link,
    }


async def ensure_event(owner: AsyncEngine, actors: Actors, plan: DemoEvent, report: DemoReport) -> None:
    """``plan``'s event, posted and decided through the API, unless one of its title has not ended (module
    docstring)."""
    if STAFF_ADMIN.email not in report.users:
        raise DemoSeedError(f"no demo staff admin {STAFF_ADMIN.email} to decide the events")
    if await _one(owner, _LIVE_EVENT, title=plan.title) is not None:
        return
    poster = await actors.get(plan.poster)
    if plan.org is None:
        path = "/api/admin/events"
    else:
        org_id = report.orgs.get(plan.org)
        if org_id is None:
            raise DemoSeedError(f"{plan.org} is not there to post {plan.key}")
        path = f"/api/orgs/{org_id}/events"
    body = event_body(plan, await nairobi_today(owner))
    event_id = (await poster.call("POST", path, json=body, expect=(201,))).json()["id"]
    report.did(f"event {plan.key}: {plan.title}")
    if plan.publish:
        admin = await actors.get(STAFF_ADMIN.email)
        seen = (await admin.call("GET", f"/api/admin/events/{event_id}")).json()["updated_at"]
        decision = {"decision": "publish", "seen": seen}
        await admin.call("POST", f"/api/admin/events/{event_id}/decision", json=decision)
        report.did(f"event {plan.key} published by {STAFF_ADMIN.email}")
    if plan.reminded_by is not None:
        await _remind(owner, actors, plan, UUID(event_id), report)


async def _remind(owner: AsyncEngine, actors: Actors, plan: DemoEvent, event_id: UUID, report: DemoReport) -> None:
    """The developer's county (when empty: the event's) and their Remind me, in the run that made the event."""
    assert plan.reminded_by is not None
    user_id = report.users.get(plan.reminded_by)
    if user_id is None:
        raise DemoSeedError(f"{plan.reminded_by} is not there to be reminded")
    developer = await actors.get(plan.reminded_by)
    found = await _one(owner, _COUNTY, u=user_id)
    if found is not None and found.county_code is None and plan.county is not None:
        await developer.call("PATCH", "/api/me/profile", json={"county_code": plan.county})
        report.did(f"county of {plan.reminded_by}: {plan.county}")
    await developer.call("POST", f"/api/me/events/{event_id}/reminder", expect=(201,))
    report.did(f"reminder of {plan.reminded_by} on {plan.key}")


async def ensure_trends(owner: AsyncEngine, actors: Actors, report: DemoReport) -> None:
    """The three hand-written trend cards, two of them published by the demo staff admin (module docstring)."""
    if STAFF_ADMIN.email not in report.users:
        raise DemoSeedError(f"no demo staff admin {STAFF_ADMIN.email} to decide the trend cards")
    today = await nairobi_today(owner)
    catalogue, policy = get_catalogue(CatalogueKind.TRENDS), get_trends_policy()
    scoring = policy.scoring(get_research_policy())
    sent = {e.id: e for e in catalogue.excerpts if freshness(e, today, scoring) is not Freshness.ARCHIVED}
    answer = AnswerDraft(False, SEEDED_TRENDS)
    verdict = check_answer(answer, sent, catalogue.allowlists[TECH], scoring, today, max_cards=len(SEEDED_TRENDS))
    if verdict.refused is not None or len(verdict.kept) != len(SEEDED_TRENDS):
        raise DemoSeedError(f"the seeded trend cards fail the checks: {[r.value for r in verdict.discarded]}")
    for kept in verdict.kept:
        found = await _one(owner, _CARD, title=kept.title)
        if found is None:
            stored = candidate(kept, "seeded")
            card = json.loads(card_json(stored))
            card["llm_trace_id"] = None  # no generating call: a seeded example, never labelled AI-drafted
            params = {"card": json.dumps(card), "sources": json.dumps(stored.p_sources())}
            async with owner.begin() as conn:
                created = await conn.execute(text(_CREATE_CARD), params)
                card_id, status = UUID(str(created.scalar_one())), "candidate"
            report.did(f"trend card {kept.topic_slug}: {kept.title}")
        else:
            card_id, status = UUID(str(found.id)), str(found.status)
        if kept.topic_slug in PUBLISHED_TRENDS and status == "candidate":
            admin = await actors.get(STAFF_ADMIN.email)
            path = f"/api/admin/research/trends/{card_id}/decision"
            await admin.call("POST", path, json={"decision": "publish"})
            report.did(f"trend card {kept.topic_slug} published by {STAFF_ADMIN.email}")


__all__ = ["DEMO_EVENTS", "SEEDED_TRENDS", "DemoEvent", "ensure_event", "ensure_trends"]
