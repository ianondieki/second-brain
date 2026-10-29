"""Revision 0010 (REQ-DEV-02; P22 track B, D-60): the trend cards' schema rules, each test in one rolled-back
transaction.

- B6 at the database: a card enters only through ``app_create_trend_candidate`` (the weekly job, bridge_app with no
  user bound, or a staff admin's manual run), as a candidate with 1 to 5 checked sources, or not at all; a staff admin
  publishes or rejects it once (``app_decide_trend_card``); nothing of it changes otherwise, for any role.
- Readers: staff admin every card and source, a developer the published ones, nobody else any (staff moderators and
  organisation-only accounts included); nobody reads who decided; bridge_app writes neither table.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration.engagements import tracker as t
from tests.integration.events.schema_world import (
    CREATE_TREND,
    DECIDE_TREND,
    DENIED,
    card,
    people,
    source,
)

BAD_CARD = "the card is an object of title, summary and topic_slug"
BAD_TEXT = "a title of 1 to 120 characters"
BAD_SOURCES = "1 to 5 sources, each with an https URL"


async def create(conn: AsyncConnection, made: dict[str, Any], sources: list[dict[str, Any]]) -> UUID:
    found: UUID = await t.run(conn, CREATE_TREND, card=json.dumps(made), sources=json.dumps(sources))
    return found


async def counts(conn: AsyncConnection) -> tuple[int, int]:
    """As the owner: how many cards and sources there are."""
    await t.as_owner(conn)
    cards = await t.run(conn, "SELECT count(*) FROM trend_cards")
    sources = await t.run(conn, "SELECT count(*) FROM trend_card_sources")
    return int(cards), int(sources)


async def test_the_job_or_a_staff_admin_creates_a_candidate_with_its_sources(owner_engine: AsyncEngine) -> None:
    """Given the weekly job (bridge_app with no user bound), When it sends a card and two sources, Then a candidate is
    written with its sources at positions 1 and 2 in the order given (title, summary, publisher and support trimmed,
    the quote verbatim, confidence to three decimals); the job reads no trend row itself. A staff admin's manual run
    writes one too (a card without the optional keys); a staff moderator, a developer and an organisation member are
    refused."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        await t.act(conn, None)
        second = source(url="https://dev.example.test/notes", publisher="  Example Dev  ", support=" Phones. ")
        second |= {"quote": "  Verbatim, with its spaces.  ", "excerpt_ref": "tech:dev.2"}
        made = card(title="  Edge AI moves onto phones  ", named_orgs=["Example Phones"])
        card_id = await create(conn, made, [source(), second])
        assert await t.run(conn, "SELECT count(*) FROM trend_cards") == 0  # the job reads no trend row
        assert await t.run(conn, "SELECT count(*) FROM trend_card_sources") == 0
        await t.as_owner(conn)
        row = (await conn.execute(sa.text("SELECT * FROM trend_cards WHERE id = :id"), {"id": card_id})).one()
        assert (row.status, row.title, row.topic_slug, row.confidence, row.llm_trace_id) == (
            "candidate",
            "Edge AI moves onto phones",
            "edge-ai",
            Decimal("0.813"),
            "trend-0001",
        )
        assert (row.named_orgs, row.decided_by, row.decided_at, row.published_at) == (
            ["Example Phones"],
            None,
            None,
            None,
        )
        sources = (
            await conn.execute(
                sa.text(
                    "SELECT position, url, publisher, published_date, retrieved_at, quote, excerpt_ref, support"
                    " FROM trend_card_sources WHERE card_id = :id ORDER BY position"
                ),
                {"id": card_id},
            )
        ).all()
        assert [(s.position, s.publisher, s.excerpt_ref, s.support) for s in sources] == [
            (1, "Example Tech Blog", "tech:edge-ai.1", "Edge AI adoption is growing."),
            (2, "Example Dev", "tech:dev.2", "Phones."),
        ]
        assert sources[1].quote == "  Verbatim, with its spaces.  "
        assert (str(sources[0].published_date), str(sources[0].retrieved_at)) == ("2026-09-01", "2026-09-02")
        await t.act(conn, p.admin)
        manual = await create(
            conn, {"title": "Rust in firmware", "summary": "Vendors ship Rust.", "topic_slug": "rust"}, [source()]
        )
        await t.as_owner(conn)
        assert await t.run(
            conn, "SELECT named_orgs = '{}' AND confidence IS NULL FROM trend_cards WHERE id = :id", id=manual
        )
        for user, org in ((p.moderator, None), (p.developer, None), (p.owner, p.org), (p.viewer, p.org)):
            await t.act(conn, user, org)
            await t.expect(
                conn,
                CREATE_TREND,
                "the trend job with no user bound, or staff admin",
                card=json.dumps(card()),
                sources=json.dumps([source()]),
            )


