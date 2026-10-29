"""The bell's API (docs/spec/07 §1; REQ-NOT-03, the in-app channel; task P19-C) against PostgreSQL as ``bridge_app``.

Given two people with notifications, When one lists them, Then only theirs, newest first, 20 a page with a cursor;
``unread=1`` keeps the unread ones and ``unread-count`` counts them; marking one read is idempotent (the first moment
stays); somebody else's id answers 404 like an unknown one; "read all" marks only the caller's unread rows. The same
endpoints serve every signed-in person (a developer, an organisation's member). Reads write no audit row; a link that
is not a platform path is never served; the list sends as many statements with 20 rows as with 2. A page may end
inside a run of rows written in one moment: the id orders them, so the next page neither skips nor repeats one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge import pagination
from bridge.db import bind_tenant, create_session_factory
from bridge.ids import uuid7
from bridge.notifications.in_app import post_in_app
from tests.integration.api import make_client
from tests.integration.proposals.helpers import Developers, user_of
from tests.integration.proposals.pitch_helpers import Members, add_member, add_org
from tests.integration.query_counts import LARGE, SMALL, counted

URL = "/api/me/notifications"
FIELDS = {"id", "kind", "title", "body", "link", "created_at", "read_at"}
_ADD = text(
    "INSERT INTO in_app_notifications (id, user_id, org_id, kind, title, body, link, created_at, read_at)"
    " VALUES (:id, :user, :org, :kind, :title, :body, :link, now() - make_interval(secs => :ago),"
    " CASE WHEN :read THEN now() - make_interval(secs => :ago / 2) END)"
)


async def add(
    owner_engine: AsyncEngine,
    user_id: UUID,
    title: str,
    *,
    ago: float = 60.0,
    read: bool = False,
    link: str | None = "/dev/engagements",
    org_id: UUID | None = None,
    kind: str = "engagement.n03",
) -> UUID:
    """One notification for ``user_id``, written ``ago`` seconds back (read half-way since, when ``read``)."""
    row_id = uuid7()
    params = {"id": row_id, "user": user_id, "org": org_id, "kind": kind, "title": title, "body": f"About {title}."}
    async with owner_engine.begin() as conn:
        await conn.execute(_ADD, params | {"link": link, "ago": ago, "read": read})
    return row_id


async def stored(owner_engine: AsyncEngine, row_id: UUID) -> Any:
    async with owner_engine.connect() as conn:
        return (await conn.execute(text("SELECT * FROM in_app_notifications WHERE id = :id"), {"id": row_id})).one()


async def ok(response: httpx.Response) -> Any:
    assert response.status_code == 200, response.text
    return response.json()


def titles(page: dict[str, Any]) -> list[str]:
    return [item["title"] for item in page["items"]]


async def count(client: httpx.AsyncClient) -> int:
    body = await ok(await client.get(f"{URL}/unread-count"))
    assert set(body) == {"count"}
    value: int = body["count"]
    return value


async def test_each_person_lists_only_their_own_newest_first(
    developers: Developers, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    amina, baraka = await developers(), await developers()
    await add(owner_engine, user_of(amina), "Oldest", ago=300)
    await add(owner_engine, user_of(amina), "Middle", ago=200, read=True, link=None)
    await add(owner_engine, user_of(baraka), "Baraka's own", ago=100)
    factory = create_session_factory(app_engine)
    async with factory() as db:  # the writers' own path: the tracker, interest, digests and reminders
        await bind_tenant(db, user_id=user_of(amina))
        assert await post_in_app(
            db,
            user_id=user_of(amina),
            kind="engagement.n03",
            title="Newest",
            body="Telco A approved your proposal.",
            link=f"/dev/engagements/{uuid4()}",
            dedupe_key=f"test:{uuid4()}",
        )
        await db.commit()

    page = await ok(await amina.get(URL))
    assert titles(page) == ["Newest", "Middle", "Oldest"]
    assert page["next_cursor"] is None
    assert all(set(item) == FIELDS for item in page["items"])
    newest, middle, _ = page["items"]
    assert (newest["kind"], newest["body"], newest["read_at"]) == (
        "engagement.n03",
        "Telco A approved your proposal.",
        None,
    )
    assert newest["link"].startswith("/dev/engagements/")
    assert middle["link"] is None
    assert middle["read_at"] is not None
    assert datetime.fromisoformat(middle["read_at"]) > datetime.fromisoformat(middle["created_at"])
    assert titles(await ok(await baraka.get(URL))) == ["Baraka's own"]


async def test_twenty_a_page_and_the_cursor_walks_the_rest(developers: Developers, owner_engine: AsyncEngine) -> None:
    """25 rows, five of them written in one moment (the id breaks the tie): 20, then 5, none twice or skipped."""
    client = await developers()
    me = user_of(client)
    for n in range(20):
        await add(owner_engine, me, f"Row {n:02d}", ago=1000 - n)
    tied = [uuid7() for _ in range(5)]
    async with owner_engine.begin() as conn:
        for n, row_id in enumerate(tied):
            await conn.execute(
                text(
                    "INSERT INTO in_app_notifications (id, user_id, kind, title, created_at)"
                    " VALUES (:id, :user, 'engagement.n03', :title, now() - interval '1 day')"  # one transaction
                ),
                {"id": row_id, "user": me, "title": f"Tied {n}"},
            )

    first = await ok(await client.get(URL))
    assert len(first["items"]) == 20
    assert first["next_cursor"]
    second = await ok(await client.get(URL, params={"cursor": first["next_cursor"]}))
    assert second["next_cursor"] is None
    listed = titles(first) + titles(second)
    assert listed == [f"Row {n:02d}" for n in reversed(range(20))] + [f"Tied {n}" for n in reversed(range(5))]
    assert [item["id"] for item in second["items"]] == [str(row_id) for row_id in reversed(tied)]
    smaller = await ok(await client.get(URL, params={"limit": 7}))
    assert len(smaller["items"]) == 7
    assert smaller["next_cursor"]


_TIED = text(
    "INSERT INTO in_app_notifications (id, user_id, kind, title, created_at)"
    " VALUES (:id, :user, 'engagement.n03', 'Tied', now() - interval '1 day')"
)


async def tied(owner_engine: AsyncEngine, user_id: UUID, n: int) -> list[UUID]:
    """``n`` notifications in one transaction, so one ``created_at``; random ids, so insertion order is no hint."""
    ids = [uuid4() for _ in range(n)]
    async with owner_engine.begin() as conn:
        for row_id in ids:
            await conn.execute(_TIED, {"id": row_id, "user": user_id})
    return ids


async def walk(client: httpx.AsyncClient, params: dict[str, Any]) -> list[list[str]]:
    """Every page's ids, following ``next_cursor`` to the end."""
    pages: list[list[str]] = []
    cursor = None
    while len(pages) < 20:
        page = await ok(await client.get(URL, params=params | ({"cursor": cursor} if cursor else {})))
        pages.append([item["id"] for item in page["items"]])
        cursor = page["next_cursor"]
        if cursor is None:
            return pages
    raise AssertionError("the cursor never ends")


