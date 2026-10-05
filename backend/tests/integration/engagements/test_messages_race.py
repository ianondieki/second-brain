"""Revision 0008 (REQ-ENG-11): the thread's rules that need committed transactions, each in a database of its own.

- A message waits for an append in flight: the gate (``engagement_messages_1_open``) locks the engagement FOR KEY SHARE
  before it reads the state, so a message racing the engagement's end is refused once the end commits. (Without that
  lock the foreign key check would wait too, then let the message in under the snapshot taken before the end.)
- At most 10 message reports per reporter in 24 hours holds for concurrent sessions: ``app_report_message``
  serialises a reporter's reports (an advisory lock), so of two racing past the ninth exactly one is filed.
- An upload joins only a message of its own transaction (``app_xid_is_current``): a sent message never gains a file in
  a later transaction, its sender's included.
- The downgrade is destructive (it drops the thread, the shortlists and the saved searches): it refuses while any of
  the tables has a row unless run with ``-x allow_p21_loss=true``; a refusal leaves the database at 0008 as it was.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

from tests.integration import world as w
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.integration.engagements import tracker as t
from tests.integration.engagements.test_message_attachments_schema import SEND, upload
from tests.integration.engagements.test_messages_schema import LIMITED, MESSAGE, READ_ONLY, REPORT, message, post

P21_TABLES = (
    "engagement_messages",
    "engagement_message_attachments",
    "engagement_message_reads",
    "org_shortlist",
    "saved_searches",
)


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_p21_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "head"))
        yield database
    finally:
        drop_database(admin_url, name)


async def test_a_message_waits_for_an_end_in_flight_and_is_refused_once_it_commits(url: URL) -> None:
    """Given an open thread, When the developer's withdrawal is appended (holding the engagement's row lock) and a
    member posts meanwhile, Then the message waits for the append and, once the withdrawal commits, is refused: the
    thread is read-only."""
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        async with owner.begin() as conn:
            p = await t.parties(conn)
            await t.act(conn, p.developer)
            engagement = await t.engage(conn, p)
            await t.walk(conn, p, engagement, "INTEREST_CONFIRMED")
        async with app.connect() as poster, app.connect() as ender:
            await ender.begin()
            await t.act(ender, p.developer)
            await t.append(ender, engagement, p.developer, "developer", "withdraw", "INTEREST_CONFIRMED", "WITHDRAWN")
            await poster.begin()
            await t.act(poster, p.owner, p.org)  # its snapshot still sees INTEREST_CONFIRMED
            pid = await t.backend_pid(poster)
            sent = asyncio.create_task(poster.execute(sa.text(MESSAGE), message(engagement, p.owner, "org")))
            await t.wait_until_blocked(ender, pid, sent)  # the message waits for the append in flight
            await ender.commit()
            with pytest.raises(DBAPIError, match=READ_ONLY):
                await sent
            await poster.rollback()
        async with app.connect() as reader, reader.begin():
            await t.act(reader, p.owner, p.org)
            assert (
                await t.run(reader, "SELECT count(*) FROM engagement_messages WHERE engagement_id = :e", e=engagement)
                == 0
            )
    finally:
        await owner.dispose()
        await app.dispose()


async def test_two_reports_racing_past_the_ninth_leave_exactly_ten(url: URL) -> None:
    """Given a member with nine message reports committed in the last 24 hours, When two of their sessions report two
    more messages at once, Then the second waits for the first (the per-reporter lock), counts its committed report
    and is refused: exactly one of the two is filed, ten in all."""
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        async with owner.begin() as conn:
            p = await t.parties(conn)
            await t.act(conn, p.developer)
            engagement = await t.engage(conn, p)
            await t.walk(conn, p, engagement, "INTEREST_CONFIRMED")
            messages = [await post(conn, engagement, p.developer, "developer", body=f"#{n}") for n in range(11)]
            await t.act(conn, p.owner, p.org)
            for reported in messages[:9]:
                await conn.execute(sa.text(REPORT), {"m": reported, "reasons": ["spam"]})
        async with app.connect() as first, app.connect() as second:
            for session in (first, second):
                await session.begin()
                await t.act(session, p.owner, p.org)
            pid = await t.backend_pid(second)
            assert (await first.execute(sa.text(REPORT), {"m": messages[9], "reasons": ["spam"]})).one().created
            racing = asyncio.create_task(second.execute(sa.text(REPORT), {"m": messages[10], "reasons": ["abuse"]}))
            await t.wait_until_blocked(first, pid, racing)
            await first.commit()
            with pytest.raises(DBAPIError, match=LIMITED):
                await racing
            await second.rollback()
        async with owner.connect() as conn:
            filed = "SELECT subject_id FROM moderation_cases WHERE subject_type = 'message' AND reporter_id = :r"
            assert set((await conn.execute(sa.text(filed), {"r": p.owner})).scalars()) == set(messages[:10])
    finally:
        await owner.dispose()
        await app.dispose()


async def test_a_sent_message_never_gains_a_file_later(url: URL) -> None:
    """Given a message and a clean upload committed by the developer, When the developer tries to attach the upload
    (or a new one) to that message in a later transaction, Then the guard refuses: an upload joins only a message of
    its own transaction."""
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        async with owner.begin() as conn:
            p = await t.parties(conn)
            await t.act(conn, p.developer)
            engagement = await t.engage(conn, p)
            await t.walk(conn, p, engagement, "INTEREST_CONFIRMED")
        async with app.connect() as conn:
            async with conn.begin():
                await t.act(conn, p.developer)
                sent = await post(conn, engagement, p.developer, "developer", body="The plan follows.")
                staged = await upload(conn, engagement, p.developer)
            async with conn.begin():
                await t.act(conn, p.developer)
                newer = await upload(conn, engagement, p.developer)
                for ids in ([staged], [newer]):
                    await t.expect(conn, SEND, "in the transaction that sends it", m=sent, ids=ids)
                own = await post(conn, engagement, p.developer, "developer", body="Here it is.")
                assert await t.rowcount(conn, SEND, m=own, ids=[staged, newer]) == 2  # with a new message, fine
    finally:
        await owner.dispose()
        await app.dispose()


def _state(url: URL) -> tuple[str, dict[str, int | None]]:
    """The revision and each P21 table's row count (None when the table does not exist)."""
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as conn:
            version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
            counts: dict[str, int | None] = {}
            for table in P21_TABLES:
                exists = conn.execute(sa.text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"})
                counts[table] = (
                    conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() if exists.scalar_one() else None
                )
            return version, counts
    finally:
        engine.dispose()


def _with_flag(config: Config) -> None:
    config.cmd_opts = argparse.Namespace(x=["allow_p21_loss=true"])
    command.downgrade(config, "0007")


async def test_the_downgrade_refuses_to_drop_the_thread_unless_told_to(url: URL) -> None:
    engine = role_engine(url, "bridge_owner")
    try:
        async with engine.begin() as conn:
            await w.build(conn, "p21")  # two messages, an attachment and a marker per tenant; a shortlist; a search
    finally:
        await engine.dispose()
    held = {
        "engagement_messages": 4,
        "engagement_message_attachments": 2,
        "engagement_message_reads": 2,
        "org_shortlist": 2,
        "saved_searches": 2,
    }
    assert _state(url) == ("0008", held)
    with pytest.raises(RuntimeError, match="hold the parties' messages, shortlists or saved searches"):
        run_alembic(url, lambda config: command.downgrade(config, "0007"))
    assert _state(url) == ("0008", held)  # nothing was dropped
    run_alembic(url, _with_flag)
    assert _state(url) == ("0007", dict.fromkeys(P21_TABLES))
    run_alembic(url, lambda config: command.upgrade(config, "0008"))
    assert _state(url) == ("0008", dict.fromkeys(P21_TABLES, 0))