async def test_a_malformed_card_or_source_writes_nothing(owner_engine: AsyncEngine) -> None:
    """A card that is not an object of the known keys, a title, summary, slug, confidence, trace id or named
    organisation out of its rule, and sources that are not 1 to 5 valid objects (exactly the seven string keys, an
    https URL on an ASCII host without user info or whitespace, 400 characters at most, a publisher, quote and support
    of their lengths without control characters, an excerpt ref of its pattern, real dates retrieved on or after
    published and not after today) are each refused, and nothing is written."""
    async with t.as_app(owner_engine) as conn:
        await people(conn)
        before = await counts(conn)
        today: Any = await t.run(conn, "SELECT app_nairobi_today()")
        tomorrow = str(today + timedelta(days=1))
        without_quote = source()
        del without_quote["quote"]
        cards: tuple[tuple[Any, str], ...] = (
            ([card()], BAD_CARD),
            ("a card", BAD_CARD),
            (card(extra="x"), BAD_CARD),
            (card(title=7), BAD_CARD),
            (card(confidence="0.9"), BAD_CARD),
            (card(llm_trace_id=12), BAD_CARD),
            (card(named_orgs="Example"), BAD_CARD),
            ({"summary": "No title.", "topic_slug": "x"}, BAD_TEXT),
            (card(title="t" * 121), BAD_TEXT),
            (card(title=" \n "), BAD_TEXT),
            (card(title="Bell\x07"), BAD_TEXT),
            (card(summary="s" * 601), BAD_TEXT),
            (card(summary="Line\nbreak"), BAD_TEXT),
            (card(topic_slug="Edge-AI"), BAD_TEXT),
            (card(topic_slug="edge ai"), BAD_TEXT),
            (card(topic_slug="edge--ai"), BAD_TEXT),
            (card(topic_slug="e" * 41), BAD_TEXT),
            (card(llm_trace_id="has space"), BAD_TEXT),
            (card(llm_trace_id="t" * 81), BAD_TEXT),
            (card(confidence=1.5), "confidence is 0 to 1"),
            (card(confidence=-0.1), "confidence is 0 to 1"),
            (card(named_orgs=[f"Org {n}" for n in range(11)]), "named organisations"),
            (card(named_orgs=["Example", "Example"]), "named organisations"),
            (card(named_orgs=["  "]), "named organisations"),
            (card(named_orgs=["Tab\there"]), "named organisations"),
            (card(named_orgs=[7]), "named organisations"),
        )
        bad_sources: tuple[Any, ...] = (
            None,
            [],
            {"url": "https://x.example.test/"},
            [source()] * 6,
            ["https://blog.example.test/"],
            [without_quote],
            [source(extra="x")],
            [source(published_date=20260901)],
            [source(url="http://blog.example.test/post")],
            [source(url="https://user:pw@blog.example.test/post")],
            [source(url="https://blog.example.test/a b")],
            [source(url="https://blög.example.test/post")],
            [source(url="https://blog.example.test/" + "x" * 375)],
            [source(publisher=" ")],
            [source(publisher="p" * 161)],
            [source(quote="q" * 601)],
            [source(quote="Two\nlines")],
            [source(support="s" * 401)],
            [source(excerpt_ref="has space")],
            [source(excerpt_ref="e" * 33)],
            [source(published_date="2026-02-30")],
            [source(published_date="2026-9-1")],
            [source(retrieved_at="2026-08-31")],  # before it was published
            [source(published_date=tomorrow, retrieved_at=tomorrow)],  # not yet
            [source(), source(url="ftp://files.example.test/")],  # one bad source refuses the card
        )
        await t.act(conn, None)
        for made, match in cards:
            await t.expect(conn, CREATE_TREND, match, card=json.dumps(made), sources=json.dumps([source()]))
        await t.expect(
            conn, "SELECT app_create_trend_candidate(NULL, CAST(:s AS jsonb))", BAD_CARD, s=json.dumps([source()])
        )
        for sources in bad_sources:
            await t.expect(conn, CREATE_TREND, BAD_SOURCES, card=json.dumps(card()), sources=json.dumps(sources))
        assert await counts(conn) == before
        await t.act(conn, None)
        five = [source(excerpt_ref=f"tech:{n}") for n in range(5)]
        await create(conn, card(confidence=1, named_orgs=[f"Org {n}" for n in range(10)]), five)
        await create(conn, card(confidence=None, llm_trace_id=None, title="t" * 120, summary="s" * 600), [source()])
        assert await counts(conn) == (before[0] + 2, before[1] + 6)


