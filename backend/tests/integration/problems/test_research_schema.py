"""REQ-RES-01 (schema half; revision 0005): research runs, ``app_create_research_candidate`` and the AC-RES-1 backstop.

- ``research_runs`` (STAFF): staff admin only; a staff admin starts a run as themselves; the caps are CHECKs
  (AC-RES-3: at most 25 searches and 40 fetches); a stopped or failed run carries a stop reason (a code).
- ``app_create_research_candidate``: staff admin only (not a moderator, a developer or nobody), on the caller's own
  running run; confidence 0.40 to 1; a bounded title and statement; 1 to 10 sources, each with an https URL, a
  published date, a retrieval time and a quote (and nothing unknown); an official source when the card names
  organisations; the candidate and its sources are written together or not at all. The candidate is invisible to
  everyone but staff, carries ``created_by`` NULL, and the same staff admin approves it (``app_moderate_problem``).
- ``problems_research_guard`` (every role): a research card reaches ``published`` only with one official source or two
  distinct publishers among sources with a quote and a date, and with an official source when it names organisations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration.schema_v4 import act, add_niche, add_user, as_app, as_owner, expect, rowcount, run

START = (
    "INSERT INTO research_runs (id, niche_id, county_code, started_by, status, finished_at, stop_reason)"
    " VALUES (:id, :niche, :county, :by, CAST(:status AS research_run_status), :finished, :reason)"
)
CREATE = (
    "SELECT app_create_research_candidate(:run, :title, :statement, :group, :county, CAST(:confidence AS numeric),"
    " CAST(:named AS text[]), CAST(:sources AS jsonb))"
)
MODERATE = "SELECT app_moderate_problem(:id, 'clear', CAST(:status AS problem_status))"


def source(**overrides: Any) -> dict[str, Any]:
    """One valid source (a saved excerpt): news, with a publisher, dates and a verbatim quote."""
    item: dict[str, Any] = {
        "url": "https://www.businessdailyafrica.com/bd/corporate/technology/example-5412426",
        "publisher": "Business Daily",
        "source_type": "news",
        "published_date": "2026-04-03",
        "retrieved_at": "2026-09-29",
        "quote": "As of December 2025, M-Pesa's share in the mobile money market had slimmed to 89 percent.",
        "excerpt_ref": "ke-tel-001",
    }
    item.update(overrides)
    return {key: value for key, value in item.items() if value is not None}


OFFICIAL = source(
    url="https://www.ca.go.ke/consumers-enjoy-lower-calling-rates",
    publisher="Communications Authority of Kenya",
    source_type="official",
    excerpt_ref="ke-tel-005",
)
OTHER_PUBLISHER = source(url="https://www.capitalfm.co.ke/business/2026/01/example/", publisher="Capital FM Kenya")


def card(run_id: UUID, sources: Any, **overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "run": run_id,
        "title": "Mobile money competition is shifting",
        "statement": "Smaller operators say termination charges and market share make it hard to compete.",
        "group": "Mobile money users",
        "county": None,
        "confidence": 0.62,
        "named": "{}",
        "sources": json.dumps(sources),
    }
    params.update(overrides)
    return params


async def _start(conn: AsyncConnection, by: UUID, niche: UUID, county: str | None = None) -> UUID:
    """As the owner: a running research run started by ``by``."""
    run_id = uuid7()
    await run(conn, START, id=run_id, niche=niche, county=county, by=by, status="running", finished=None, reason=None)
    return run_id


async def _county(conn: AsyncConnection) -> str:
    """As the owner: a county region under KE (the migrated test database has no seed regions)."""
    await run(conn, "INSERT INTO regions (code, kind, name) VALUES ('KE', 'country', 'Kenya') ON CONFLICT DO NOTHING")
    code = f"XT-{uuid7().hex[-4:]}"
    await run(conn, "INSERT INTO regions (code, parent_code, kind, name) VALUES (:c, 'KE', 'county', 'Test')", c=code)
    return code


@dataclass(frozen=True, slots=True)
class Staff:
    admin: UUID
    other_admin: UUID
    moderator: UUID
    developer: UUID
    niche: UUID


async def _staff(conn: AsyncConnection) -> Staff:
    return Staff(
        admin=await add_user(conn, "admin", staff_role="admin"),
        other_admin=await add_user(conn, "admin2", staff_role="admin"),
        moderator=await add_user(conn, "moderator", staff_role="moderator"),
        developer=await add_user(conn, "developer"),
        niche=await add_niche(conn),
    )


# --- research_runs ------------------------------------------------------------------------------------------------


async def test_research_runs_are_staff_admin_only_and_capped(owner_engine: AsyncEngine) -> None:
    """Staff admin starts a run as themselves and reads and updates runs; a moderator, a developer and nobody read,
    start or change none; AC-RES-3: a run never records more than 25 searches or 40 fetches; a stopped run carries a
    stop reason (a code)."""
    async with as_app(owner_engine) as conn:
        people = await _staff(conn)
        mine = uuid7()
        start = {"niche": people.niche, "county": None, "status": "running", "finished": None, "reason": None}
        await act(conn, people.admin)
        await run(conn, START, id=mine, by=people.admin, **start)
        await expect(conn, START, "row-level security", id=uuid7(), by=people.other_admin, **start)  # as themselves
        await expect(conn, START, "row-level security", id=uuid7(), by=people.admin, **(start | {"status": "stopped"}))
        for outsider in (people.moderator, people.developer, None):
            await act(conn, outsider)
            await expect(conn, START, "row-level security", id=uuid7(), by=outsider or people.admin, **start)
            assert await run(conn, "SELECT count(*) FROM research_runs WHERE id = :id", id=mine) == 0
            assert await rowcount(conn, "UPDATE research_runs SET searches = 1 WHERE id = :id", id=mine) == 0
        await act(conn, people.other_admin)  # any staff admin may close a stale run
        assert await run(conn, "SELECT count(*) FROM research_runs WHERE id = :id", id=mine) == 1
        caps = "UPDATE research_runs SET searches = :s, fetches = :f WHERE id = :id"
        await expect(conn, caps, "run_caps", s=26, f=0, id=mine)
        await expect(conn, caps, "run_caps", s=0, f=41, id=mine)
        assert await rowcount(conn, caps, s=25, f=40, id=mine) == 1
        stop = "UPDATE research_runs SET status = 'stopped', finished_at = now(), stop_reason = :r WHERE id = :id"
        await expect(conn, stop.replace(", stop_reason = :r", ""), "stop_reason_is_a_code", id=mine)
        await expect(conn, stop, "stop_reason_is_a_code", r="Too many fetches!", id=mine)
        assert await rowcount(conn, stop, r="fetch_cap", id=mine) == 1
        await expect(conn, "DELETE FROM research_runs WHERE id = :id", "permission denied", id=mine)


# --- app_create_research_candidate ----------------------------------------------------------------------------------


async def test_only_a_staff_admin_creates_candidates_on_their_own_running_run(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        people = await _staff(conn)
        mine = await _start(conn, people.admin, people.niche)
        theirs = await _start(conn, people.other_admin, people.niche)
        done = await _start(conn, people.admin, people.niche)
        await run(conn, "UPDATE research_runs SET status = 'completed', finished_at = now() WHERE id = :id", id=done)
        valid = [source(), OTHER_PUBLISHER]
        for caller in (people.moderator, people.developer, None):  # wrong role
            await act(conn, caller)
            await expect(conn, CREATE, "staff admin only", **card(mine, valid))
        await act(conn, people.admin)
        for run_id in (theirs, done, uuid7()):  # wrong run: another admin's, finished, none
            await expect(conn, CREATE, "no running research run of the caller's", **card(run_id, valid))
        created = await run(conn, CREATE, **card(mine, valid))
        assert isinstance(created, UUID)


@pytest.mark.parametrize(
    "sources",
    [
        pytest.param([source(url="http://www.ca.go.ke/page")], id="http"),
        pytest.param([source(url="https://www.ca.go.ke/a page")], id="url_with_space"),
        pytest.param([source(url="https://user@evil.example/")], id="url_with_userinfo"),
        pytest.param([source(url="ftp://www.ca.go.ke/file")], id="not_web"),
        pytest.param([{k: v for k, v in source().items() if k != "url"}], id="no_url"),
        pytest.param([{k: v for k, v in source().items() if k != "published_date"}], id="no_date"),
        pytest.param([source(published_date="2026-02-30")], id="impossible_date"),
        pytest.param([source(published_date="29/09/2026")], id="date_format"),
        pytest.param([{k: v for k, v in source().items() if k != "retrieved_at"}], id="no_retrieval"),
        pytest.param([source(retrieved_at="yesterday")], id="bad_retrieval"),
        pytest.param([{k: v for k, v in source().items() if k != "quote"}], id="no_quote"),
        pytest.param([source(quote="   ")], id="blank_quote"),
        pytest.param([source(quote="x" * 2001)], id="long_quote"),
        pytest.param([source(publisher=" ")], id="blank_publisher"),
        pytest.param([source(source_type="rumour")], id="unknown_type"),
        pytest.param([source(excerpt_ref="ke tel 001")], id="bad_excerpt_ref"),
        pytest.param([source(note="free text")], id="unknown_key"),
        pytest.param([source(published_date=20260403)], id="not_a_string"),
        pytest.param([source(), "https://example.test"], id="not_an_object"),
        pytest.param([], id="none"),
        pytest.param([source()] * 11, id="eleven"),
        pytest.param(source(), id="not_a_list"),
    ],
)
async def test_every_source_needs_an_https_url_a_date_and_a_quote(owner_engine: AsyncEngine, sources: Any) -> None:
    """A bad source refuses the whole card: nothing is written (a good source next to it included)."""
    async with as_app(owner_engine) as conn:
        people = await _staff(conn)
        mine = await _start(conn, people.admin, people.niche)
        await act(conn, people.admin)
        bundle = [*sources, OFFICIAL] if isinstance(sources, list) and 0 < len(sources) < 10 else sources
        await expect(conn, CREATE, "1 to 10 sources, each with an https URL", **card(mine, bundle))
        await as_owner(conn)
        assert await run(conn, "SELECT count(*) FROM problems WHERE research_run_id = :r", r=mine) == 0


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"confidence": 0.39}, "confidence is 0.40 to 1"),
        ({"confidence": 0.3999}, "confidence is 0.40 to 1"),
        ({"confidence": 1.01}, "confidence is 0.40 to 1"),
        ({"confidence": None}, "confidence is 0.40 to 1"),
        ({"title": "x" * 91}, "a title of 1 to 90 characters"),
        ({"title": "  "}, "a title of 1 to 90 characters"),
        ({"statement": " ".join(["word"] * 121)}, "a statement of 1 to 120 words"),
        ({"named": "{Safaricom}"}, "naming an organisation needs an official source"),
        ({"named": "{" + ",".join(f"Org {i}" for i in range(11)) + "}", "sources": [OFFICIAL]}, "named_orgs_valid"),
    ],
)
async def test_a_candidate_is_refused_below_its_bounds(
    owner_engine: AsyncEngine, overrides: dict[str, Any], message: str
) -> None:
    """docs/spec/06 6.5: confidence below 0.40 is discarded; a title of at most 90 characters and a statement of at
    most 120 words; a card naming an organisation needs an official source, and names at most 10."""
    async with as_app(owner_engine) as conn:
        people = await _staff(conn)
        mine = await _start(conn, people.admin, people.niche)
        await act(conn, people.admin)
        sources = overrides.pop("sources", [source(), OTHER_PUBLISHER])
        await expect(conn, CREATE, message, **card(mine, sources, **overrides))
        await run(conn, CREATE, **card(mine, sources, confidence=0.40))  # the floor itself is accepted


async def test_a_candidate_is_staff_only_and_the_same_admin_approves_it(owner_engine: AsyncEngine) -> None:
    """AC-RES-2 (database half): the candidate and its sources are invisible to every non-staff reader; it carries the
    run, its niche and country, no creator, and the named organisations; the admin who created it approves it through
    app_moderate_problem (created_by NULL is never the moderator's own), after which every signed-in user reads it."""
    async with as_app(owner_engine) as conn:
        people = await _staff(conn)
        county = await _county(conn)
        mine = await _start(conn, people.admin, people.niche, county)
        await act(conn, people.admin)
        created = await run(conn, CREATE, **card(mine, [OFFICIAL, source()], named="{Safaricom}"))
        await as_owner(conn)
        row = (
            await conn.execute(
                sa.text(
                    "SELECT source::text, status::text, created_by, org_id, ai_generated, research_run_id, niche_id,"
                    " country, county_code, named_orgs, moderation_state::text AS moderation FROM problems"
                    " WHERE id = :id"
                ),
                {"id": created},
            )
        ).one()
        assert tuple(row) == (
            "research_agent",
            "candidate",
            None,
            None,
            True,
            mine,
            people.niche,
            "KE",
            county,
            ["Safaricom"],
            "clear",
        )
        cited = await conn.execute(
            sa.text("SELECT excerpt_ref, source_type FROM problem_sources WHERE problem_id = :id ORDER BY excerpt_ref"),
            {"id": created},
        )
        assert [tuple(r) for r in cited.all()] == [("ke-tel-001", "news"), ("ke-tel-005", "official")]
        visible = (
            "SELECT (SELECT count(*) FROM problems WHERE id = :id),"
            " (SELECT count(*) FROM problem_sources WHERE problem_id = :id)"
        )
        for reader in (people.developer, None):
            await act(conn, reader)
            assert tuple((await conn.execute(sa.text(visible), {"id": created})).one()) == (0, 0)
        await act(conn, people.admin)
        await expect(conn, CREATE, "a county run's card is of its county", **card(mine, [OFFICIAL], county="KE"))
        await run(conn, MODERATE, id=created, status="published")
        await act(conn, people.developer)
        assert tuple((await conn.execute(sa.text(visible), {"id": created})).one()) == (1, 2)


# --- the AC-RES-1 backstop ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sources", "named", "published"),
    [
        pytest.param([source()], "{}", False, id="one_news_source"),
        pytest.param([source(), source(publisher="  business DAILY ")], "{}", False, id="one_publisher_twice"),
        pytest.param([source(), OTHER_PUBLISHER], "{}", True, id="two_publishers"),
        pytest.param([OFFICIAL], "{}", True, id="one_official_source"),
        pytest.param([OFFICIAL], "{Safaricom}", True, id="named_with_official"),
    ],
)
async def test_a_research_card_publishes_only_with_an_official_source_or_two_publishers(
    owner_engine: AsyncEngine, sources: list[dict[str, Any]], named: str, published: bool
) -> None:
    """AC-RES-1: approving a card with a single non-official publisher is refused (and it stays a candidate); an
    official source, or two distinct publishers, publish it."""
    async with as_app(owner_engine) as conn:
        people = await _staff(conn)
        mine = await _start(conn, people.admin, people.niche)
        await act(conn, people.admin)
        created = await run(conn, CREATE, **card(mine, sources, named=named))
        if published:
            await run(conn, MODERATE, id=created, status="published")
        else:
            await expect(conn, MODERATE, "AC-RES-1", id=created, status="published")
        status = await run(conn, "SELECT status::text FROM problems WHERE id = :id", id=created)
        assert status == ("published" if published else "candidate")


