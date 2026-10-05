"""REQ-PERS-03 (R27), REQ-TREND-02 (R18), P21 track C, D-57 (7): the daily saved-search alerts on the shared clock.

- P21-C3: the job notifies once per saved search with the count of what Discover lists for its view and filters that
  was published since the search was saved (then since the last alert), none when zero, never twice for one item; a
  re-run the same day sends nothing (``last_alerted_at`` moved in the notification's transaction).
- P21-C4: a search with alerts off, or deleted, sends nothing; turned back on, it alerts again.
- P21-C5: only published, visible items count: a held or unpublished problem, a closed Brief or one past its deadline
  never does; the Briefs view counts open Briefs only.
- P21-C6: the digest email is opt-in (off by default, settable on the notification settings API); when on, one email
  a day listing the searches' names and counts, never an item's text.

The job runs over this test's developer only (``user_ids``): other tests' searches live in the same database. Items
are written relative to ``app_clock_now()`` (``trend_world``), and each test's niches are its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.db import create_session_factory
from bridge.matching.saved_search_alerts import AlertDeps, Report, run_alerts
from bridge.matching.trending import NAIROBI, nairobi_day
from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import clients
from tests.integration.matching.trend_world import TrendWorld, brief, build, research_card
from tests.integration.proposals.helpers import Developers, rows, user_of

URL = "/api/me/saved-searches"
PREFERENCES = "/api/me/notification-preferences"
NAKURU = "KE-32"
SECRET_TITLE = "Grain silos in Nakuru overheat"
SECRET_STATEMENT = "Farmers in Nakuru lose stored grain when the silos overheat at night."


@dataclass(frozen=True, slots=True)
class Rig:
    world: TrendWorld
    me: httpx.AsyncClient
    deps: AlertDeps

    @property
    def user(self) -> UUID:
        return user_of(self.me)

    @property
    def outbox(self) -> FakeEmailProvider:
        provider = self.deps.email
        assert isinstance(provider, FakeEmailProvider)
        return provider

    async def run(self, now: datetime | None = None) -> Report:
        return await run_alerts(self.deps, now=now, user_ids=[self.user])


async def rig(developers: Developers, owner_engine: AsyncEngine, app_engine: AsyncEngine) -> Rig:
    world = await build(owner_engine)  # seeds the counties too
    deps = AlertDeps(create_session_factory(app_engine), get_settings(), FakeEmailProvider())
    return Rig(world, await developers(), deps)


async def save(r: Rig, owner_engine: AsyncEngine, name: str, view: str = "problems", **filters: Any) -> str:
    """Save a search through the API, then date its saving three days back (items of the last days are new to it)."""
    response = await r.me.post(URL, json={"name": name, "view": view, **filters})
    assert response.status_code == 201, response.text
    search_id: str = response.json()["id"]
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE saved_searches SET created_at = app_clock_now() - interval '3 days' WHERE id = :id"),
            {"id": UUID(search_id)},
        )
    return search_id


async def notices(owner_engine: AsyncEngine, user: UUID) -> list[tuple[str, str | None, str | None]]:
    found = await rows(
        owner_engine,
        "SELECT title, body, link FROM in_app_notifications WHERE user_id = :u AND kind = 'saved_search_match'"
        " ORDER BY created_at, title",
        u=user,
    )
    return [(row.title, row.body, row.link) for row in found]


def counts(report: Report, user: UUID) -> dict[UUID, int]:
    outcome = report.of(user)
    assert outcome is not None
    assert not outcome.error
    return {alert.search_id: alert.count for alert in outcome.alerts}


async def test_p21_c3_one_notice_per_search_with_its_new_count_and_never_twice(
    developers: Developers, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    r = await rig(developers, owner_engine, app_engine)
    w = r.world
    grain = await save(r, owner_engine, "Grain in Nakuru", niche=w.slug("parent"), county=NAKURU)
    transport = await save(r, owner_engine, "Transport", niche=w.slug("elsewhere"))
    briefs = await save(r, owner_engine, "Farming Briefs", "briefs", niche=w.slug("parent"))
    await research_card(owner_engine, w.niche, county=NAKURU, age_days=1)
    await research_card(owner_engine, w.sibling, county=NAKURU, age_days=2)  # the parent includes its children
    await research_card(owner_engine, w.niche, county="KE-30", age_days=1)  # another county
    await research_card(owner_engine, w.niche, county=NAKURU, age_days=5)  # before the search was saved
    await brief(owner_engine, w.niche, age_days=1)  # no county: the Briefs view's

    first = await r.run()
    assert counts(first, r.user) == {UUID(grain): 2, UUID(transport): 0, UUID(briefs): 1}
    assert await notices(owner_engine, r.user) == [
        ("1 new Brief matches Farming Briefs", None, f"/dev/discover?view=briefs&niche={w.slug('parent')}"),
        ("2 new problems match Grain in Nakuru", None, f"/dev/discover?niche={w.slug('parent')}&county={NAKURU}"),
    ]
    stamped = await rows(owner_engine, "SELECT last_alerted_at FROM saved_searches WHERE user_id = :u", u=r.user)
    assert {row.last_alerted_at for row in stamped} == {first.now}  # every decided search, matches or not

    again = await r.run()  # the same day: nothing is due any more
    assert again.of(r.user) is None
    assert len(await notices(owner_engine, r.user)) == 2

    await research_card(owner_engine, w.niche, county=NAKURU, age_days=-0.5)  # after the first run
    tomorrow = await r.run(first.now + timedelta(days=1))
    assert counts(tomorrow, r.user) == {UUID(grain): 1, UUID(transport): 0, UUID(briefs): 0}  # never twice
    assert (await notices(owner_engine, r.user))[-1][0] == "1 new problem matches Grain in Nakuru"
    assert len(await notices(owner_engine, r.user)) == 3
    assert r.outbox.outbox == []  # the digest email is off by default


async def test_p21_c4_alerts_off_and_deleted_searches_send_nothing(
    developers: Developers, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    r = await rig(developers, owner_engine, app_engine)
    w = r.world
    quiet = await save(r, owner_engine, "Quiet", niche=w.slug("parent"))
    gone = await save(r, owner_engine, "Gone", niche=w.slug("niche"))
    await research_card(owner_engine, w.niche, age_days=1)
    assert (await r.me.patch(f"{URL}/{quiet}", json={"alerts": False})).status_code == 200
    assert (await r.me.delete(f"{URL}/{gone}")).status_code == 204

    report = await r.run()
    assert report.of(r.user) is None
    assert await notices(owner_engine, r.user) == []
    [row] = await rows(owner_engine, "SELECT last_alerted_at FROM saved_searches WHERE id = :id", id=UUID(quiet))
    assert row.last_alerted_at is None

    # Turned back on, the window restarts then: what came out while alerts were off is never counted.
    await research_card(owner_engine, w.niche, age_days=0.5)  # published while off
    renamed = await r.me.patch(f"{URL}/{quiet}", json={"name": "Quiet again"})  # alerts untouched: no reset
    assert renamed.json()["last_alerted_at"] is None
    back_on = await r.me.patch(f"{URL}/{quiet}", json={"alerts": True})
    assert back_on.status_code == 200
    [clock] = await rows(owner_engine, "SELECT app_clock_now() AS now")
    reset = datetime.fromisoformat(back_on.json()["last_alerted_at"])
    assert timedelta(0) <= clock.now - reset < timedelta(minutes=1)
    again = await r.me.patch(f"{URL}/{quiet}", json={"alerts": True})  # already on: the window stays
    assert again.json()["last_alerted_at"] == back_on.json()["last_alerted_at"]
    assert (await r.run()).of(r.user) is None  # alerted (re-enabled) today: nothing due until tomorrow
    await research_card(owner_engine, w.niche, age_days=-0.1)  # published after alerts came back on
    assert counts(await r.run(clock.now + timedelta(days=1)), r.user) == {UUID(quiet): 1}
    assert [title for title, _, _ in await notices(owner_engine, r.user)] == ["1 new problem matches Quiet again"]


async def test_the_counts_hold_the_saved_words_as_typed_in_both_views(
    developers: Developers, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The saved words narrow the count exactly as Discover's words filter does: title or statement, ignoring case,
    ``%`` and ``_`` taken as typed (a LIKE wildcard would also match the look-alike items)."""
    r = await rig(developers, owner_engine, app_engine)
    w = r.world
    typed = await save(r, owner_engine, "Typed", niche=w.slug("parent"), words="CHAIN_100%")
    milk = await save(r, owner_engine, "Milk", niche=w.slug("parent"), words="milk")
    stated = await save(r, owner_engine, "Stated", niche=w.slug("parent"), words="silo doors")
    briefs = await save(r, owner_engine, "Typed Briefs", "briefs", niche=w.slug("parent"), words="chain_100%")
    await research_card(owner_engine, w.niche, title="Milk chain_100% spoilage")
    await research_card(owner_engine, w.sibling, title="Milk chainX100Y spoilage")  # wildcards would match it
    await research_card(owner_engine, w.niche, title="Grain pests", statement="Weevils get past the SILO DOORS.")
    await brief(owner_engine, w.niche, title="Depot chain_100% audit")
    await brief(owner_engine, w.sibling, title="Depot chainX100Y audit")
    await brief(owner_engine, w.niche, title="Depot counts")
    # The Problems view lists Briefs as problems too: "Typed" counts the card and the Brief holding the words, never
    # the look-alikes; without the words each problems search would count all six.
    assert counts(await r.run(), r.user) == {UUID(typed): 2, UUID(milk): 2, UUID(stated): 1, UUID(briefs): 1}