async def published_and_others(conn: AsyncConnection, admin: UUID) -> tuple[UUID, UUID, UUID]:
    """As the job: three candidates; as ``admin``: the first published, the second rejected."""
    await t.act(conn, None)
    ids = [await create(conn, card(title=f"Trend {n}"), [source(), source(excerpt_ref=f"tech:{n}")]) for n in range(3)]
    await t.act(conn, admin)
    await t.run(conn, DECIDE_TREND, card=ids[0], decision="publish")
    await t.run(conn, DECIDE_TREND, card=ids[1], decision="reject")
    return ids[0], ids[1], ids[2]


async def test_developers_read_published_cards_and_staff_admin_every_card(owner_engine: AsyncEngine) -> None:
    """A developer reads the published card and its sources, never a candidate's or a rejected one's; staff admin
    reads every card and source; a staff moderator, an organisation-only account, an organisation member and an
    unbound session read none; nobody reads who decided; bridge_app inserts, updates and deletes neither table."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        live, rejected, candidate = await published_and_others(conn, p.admin)
        ids = [live, rejected, candidate]
        cards = "SELECT id FROM trend_cards WHERE id = ANY(:ids)"
        sources = "SELECT card_id FROM trend_card_sources WHERE card_id = ANY(:ids)"
        readers: tuple[tuple[UUID | None, UUID | None, set[UUID]], ...] = (
            (p.developer, None, {live}),
            (p.other, None, {live}),
            (p.admin, None, set(ids)),
            (p.moderator, None, set()),
            (p.viewer, p.org, set()),
            (p.owner, p.org, set()),
            (None, None, set()),
        )
        for user, org, expected in readers:
            await t.act(conn, user, org)
            assert set((await conn.execute(sa.text(cards), {"ids": ids})).scalars()) == expected, user
            found = list((await conn.execute(sa.text(sources), {"ids": ids})).scalars())
            assert sorted(found) == sorted([*expected, *expected]), user  # two sources a card
        for user in (p.developer, p.admin):
            await t.act(conn, user)
            await t.expect(conn, "SELECT decided_by FROM trend_cards WHERE id = :id", DENIED, id=live)
            await t.expect(conn, "SELECT * FROM trend_cards WHERE id = :id", DENIED, id=live)
            readable = (
                "SELECT status, decided_at IS NOT NULL AND published_at IS NOT NULL FROM trend_cards WHERE id = :id"
            )
            assert tuple((await conn.execute(sa.text(readable), {"id": live})).one()) == ("published", True)
            for statement in (
                "INSERT INTO trend_cards (id, title, summary, topic_slug) VALUES (uuid7(), 'T', 'S', 'x')",
                "UPDATE trend_cards SET title = 'Changed' WHERE id = :id",
                "DELETE FROM trend_cards WHERE id = :id",
                "UPDATE trend_card_sources SET quote = 'Changed' WHERE card_id = :id",
                "DELETE FROM trend_card_sources WHERE card_id = :id",
            ):
                await t.expect(conn, statement, DENIED, id=live)


async def test_a_staff_admin_decides_a_candidate_once(owner_engine: AsyncEngine) -> None:
    """``app_decide_trend_card``: staff admin only (a moderator, a developer and the job are refused); publish sets
    ``published_at`` and the decision, reject the decision only; a decided card is never decided again; an unknown card
    and an unknown decision are refused."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        await t.act(conn, None)
        first = await create(conn, card(), [source()])
        second = await create(conn, card(), [source()])
        for user in (p.moderator, p.developer, None):
            await t.act(conn, user)
            await t.expect(conn, DECIDE_TREND, "staff admin only", card=first, decision="publish")
        await t.act(conn, p.admin)
        await t.expect(conn, DECIDE_TREND, "the decision is publish or reject", card=first, decision="published")
        await t.expect(conn, DECIDE_TREND, "no trend card with that id", card=uuid7(), decision="publish")
        await t.run(conn, DECIDE_TREND, card=first, decision="publish")
        await t.run(conn, DECIDE_TREND, card=second, decision="reject")
        for card_id in (first, second):
            for decision in ("publish", "reject"):
                await t.expect(conn, DECIDE_TREND, "the card was already decided", card=card_id, decision=decision)
        await t.as_owner(conn)
        decided = "SELECT status, decided_by, published_at IS NOT NULL AS dated FROM trend_cards WHERE id = :id"
        assert tuple((await conn.execute(sa.text(decided), {"id": first})).one()) == ("published", p.admin, True)
        assert tuple((await conn.execute(sa.text(decided), {"id": second})).one()) == ("rejected", p.admin, False)