@pytest.mark.parametrize(
    ("newer", "same_moment", "older", "limit", "sizes"),
    [(1, 5, 1, 3, [3, 3, 1]), (0, 5, 0, 3, [3, 2]), (0, 23, 0, None, [20, 3]), (2, 21, 0, None, [20, 3])],
    ids=["3-a-page-around-a-tie", "3-a-page-inside-a-tie", "20-a-page-inside-23-tied", "20-a-page-after-2-newer"],
)
async def test_a_page_ending_inside_a_tie_neither_skips_nor_repeats(
    developers: Developers,
    owner_engine: AsyncEngine,
    newer: int,
    same_moment: int,
    older: int,
    limit: int | None,
    sizes: list[int],
) -> None:
    client = await developers()
    me = user_of(client)
    before = [await add(owner_engine, me, f"Older {n}", ago=2 * 86400 + n) for n in range(older)]
    ties = await tied(owner_engine, me, same_moment)
    after = [await add(owner_engine, me, f"Newer {n}", ago=60.0 - n) for n in range(newer)]

    pages = await walk(client, {} if limit is None else {"limit": limit})
    assert [len(page) for page in pages] == sizes
    listed = [row_id for page in pages for row_id in page]
    expected = [*reversed(after), *sorted(ties, reverse=True), *before]
    assert listed == [str(row_id) for row_id in expected]  # newest first, a tie by id, none twice, none skipped