async def test_the_problems_count_is_capped_at_what_the_page_lists(
    developers: Developers, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The Problems view lists a problem only while it trends or is New this week (7 days), so an alert never counts an
    older one, however long ago the last alert was; the Briefs view lists every open Brief, so its count is uncapped."""
    r = await rig(developers, owner_engine, app_engine)
    w = r.world
    problems = await save(r, owner_engine, "Problems", niche=w.slug("parent"))
    briefs = await save(r, owner_engine, "Briefs", "briefs", niche=w.slug("parent"))
    async with owner_engine.begin() as conn:  # saved (and last alerted) three weeks ago
        await conn.execute(
            text("UPDATE saved_searches SET created_at = app_clock_now() - interval '21 days' WHERE user_id = :u"),
            {"u": r.user},
        )
    old = await research_card(owner_engine, w.niche, age_days=10)  # since the last alert, but no longer new
    await research_card(owner_engine, w.niche, age_days=2)
    await brief(owner_engine, w.niche, age_days=10)
    await brief(owner_engine, w.niche, age_days=2)
    async with clients(app_engine, get_settings(), r.user) as (viewer,):
        listed = (await viewer.get("/api/discover/trending", params={"niche": w.slug("parent")})).json()
    assert str(old) not in {item["problem"]["id"] for item in listed["problems"]}  # what the notice's link shows
    # Problems: the card and the Brief of 2 days ago (the Problems view lists Briefs too); Briefs: both Briefs.
    assert counts(await r.run(), r.user) == {UUID(problems): 2, UUID(briefs): 2}


async def test_p21_c5_only_published_visible_items_count(
    developers: Developers, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    r = await rig(developers, owner_engine, app_engine)
    w = r.world
    problems = await save(r, owner_engine, "All of Farming", niche=w.slug("parent"))
    briefs = await save(r, owner_engine, "Farming Briefs", "briefs", niche=w.slug("parent"))
    await research_card(owner_engine, w.niche, age_days=1)  # counts
    held = await research_card(owner_engine, w.niche, age_days=1)
    await research_card(owner_engine, w.niche, age_days=1, status="candidate")  # never published
    await brief(owner_engine, w.sibling, age_days=1)  # an open Brief: counts in both views
    closed = await brief(owner_engine, w.niche, age_days=1)
    lapsed = await brief(owner_engine, w.niche, age_days=1)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE problems SET moderation_state = 'held' WHERE id = :id"), {"id": held})
        await conn.execute(text("UPDATE problem_briefs SET status = 'closed' WHERE problem_id = :id"), {"id": closed})
        await conn.execute(
            text("UPDATE problem_briefs SET deadline = current_date - 2 WHERE problem_id = :id"), {"id": lapsed}
        )
    assert counts(await r.run(), r.user) == {UUID(problems): 2, UUID(briefs): 1}


async def test_p21_c6_the_digest_email_is_opt_in_once_a_day_with_counts_only(
    developers: Developers, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    r = await rig(developers, owner_engine, app_engine)
    w = r.world
    grain = await save(r, owner_engine, "Grain in Nakuru", niche=w.slug("parent"), county=NAKURU)
    briefs = await save(r, owner_engine, "Farming Briefs", "briefs", niche=w.slug("parent"))
    await research_card(
        owner_engine, w.niche, county=NAKURU, age_days=1, title=SECRET_TITLE, statement=SECRET_STATEMENT
    )

    settings = (await r.me.get(PREFERENCES)).json()
    assert {"kind": "saved_search_digest", "channel": "email", "default": False, "enabled": False}.items() <= next(
        item for item in settings["items"] if item["kind"] == "saved_search_digest"
    ).items()
    first = await r.run()
    outcome = first.of(r.user)
    assert outcome is not None
    assert (outcome.email, outcome.email_skipped) == (None, "preference_off")
    assert r.outbox.outbox == []

    for refused in (
        {"kind": "saved_search_match", "channel": "in_app", "enabled": False},  # in-app is always on
        {"kind": "no_such_kind", "channel": "email", "enabled": True},
    ):
        response = await r.me.put(PREFERENCES, json=refused)
        assert (response.status_code, response.json()["detail"]["code"]) == (422, "unknown_preference")
    turned_on = await r.me.put(PREFERENCES, json={"kind": "saved_search_digest", "channel": "email", "enabled": True})
    assert turned_on.status_code == 200, turned_on.text
    assert next(item for item in turned_on.json()["items"] if item["kind"] == "saved_search_digest")["enabled"]

    # Published after the first run and before 09:00 on the next Nairobi day, which is at least 9 hours after it,
    # so the test reads the same at any hour (a moment of "now + 1 day" crossed midnight with the hour added below).
    tomorrow = datetime.combine(nairobi_day(first.now) + timedelta(days=1), time(9, 0), tzinfo=NAIROBI)
    await research_card(
        owner_engine, w.niche, county=NAKURU, age_days=-0.2, title=SECRET_TITLE, statement=SECRET_STATEMENT
    )
    await brief(owner_engine, w.niche, age_days=-0.2, title=SECRET_TITLE)
    await brief(owner_engine, w.sibling, age_days=-0.15, title=SECRET_TITLE)
    assert counts(await r.run(tomorrow), r.user) == {UUID(grain): 1, UUID(briefs): 2}
    [email] = r.outbox.outbox
    [address] = await rows(owner_engine, "SELECT email FROM users WHERE id = :u", u=r.user)
    assert (email.to, email.subject) == (address.email, "New matches for your saved searches")
    assert email.html is not None
    for line in ("Grain in Nakuru: 1 new problem", "Farming Briefs: 2 new Briefs"):
        assert line in email.text
        assert line in email.html
    for part in (email.text, email.html, email.subject):
        assert SECRET_TITLE not in part
        assert SECRET_STATEMENT not in part
        assert "Grain silos" not in part

    async with owner_engine.begin() as conn:  # forced again the same day, with something new: still one email
        await conn.execute(text("UPDATE saved_searches SET last_alerted_at = NULL WHERE user_id = :u"), {"u": r.user})
    await research_card(owner_engine, w.niche, county=NAKURU, age_days=-0.25)
    await r.run(tomorrow + timedelta(hours=1))  # 10:00, the same Nairobi day
    assert len(r.outbox.outbox) == 1
    [sent] = await rows(
        owner_engine,
        "SELECT count(*) FROM notification_deliveries WHERE user_id = :u AND kind = 'saved_search_digest'",
        u=r.user,
    )
    assert sent[0] == 1