async def test_a_card_and_its_sources_never_change_but_by_the_one_decision(owner_engine: AsyncEngine) -> None:
    """For every role (the owner too): a card's content, trace id, named organisations and creation time never change;
    its status moves once, from candidate to published (only with a source) or rejected, with its decision; a source
    joins only a candidate card, at a position of 1 to 5 not yet taken, and never changes."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        live, rejected, candidate = await published_and_others(conn, p.admin)
        await t.as_owner(conn)
        for assignment, card_id in (
            ("title = 'Changed'", candidate),
            ("summary = 'Changed'", live),
            ("named_orgs = '{Example}'", candidate),
            ("confidence = 0.1", candidate),
            ("llm_trace_id = 'other'", live),
            ("created_at = created_at - interval '1 day'", candidate),
        ):
            await t.expect(conn, f"UPDATE trend_cards SET {assignment} WHERE id = :id", "never change", id=card_id)
        for assignment, card_id in (
            ("status = 'candidate', decided_by = NULL, decided_at = NULL, published_at = NULL", live),
            ("status = 'published', published_at = now()", rejected),
            ("status = 'rejected', published_at = NULL", live),
            ("decided_at = now()", live),
        ):
            await t.expect(conn, f"UPDATE trend_cards SET {assignment} WHERE id = :id", "one decision", id=card_id)
        await t.expect(
            conn, "UPDATE trend_cards SET status = 'published' WHERE id = :id", "decision_complete", id=candidate
        )
        bare = uuid7()
        insert = "INSERT INTO trend_cards (id, title, summary, topic_slug) VALUES (:id, 'Bare', 'No source.', 'bare')"
        await t.run(conn, insert, id=bare)
        publish = (
            "UPDATE trend_cards SET status = 'published', decided_by = :admin, decided_at = now(), published_at = now()"
            " WHERE id = :id"
        )
        await t.expect(conn, publish, "published only with a source", id=bare, admin=p.admin)
        add = (
            "INSERT INTO trend_card_sources (id, card_id, position, url, publisher, published_date, retrieved_at,"
            " quote, excerpt_ref, support) VALUES (uuid7(), :card, :position, 'https://x.example.test/', 'P',"
            " DATE '2026-01-01', DATE '2026-01-02', 'Q.', 'ref', 'S.')"
        )
        for card_id in (live, rejected):
            await t.expect(conn, add, "only to a candidate card", card=card_id, position=3)
        await t.expect(conn, add, "uq_trend_card_sources_card_id_position", card=candidate, position=1)
        await t.expect(conn, add, "position_range", card=candidate, position=6)
        await t.run(conn, add, card=candidate, position=5)
        await t.expect(
            conn, "UPDATE trend_card_sources SET quote = 'Changed' WHERE card_id = :id", "append-only", id=candidate
        )
        await t.act(conn, None)  # the job holds no direct write either
        await t.expect(
            conn, "INSERT INTO trend_cards (id, title, summary, topic_slug) VALUES (uuid7(), 'T', 'S', 'x')", DENIED
        )