async def test_the_unread_filter_and_the_count(developers: Developers, owner_engine: AsyncEngine) -> None:
    client, other = await developers(), await developers()
    assert await count(client) == 0
    assert (await ok(await client.get(URL, params={"unread": 1}))) == {"items": [], "next_cursor": None}
    await add(owner_engine, user_of(client), "Unread old", ago=300)
    await add(owner_engine, user_of(client), "Read", ago=200, read=True)
    await add(owner_engine, user_of(client), "Unread new", ago=100)
    await add(owner_engine, user_of(other), "Somebody else's", ago=50)

    assert titles(await ok(await client.get(URL, params={"unread": 1}))) == ["Unread new", "Unread old"]
    assert titles(await ok(await client.get(URL, params={"unread": 0}))) == ["Unread new", "Read", "Unread old"]
    assert await count(client) == 2
    assert await count(other) == 1


async def test_marking_one_read_is_idempotent(developers: Developers, owner_engine: AsyncEngine) -> None:
    client = await developers()
    row_id = await add(owner_engine, user_of(client), "Approved")
    await add(owner_engine, user_of(client), "Still unread", ago=30)
    assert await count(client) == 2

    first = await ok(await client.post(f"{URL}/{row_id}/read"))
    assert set(first) == FIELDS
    assert first["id"] == str(row_id)
    assert first["read_at"] is not None
    again = await ok(await client.post(f"{URL}/{row_id}/read"))
    assert again == first  # the first moment stays
    assert await count(client) == 1
    row = await stored(owner_engine, row_id)
    assert row.read_at == datetime.fromisoformat(first["read_at"])
    assert (row.title, row.body, row.link, row.user_id) == (
        "Approved",
        "About Approved.",
        "/dev/engagements",
        user_of(client),
    )


async def test_somebody_elses_id_is_404_like_an_unknown_one(developers: Developers, owner_engine: AsyncEngine) -> None:
    client, other = await developers(), await developers()
    theirs = await add(owner_engine, user_of(other), "Theirs")
    foreign = await client.post(f"{URL}/{theirs}/read")
    unknown = await client.post(f"{URL}/{uuid4()}/read")
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()
    assert foreign.json()["detail"]["code"] == "not_found"
    assert (await stored(owner_engine, theirs)).read_at is None
    assert await count(other) == 1
    assert (await client.post(f"{URL}/not-a-uuid/read")).status_code == 422


async def test_read_all_marks_only_the_callers_unread_rows(developers: Developers, owner_engine: AsyncEngine) -> None:
    client, other = await developers(), await developers()
    earlier = await add(owner_engine, user_of(client), "Read earlier", ago=500, read=True)
    before = (await stored(owner_engine, earlier)).read_at
    for n in range(3):
        await add(owner_engine, user_of(client), f"Unread {n}", ago=100 - n)
    theirs = await add(owner_engine, user_of(other), "Theirs")

    assert await ok(await client.post(f"{URL}/read-all")) == {"count": 0}
    assert await count(client) == 0
    assert (await ok(await client.get(URL, params={"unread": 1})))["items"] == []
    assert all(item["read_at"] for item in (await ok(await client.get(URL)))["items"])
    assert (await stored(owner_engine, earlier)).read_at == before  # never moved
    assert (await stored(owner_engine, theirs)).read_at is None
    assert await ok(await client.post(f"{URL}/read-all")) == {"count": 0}  # nothing left: still fine


async def test_an_organisations_member_uses_the_same_endpoints(
    member_client: Members, owner_engine: AsyncEngine
) -> None:
    org = await add_org(owner_engine, f"Bellco {uuid4().hex[:6]}", verification="e2", niche_id=None)
    assert org.member is not None
    member = await member_client(org.member)
    row_id = await add(
        owner_engine, org.member, "A developer accepted", org_id=org.id, link=f"/org/engagements/{uuid4()}"
    )
    page = await ok(await member.get(URL))
    assert [item["id"] for item in page["items"]] == [str(row_id)]
    assert await count(member) == 1
    assert (await ok(await member.post(f"{URL}/{row_id}/read")))["read_at"] is not None
    assert await count(member) == 0