async def test_the_backstop_holds_for_every_role_and_every_way_in(owner_engine: AsyncEngine) -> None:
    """The owner too: a research card inserted as published (its sources come after it), moved to published from any
    status with a single publisher, or naming an organisation without an official source is refused; sources without
    a quote or a date do not count; a card already published may change its moderation state."""
    async with as_app(owner_engine) as conn:
        people = await _staff(conn)
        await as_owner(conn)
        insert = (
            "INSERT INTO problems (id, source, niche_id, title, statement, status, ai_generated, named_orgs)"
            " VALUES (:id, 'research_agent', :niche, 'Owner card', 'Statement', CAST(:status AS problem_status), true,"
            " CAST(:named AS text[]))"
        )
        await expect(conn, insert, "AC-RES-1", id=uuid7(), niche=people.niche, status="published", named="{}")
        cite = (
            "INSERT INTO problem_sources (id, problem_id, url, publisher, source_type, published_date, retrieved_at,"
            " quote) VALUES (:id, :p, 'https://example.test/s', :publisher, :type, :date, now(), :quote)"
        )
        card_id = uuid7()
        await run(conn, insert, id=card_id, niche=people.niche, status="archived", named="{}")
        await run(
            conn, cite, id=uuid7(), p=card_id, publisher="Daily Nation", type="news", date="2026-01-01", quote="q"
        )
        # A second publisher without a quote, and one without a date, do not count.
        await run(conn, cite, id=uuid7(), p=card_id, publisher="The Star", type="news", date="2026-01-01", quote=None)
        await run(conn, cite, id=uuid7(), p=card_id, publisher="The Standard", type="news", date=None, quote="q")
        publish = "UPDATE problems SET status = 'published' WHERE id = :id"
        await expect(conn, publish, "AC-RES-1", id=card_id)
        await run(conn, cite, id=uuid7(), p=card_id, publisher="Capital FM", type="news", date="2026-01-02", quote="q")
        assert await rowcount(conn, publish, id=card_id) == 1
        held = "UPDATE problems SET moderation_state = 'held' WHERE id = :id"
        assert await rowcount(conn, held, id=card_id) == 1  # already published: nothing to re-check
        named = uuid7()
        await run(conn, insert, id=named, niche=people.niche, status="candidate", named="{Airtel}")
        for publisher in ("Daily Nation", "Capital FM"):
            await run(conn, cite, id=uuid7(), p=named, publisher=publisher, type="news", date="2026-01-01", quote="q")
        await expect(conn, publish, "naming an organisation is published with an official source", id=named)
        await run(conn, cite, id=uuid7(), p=named, publisher="CA", type="official", date="2026-01-01", quote="q")
        assert await rowcount(conn, publish, id=named) == 1
        # Other sources publish as before: a developer's problem needs no citation.
        developer_problem = uuid7()
        await run(
            conn,
            "INSERT INTO problems (id, source, title, statement, status, created_by) VALUES (:id, 'developer', 't',"
            " 's', 'published', :u)",
            id=developer_problem,
            u=people.developer,
        )
