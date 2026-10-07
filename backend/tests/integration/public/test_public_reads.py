"""REQ-UX-03, REQ-DIR-01, REQ-REPO-02 (P24-B): ``GET /api/public/activity`` and ``GET /api/public/explore`` against the
database, signed out.

- Only public rows: a developer's published problem, a listed E2 organisation's published public Brief and a published
  proposal's registered version are listed; a pending problem, a held one, an unverified organisation's Brief, a
  delisted one's, an invited Brief, a draft Brief, a hidden, a held and a draft proposal never are, and no body names
  the author, a handle, an address, an organisation or a statement.
- Explore counts by county and by top-level niche (a child niche under its parent), the newest three each, counties
  without public problems left out.
- ``seeded``: every item in a demo deployment (APP_ENV test); elsewhere only a seeded example card's.
- Two reads within the minute cost one feed query; past the per-address limit the answer is 429; the answers say
  ``Cache-Control: public, max-age=60`` and have the OpenAPI document's shapes.

Each test builds its own rows (committed: the API reads in its own connections) and asserts about them only, by their
event keys and ids: other modules' rows are in the same database, some of them dated ahead of the wall clock, so the
tests that look for their rows in the feed widen it past 20 (``whole_feed``; the limit itself is a unit test). The
statements also run as the table owner, with RLS out of the way, to prove their own predicates exclude every private
row; the reader's 2-second timeout cancels a slow statement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.config import get_settings
from bridge.db import create_session_factory
from bridge.ids import uuid7
from bridge.public import queries, router
from bridge.public.feed import event_id
from tests.integration import world as w
from tests.integration.api import make_client
from tests.integration.engagements import tracker as t
from tests.integration.proposals.helpers import Developers, ProposalWorld, create, draft_body, publish, rows
from tests.integration.query_counts import statements
from tests.integration.teams.schema_world import county, developer, organisation
from tests.unit.public.openapi_shape import conforms

ACTIVITY, EXPLORE = "/api/public/activity", "/api/public/explore"
STATEMENT = "A statement nobody signed out may read"


async def add_problem(
    conn: AsyncConnection,
    title: str,
    *,
    by: UUID,
    niche_id: UUID,
    county_code: str | None = None,
    org: UUID | None = None,
    status: str = "published",
    moderation: str = "clear",
    example: bool = False,
) -> UUID:
    """As the owner: a problem published now (a Brief's when ``org``), with one cited source (a saved demo excerpt's
    when ``example``)."""
    problem_id = uuid7()
    await t.run(
        conn,
        "INSERT INTO problems (id, source, niche_id, county_code, title, statement, status, created_by, org_id,"
        " moderation_state, published_at) VALUES (:id, CAST(:source AS problem_source), :niche, :county, :title,"
        " :statement, CAST(:status AS problem_status), :by, :org, CAST(:moderation AS moderation_state),"
        " clock_timestamp())",
        id=problem_id,
        source="org_brief" if org else "developer",
        niche=niche_id,
        county=county_code,
        title=title,
        statement=STATEMENT,
        status=status,
        by=by,
        org=org,
        moderation=moderation,
    )
    await t.run(
        conn,
        "INSERT INTO problem_sources (id, problem_id, url, retrieved_at, excerpt_ref)"
        " VALUES (:id, :problem, 'https://example.test/source', now(), :ref)",
        id=uuid7(),
        problem=problem_id,
        ref="example:p24-demo" if example else None,
    )
    return problem_id


async def add_brief(conn: AsyncConnection, problem_id: UUID, org: UUID, *, visibility: str, status: str) -> None:
    await t.run(
        conn,
        "INSERT INTO problem_briefs (problem_id, org_id, visibility, status)"
        " VALUES (:p, :o, CAST(:v AS brief_visibility), CAST(:s AS brief_status))",
        p=problem_id,
        o=org,
        v=visibility,
        s=status,
    )


async def add_niche(conn: AsyncConnection, name: str, parent: UUID | None = None) -> UUID:
    niche_id = uuid7()
    await t.run(
        conn,
        "INSERT INTO niches (id, parent_id, slug, name_en) VALUES (:id, :parent, :slug, :name)",
        id=niche_id,
        parent=parent,
        slug=f"p24-{niche_id.hex}",
        name=name,
    )
    return niche_id


@dataclass(frozen=True, slots=True)
class Scene:
    tag: str
    top: UUID  # a top-level niche
    child: UUID  # under it
    county: str  # its public problems' county
    private_county: str  # only private problems are here
    public_problems: dict[str, UUID]  # label -> problem id ("open", "brief")
    private_problems: dict[str, UUID]
    public_version: UUID
    private_versions: dict[str, UUID]
    private_text: tuple[str, ...]  # names, handles, addresses, organisations and titles that must never appear


async def build(owner_engine: AsyncEngine) -> Scene:
    tag = uuid7().hex[-8:]
    async with owner_engine.begin() as conn:
        author = await developer(conn, f"p24author{tag}", peers=False)
        top = await add_niche(conn, f"P24 Top {tag}")
        child = await add_niche(conn, f"P24 Child {tag}", parent=top)
        place = await county(conn, f"P24 County {tag}")
        hidden_place = await county(conn, f"P24 Private County {tag}")
        orgs = {label: await organisation(conn, f"p24{label}{tag}") for label in ("open", "unverified", "delisted")}
        public = {
            "open": await add_problem(conn, f"P24 open {tag}", by=author, niche_id=child, county_code=place),
            "brief": await add_problem(
                conn, f"P24 brief {tag}", by=author, niche_id=child, county_code=place, org=orgs["open"]
            ),
        }
        await add_brief(conn, public["brief"], orgs["open"], visibility="public", status="published")
        private: dict[str, UUID] = {}
        for label, status, moderation in (("pending", "pending_review", "clear"), ("held", "published", "held")):
            private[label] = await add_problem(
                conn,
                f"P24 private {label} {tag}",
                by=author,
                niche_id=child,
                county_code=hidden_place,
                status=status,
                moderation=moderation,
            )
        for label, org, visibility, status in (
            ("unverified", orgs["unverified"], "public", "published"),
            ("delisted", orgs["delisted"], "public", "published"),
            ("invited", orgs["open"], "invited", "published"),
            ("draft-brief", orgs["open"], "public", "draft"),
        ):
            private[label] = await add_problem(
                conn, f"P24 private {label} {tag}", by=author, niche_id=child, county_code=hidden_place, org=org
            )
            await add_brief(conn, private[label], org, visibility=visibility, status=status)
        await t.run(conn, "UPDATE organizations SET verification = 'pending' WHERE id = :o", o=orgs["unverified"])
        await t.run(conn, "UPDATE organizations SET delisted_at = now() WHERE id = :o", o=orgs["delisted"])
        _, public_version = await w.add_proposal(conn, author, child, public["open"])
        versions = {
            "hidden": (await w.add_proposal(conn, author, child, public["open"], status="hidden"))[1],
            "held": (await w.add_proposal(conn, author, child, public["open"], moderation_state="held"))[1],
            "draft": (await w.add_proposal(conn, author, child, public["open"], registered=False))[1],
        }
        people = await conn.execute(sa.text("SELECT display_name, email FROM users WHERE id = :u"), {"u": author})
        person = people.one()
        handle = await t.run(conn, "SELECT handle FROM developer_profiles WHERE user_id = :u", u=author)
        names = [await t.run(conn, "SELECT legal_name FROM organizations WHERE id = :o", o=o) for o in orgs.values()]
    private_titles = tuple(f"P24 private {label} {tag}" for label in private)
    return Scene(
        tag=tag,
        top=top,
        child=child,
        county=place,
        private_county=hidden_place,
        public_problems=public,
        private_problems=private,
        public_version=public_version,
        private_versions=versions,
        private_text=(person.display_name, person.email, str(handle), *map(str, names), STATEMENT, *private_titles),
    )


async def read(client: httpx.AsyncClient, path: str, scene: Scene) -> dict[str, Any]:
    """One signed-out read: 200, the public cache header, the OpenAPI shape, and none of the scene's private text."""
    response = await client.get(path)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "public, max-age=60"
    body: dict[str, Any] = response.json()
    document = client.app.openapi()  # type: ignore[attr-defined]
    schema = document["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    conforms(body, schema, document["components"]["schemas"])
    for text in scene.private_text:
        assert text not in response.text, text
    return body


@pytest.fixture
async def scene(owner_engine: AsyncEngine) -> Scene:
    return await build(owner_engine)


@pytest.fixture
def whole_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The activity feed with every public event, not the newest 20: the scene's rows are in it whatever else the
    shared database holds."""
    monkeypatch.setattr(queries, "FEED_SIZE", 1_000_000)


@pytest.mark.usefixtures("whole_feed")
async def test_only_public_rows_reach_a_signed_out_visitor(app_engine: AsyncEngine, scene: Scene) -> None:
    """Given public and private problems, Briefs and proposals, When a signed-out visitor reads the feed and Explore,
    Then only the public ones are there, under opaque keys, with no person, handle, address, organisation, statement
    or private title anywhere in either body."""
    async with make_client(app_engine, ip="198.51.100.21") as client:
        assert get_settings().session_cookie_name not in client.cookies  # signed out
        activity, explore = await read(client, ACTIVITY, scene), await read(client, EXPLORE, scene)
    keys = {item["id"]: item for item in activity["items"]}
    opened = keys[event_id("brief_opened", scene.public_problems["brief"])]
    posted = keys[event_id("problem_posted", scene.public_problems["open"])]
    registered = keys[event_id("version_registered", scene.public_version)]
    assert (posted["title"], posted["county"], posted["niche"], posted["stage"]) == (
        f"P24 open {scene.tag}",
        f"P24 County {scene.tag}",
        f"P24 Top {scene.tag} › P24 Child {scene.tag}",
        None,
    )
    assert opened["title"] == f"P24 brief {scene.tag}"
    assert (registered["title"], registered["county"]) == ("RLS proposal", None)
    for problem_id in scene.private_problems.values():
        for kind in ("problem_posted", "brief_opened"):
            assert event_id(kind, problem_id) not in keys
    for version_id in scene.private_versions.values():
        assert event_id("version_registered", version_id) not in keys
    assert {item["kind"] for item in activity["items"]} <= {"problem_posted", "brief_opened", "version_registered"}
    assert {item["stage"] for item in activity["items"]} == {None}
    listed = {teaser["id"] for group in explore["counties"] + explore["niches"] for teaser in group["newest"]}
    assert not listed & {str(problem_id) for problem_id in scene.private_problems.values()}
    assert scene.private_county not in {group["code"] for group in explore["counties"]}


async def test_explore_counts_by_county_and_top_level_niche_with_the_newest_three(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, scene: Scene
) -> None:
    """Given the scene's two public problems in one county and a child niche, When two more are published there, Then
    Explore shows the county with 4 and its three newest, the top-level niche with 4, and totals that count them."""
    async with owner_engine.begin() as conn:
        author = await t.run(conn, "SELECT created_by FROM problems WHERE id = :p", p=scene.public_problems["open"])
        later = [
            await add_problem(conn, title, by=author, niche_id=scene.child, county_code=scene.county)
            for title in (f"P24 later 1 {scene.tag}", f"P24 later 2 {scene.tag}")
        ]
    async with make_client(app_engine, ip="198.51.100.22") as client:
        explore = await read(client, EXPLORE, scene)
    [place] = [group for group in explore["counties"] if group["code"] == scene.county]
    newest = [str(later[1]), str(later[0]), str(scene.public_problems["brief"])]
    assert (place["name"], place["count"], [x["id"] for x in place["newest"]]) == (
        f"P24 County {scene.tag}",
        4,
        newest,
    )
    [top] = [group for group in explore["niches"] if group["id"] == str(scene.top)]
    assert (top["count"], [x["id"] for x in top["newest"]]) == (4, newest)
    assert str(scene.child) not in {group["id"] for group in explore["niches"]}  # a child counts under its parent
    assert explore["totals"]["problems"] >= 4
    assert explore["totals"]["counties"] == len(explore["counties"])
    assert explore["totals"]["niches"] == len(explore["niches"])


@pytest.mark.usefixtures("whole_feed")
async def test_seeded_follows_the_demo_deployment_and_the_seeds_own_mark(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, scene: Scene
) -> None:
    """Given a seeded example card (every source a saved demo excerpt) and the scene's real problem, When the feed is
    read under APP_ENV test, Then every item is seeded; When read under staging, Then only the example card is, and
    the feed is not."""
    async with owner_engine.begin() as conn:
        author = await t.run(conn, "SELECT created_by FROM problems WHERE id = :p", p=scene.public_problems["open"])
        example = await add_problem(conn, f"P24 example {scene.tag}", by=author, niche_id=scene.child, example=True)
    async with make_client(app_engine, ip="198.51.100.23") as client:
        demo = await read(client, ACTIVITY, scene)
    assert demo["seeded"] is True
    assert all(item["seeded"] for item in demo["items"])
    staging = get_settings().model_copy(update={"app_env": "staging"})
    async with make_client(app_engine, staging, ip="198.51.100.24") as client:
        real = await read(client, ACTIVITY, scene)
    keys = {item["id"]: item["seeded"] for item in real["items"]}
    assert keys[event_id("problem_posted", example)] is True
    assert keys[event_id("problem_posted", scene.public_problems["open"])] is False
    assert real["seeded"] is False


@pytest.mark.parametrize(("path", "query"), [(ACTIVITY, "UNION ALL"), (EXPLORE, "OVER (PARTITION BY")])
async def test_two_reads_within_the_minute_cost_one_query(
    app_engine: AsyncEngine, scene: Scene, path: str, query: str
) -> None:
    """Given a fresh API worker, When the same public read is asked twice, Then the database answers the first only
    (the second costs at most the clock: neither the problems nor the rate-limit ledger)."""
    async with make_client(app_engine, ip="198.51.100.25") as client:
        with statements(app_engine) as first:
            body = await read(client, path, scene)
        with statements(app_engine) as second:
            assert await read(client, path, scene) == body
    assert sum(query in statement for statement in first) == 1
    assert not [s for s in second if any(table in s for table in ("problems", "proposal", "login_attempts"))]


async def test_past_the_limit_an_address_gets_429(
    monkeypatch: pytest.MonkeyPatch, app_engine: AsyncEngine, scene: Scene
) -> None:
    """Given a limit of 2 reads a minute, When one address misses the cache a third time, Then it gets 429
    rate_limited (not cached), while another address still reads."""
    monkeypatch.setattr(router, "READS_PER_MINUTE", 2)
    async with make_client(app_engine, ip="198.51.100.26") as client:
        for _ in range(2):
            await read(client, EXPLORE, scene)
            del client.app.state.public_caches  # type: ignore[attr-defined]  # the next read is a miss
        refused = await client.get(EXPLORE)
    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "rate_limited"
    assert refused.headers["cache-control"] == "no-store"
    async with make_client(app_engine, ip="198.51.100.27") as other:
        assert (await other.get(EXPLORE)).status_code == 200


async def test_a_published_proposals_new_problem_puts_its_county_on_explore(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, developers: Developers, proposal_world: ProposalWorld
) -> None:
    """Given a developer's teaser in a county that describes a new problem (as the demo seed publishes P1 and P3) and
    another teaser with no county, When both publish, Then each new problem takes its teaser's county (none:
    nationwide) and Explore, signed out, lists that county with the problem as its newest."""
    tag, place = uuid7().hex[-8:], "KE-77"  # the teaser form takes KE-NN codes; no county of the seed is KE-77
    async with owner_engine.begin() as conn:
        kenya = "INSERT INTO regions (code, kind, name) VALUES ('KE', 'country', 'Kenya') ON CONFLICT DO NOTHING"
        await t.run(conn, kenya)
        await t.run(
            conn,
            "INSERT INTO regions (code, parent_code, kind, name) VALUES (:c, 'KE', 'county', :n)",
            c=place,
            n=f"P24 Seeded County {tag}",
        )
    owner = await developers()
    made: dict[str | None, str] = {}
    for county_code in (place, None):
        body = draft_body(proposal_world, link=False, county_code=county_code)
        body["new_problem"] = {
            "title": f"P24 described {tag} {county_code or 'nationwide'}",
            "statement": "Farmers lose a third of the milk before it reaches a cooler.",
        }
        created = await create(owner, body)
        response = await publish(owner, created["id"])
        assert response.status_code == 200, response.text
        made[county_code] = response.json()["new_problem_id"]
    filed = await rows(
        owner_engine, "SELECT id::text, county_code FROM problems WHERE id::text = ANY(:ids)", ids=list(made.values())
    )
    assert {row.id: row.county_code for row in filed} == {made[place]: place, made[None]: None}
    async with make_client(app_engine, ip="198.51.100.28") as visitor:
        response = await visitor.get(EXPLORE)
    assert response.status_code == 200, response.text
    explore = response.json()
    assert explore["counties"], "the counties list is empty"
    [group] = [group for group in explore["counties"] if group["code"] == place]
    assert (group["name"], group["count"]) == (f"P24 Seeded County {tag}", 1)
    assert [teaser["id"] for teaser in group["newest"]] == [made[place]]


@pytest.mark.usefixtures("whole_feed")
async def test_the_statements_exclude_every_private_row_without_rls(owner_engine: AsyncEngine, scene: Scene) -> None:
    """Given the scene's private rows (a pending and a held problem, a draft, an invited, an unverified and a delisted
    organisation's Brief, a hidden, a held and an unpublished proposal), When both statements run as the table owner
    (Row-Level Security does not apply to it), Then none of them is read: the statements' own predicates exclude them,
    whatever RLS would add; the public rows are read."""
    async with owner_engine.connect() as conn:
        assert await t.run(conn, "SELECT current_user") == "bridge_owner"
        activity = {row.row_id for row in (await conn.execute(queries.activity_statement())).all()}
        explore = {row.id for row in (await conn.execute(queries.explore_statement())).all()}
    private = set(scene.private_problems.values()) | set(scene.private_versions.values())
    assert not activity & private
    assert not explore & set(scene.private_problems.values())
    assert {*scene.public_problems.values(), scene.public_version} <= activity
    assert set(scene.public_problems.values()) <= explore


async def test_a_slow_public_read_is_cancelled_after_2_seconds(app_engine: AsyncEngine) -> None:
    """Given a statement slower than the reader's timeout, When the public reader runs it, Then the database cancels
    it (query_canceled) instead of holding the connection."""
    factory = create_session_factory(app_engine)
    with pytest.raises(DBAPIError) as caught:
        await queries.read(factory, sa.select(sa.func.pg_sleep(3)))
    assert getattr(caught.value.orig, "sqlstate", None) == "57014"
    assert "statement timeout" in str(caught.value.orig)


async def test_a_public_problem_page_serves_readable_problems_only(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, scene: Scene
) -> None:
    """Given the scene's public problem and public Brief and its private rows (a pending and a held problem, a draft,
    an invited, an unverified and a delisted organisation's Brief) plus an archived and a rejected problem, When a
    signed-out visitor opens each page, Then the two public ones answer 200 with the public cache header, the Brief
    naming its listed organisation and the developer's problem none, never the author; every other id is the same
    404 (no-store)."""
    async with owner_engine.begin() as conn:
        author = await t.run(conn, "SELECT created_by FROM problems WHERE id = :p", p=scene.public_problems["open"])
        retired = {
            status: await add_problem(conn, f"P24 {status} {scene.tag}", by=author, niche_id=scene.child, status=status)
            for status in ("archived", "rejected")
        }
        org_name = await t.run(
            conn,
            "SELECT o.legal_name FROM organizations o JOIN problems p ON p.org_id = o.id WHERE p.id = :p",
            p=scene.public_problems["brief"],
        )
    person = (*scene.private_text[:3], org_name)  # the author's display name, address and handle; the organisation
    async with make_client(app_engine, ip="198.51.100.29") as visitor:
        pages = {
            label: await visitor.get(f"/api/public/problems/{pid}") for label, pid in scene.public_problems.items()
        }
        refused = {
            label: await visitor.get(f"/api/public/problems/{pid}")
            for label, pid in {**scene.private_problems, **retired}.items()
        }
    for label, response in pages.items():
        assert (response.status_code, response.headers["cache-control"]) == (200, "public, max-age=60"), label
        assert not [text for text in person if text in response.text], label
    opened, posted = pages["brief"].json(), pages["open"].json()
    assert (opened["source"], opened["organisation"]) == ("brief", {"verification": "e2"})
    assert (opened["title"], opened["statement"]) == (f"P24 brief {scene.tag}", STATEMENT)
    assert (posted["source"], posted["organisation"]) == ("developer", None)
    assert posted["county"] == {"code": scene.county, "name": f"P24 County {scene.tag}"}
    assert posted["niche"] == {
        "id": str(scene.child),
        "name": f"P24 Child {scene.tag}",
        "parent": {"id": str(scene.top), "name": f"P24 Top {scene.tag}"},
    }
    for label, response in refused.items():
        assert response.status_code == 404, label
        assert response.json() == {"detail": {"code": "not_found", "message": "No such problem."}}, label
        assert response.headers["cache-control"] == "no-store", label