async def test_another_member_of_the_same_organisation_sees_none_of_them(
    member_client: Members, owner_engine: AsyncEngine
) -> None:
    """An organisation's notification is one person's: a colleague neither lists, counts nor marks it."""
    org = await add_org(owner_engine, f"Bellco {uuid4().hex[:6]}", verification="e2", niche_id=None)
    assert org.member is not None
    async with owner_engine.begin() as conn:
        colleague_id = await add_member(conn, org.id, "{owner}")
    first, colleague = await member_client(org.member), await member_client(colleague_id)
    row_id = await add(owner_engine, org.member, "Approved", org_id=org.id, link=f"/org/engagements/{uuid4()}")

    assert await ok(await colleague.get(URL)) == {"items": [], "next_cursor": None}
    assert await count(colleague) == 0
    refused = await colleague.post(f"{URL}/{row_id}/read")
    assert refused.status_code == 404
    assert refused.json()["detail"]["code"] == "not_found"
    assert await ok(await colleague.post(f"{URL}/read-all")) == {"count": 0}
    assert (await stored(owner_engine, row_id)).read_at is None
    assert await count(first) == 1


@pytest.mark.parametrize("limit", [0, -1, 51, "x"])
async def test_a_limit_outside_one_to_fifty_is_422(developers: Developers, limit: int | str) -> None:
    client = await developers()
    response = await client.get(URL, params={"limit": limit})
    assert response.status_code == 422, response.text
    assert (await client.get(URL, params={"limit": 50})).status_code == 200


@pytest.mark.parametrize(
    "cursor",
    ["nonsense", pagination.encode(None, uuid4()), "W10", "x" * 2001],
    ids=["garbage", "no-moment", "empty-array", "too-long"],
)
async def test_a_cursor_this_list_did_not_write_is_refused(developers: Developers, cursor: str) -> None:
    client = await developers()
    response = await client.get(URL, params={"cursor": cursor})
    if len(cursor) > pagination.MAX_CURSOR_CHARS:
        assert response.status_code == 422
        return
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "invalid_cursor"


async def test_signed_out_is_401(app_engine: AsyncEngine) -> None:
    async with make_client(app_engine) as anonymous:
        for method, path in (
            ("GET", URL),
            ("GET", f"{URL}/unread-count"),
            ("POST", f"{URL}/{uuid4()}/read"),
            ("POST", f"{URL}/read-all"),
        ):
            response = await anonymous.request(method, path)
            assert response.status_code == 401, (method, path, response.text)
            assert response.json()["detail"]["code"] == "unauthenticated"


@pytest.mark.parametrize(
    "link", ["https://evil.example/x", "//evil.example", "/\\evil.example", "/\t/evil.example", "engagements"]
)
async def test_a_stored_link_that_is_not_a_platform_path_is_never_served(
    developers: Developers, owner_engine: AsyncEngine, link: str
) -> None:
    """``post_in_app`` refuses such a link; a row written another way still never sends the browser elsewhere."""
    client = await developers()
    row_id = await add(owner_engine, user_of(client), "Odd link", link=link)
    [item] = (await ok(await client.get(URL)))["items"]
    assert item["link"] is None
    assert (await ok(await client.post(f"{URL}/{row_id}/read")))["link"] is None


async def test_reads_and_marking_read_write_no_audit_row(developers: Developers, owner_engine: AsyncEngine) -> None:
    client = await developers()
    row_id = await add(owner_engine, user_of(client), "Quiet")
    audit = text("SELECT count(*) FROM audit_events WHERE actor_user_id = :u")
    async with owner_engine.connect() as conn:
        before = (await conn.execute(audit, {"u": user_of(client)})).scalar_one()
    await ok(await client.get(URL))
    await ok(await client.get(f"{URL}/unread-count"))
    await ok(await client.post(f"{URL}/{row_id}/read"))
    await ok(await client.post(f"{URL}/read-all"))
    async with owner_engine.connect() as conn:
        assert (await conn.execute(audit, {"u": user_of(client)})).scalar_one() == before


async def test_the_list_sends_as_many_statements_with_twenty_rows_as_with_two(
    developers: Developers, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """P16-E1 item 5 (REQ-FND-01): one query per page, never one per row."""
    client = await developers()
    for n in range(SMALL):
        await add(owner_engine, user_of(client), f"Small {n}", ago=1000 - n)
    small, body = await counted(client, app_engine, URL)
    assert len(body["items"]) == SMALL
    for n in range(LARGE - SMALL):
        await add(owner_engine, user_of(client), f"Large {n}", ago=500 - n, read=n % 2 == 0)
    large, body = await counted(client, app_engine, URL)
    assert len(body["items"]) == LARGE
    assert large == small
