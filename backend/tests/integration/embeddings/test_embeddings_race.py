"""Revision 0012 (REQ-PERS-02; AC-PERS-3): a profiling withdrawal and the worker's write never pass each other, in a
database of their own (the tests commit).

- The writer locks the profile, then reads the consent afresh; the withdrawal's trigger locks the same row. A write
  racing a withdrawal in flight waits for it and, once it commits, writes nothing (false).
- A withdrawal racing a write in flight waits for it and, once it commits, clears what the write left.
Either way the profile ends without a vector while the latest decision is a withdrawal.
- The problem writer locks the problem before it reads its state: a write racing a moderation hold in flight waits
  for it and, once it commits, writes nothing.
- ``app_clear_empty_embeddings`` locks each row before it reads its text again: a profile or problem whose text is
  given back while the clearer waits for it keeps its vector, and a row a withdrawal, an erasure or another run of
  the clearer clears while it waits counts for nothing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.integration.embeddings.schema_world import (
    CLEAR_EMPTY,
    CONSENT,
    MODEL,
    SET_PROBLEM,
    SET_PROFILE,
    VERSION,
    decide,
    named_niche,
    problem_text,
    profile_text,
    set_problem,
    set_profile,
    sha,
    vector,
)
from tests.integration.engagements import tracker as t
from tests.integration.teams.schema_world import developer

VECTOR = "SELECT profile_embedding IS NOT NULL FROM developer_profiles WHERE user_id = :u"


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_embed_race_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "head"))
        yield database
    finally:
        drop_database(admin_url, name)


async def _consented(owner: AsyncEngine) -> tuple[UUID, str]:
    """Committed: a developer with a liked niche who granted profiling, and their text's hash."""
    async with owner.begin() as conn:
        user = await developer(conn, "racer", peers=False, liked=(await named_niche(conn, "Racing"),))
        await decide(conn, user, True)
        text_hash = sha(await profile_text(conn, user))
    return user, text_hash


def _withdrawal(user: UUID) -> dict[str, object]:
    return {"id": uuid7(), "user": user, "purpose": "profiling", "granted": False, "sha": bytes(32)}


def _write(user: UUID, text_hash: str) -> dict[str, object]:
    return {"user": user, "vector": vector(), "model": MODEL, "version": VERSION, "text_hash": text_hash}


async def test_a_write_racing_a_withdrawal_writes_nothing_once_it_commits(url: URL) -> None:
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        user, text_hash = await _consented(owner)
        async with app.connect() as settings, app.connect() as worker:
            await settings.begin()
            await t.act(settings, user)
            await t.run(settings, CONSENT, **_withdrawal(user))  # the trigger holds the profile's row lock
            await worker.begin()
            await t.act(worker, None)  # its snapshot still sees the grant
            pid = await t.backend_pid(worker)
            write = asyncio.create_task(worker.execute(sa.text(SET_PROFILE), _write(user, text_hash)))
            await t.wait_until_blocked(settings, pid, write)  # the writer waits for the profile's row
            await settings.commit()
            assert (await write).scalar_one() is False
            await worker.commit()
        async with owner.connect() as conn:
            assert (await conn.execute(sa.text(VECTOR), {"u": user})).scalar_one() is False
    finally:
        await owner.dispose()
        await app.dispose()


async def test_a_withdrawal_racing_a_write_clears_it_once_it_commits(url: URL) -> None:
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        user, text_hash = await _consented(owner)
        async with app.connect() as worker, app.connect() as settings:
            await worker.begin()
            await t.act(worker, None)
            assert (await worker.execute(sa.text(SET_PROFILE), _write(user, text_hash))).scalar_one() is True
            await settings.begin()
            await t.act(settings, user)
            pid = await t.backend_pid(settings)
            withdraw = asyncio.create_task(settings.execute(sa.text(CONSENT), _withdrawal(user)))
            await t.wait_until_blocked(worker, pid, withdraw)  # the trigger waits for the written row
            await worker.commit()
            await withdraw
            await settings.commit()
        async with owner.connect() as conn:
            assert (await conn.execute(sa.text(VECTOR), {"u": user})).scalar_one() is False
    finally:
        await owner.dispose()
        await app.dispose()


async def test_a_problem_write_racing_a_hold_writes_nothing_once_it_commits(url: URL) -> None:
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        async with owner.begin() as conn:
            author = await developer(conn, "author", peers=False)
            issue = await w.add_problem(conn, author, await named_niche(conn, "Held"))
            text_hash = sha(await problem_text(conn, issue))
        async with app.connect() as holder, app.connect() as worker:
            await holder.begin()
            await t.act(holder, author)
            await t.run(holder, "SELECT app_hold_problem(:id)", id=issue)  # the author's hold, not yet committed
            await worker.begin()
            await t.act(worker, None)  # its snapshot still sees the problem published and clear
            pid = await t.backend_pid(worker)
            params = {"problem": issue, "vector": vector(), "model": MODEL, "version": VERSION, "text_hash": text_hash}
            write = asyncio.create_task(worker.execute(sa.text(SET_PROBLEM), params))
            await t.wait_until_blocked(holder, pid, write)  # the writer waits for the problem's row
            await holder.commit()
            assert (await write).scalar_one() is False
            await worker.commit()
        async with owner.connect() as conn:
            stored = "SELECT embedding IS NULL AND embedded_at IS NULL FROM problems WHERE id = :id"
            assert (await conn.execute(sa.text(stored), {"id": issue})).scalar_one() is True
    finally:
        await owner.dispose()
        await app.dispose()


@pytest.mark.parametrize("kind", ["profile", "problem"])
async def test_a_text_given_back_while_the_empty_clearer_waits_keeps_its_vector(url: URL, kind: str) -> None:
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        user, _ = await _consented(owner)
        async with owner.begin() as conn:
            issue = await w.add_problem(conn, user, await named_niche(conn, "Given back"))
            assert await set_profile(conn, user)
            assert await set_problem(conn, issue)
            await t.as_owner(conn)  # both texts emptied, and committed: the clearer's candidates
            await t.run(conn, "DELETE FROM developer_niches WHERE user_id = :u", u=user)
            await t.run(conn, "UPDATE problems SET title = ' ', statement = ' ' WHERE id = :id", id=issue)
        give_back = {
            "profile": ("UPDATE developer_profiles SET headline = 'Back again' WHERE user_id = :id", user),
            "problem": ("UPDATE problems SET title = 'Back again' WHERE id = :id", issue),
        }[kind]
        async with owner.connect() as editor, app.connect() as worker:
            await editor.begin()
            await t.run(editor, give_back[0], id=give_back[1])  # holds the row lock, not yet committed
            await worker.begin()
            await t.act(worker, None)  # its snapshot still sees both texts empty
            pid = await t.backend_pid(worker)
            clearing = asyncio.create_task(worker.execute(sa.text(CLEAR_EMPTY)))
            await t.wait_until_blocked(editor, pid, clearing)  # the clearer waits for the row
            await editor.commit()
            cleared = (await clearing).one()
            await worker.commit()
        assert tuple(cleared) == ((0, 1) if kind == "profile" else (1, 0))
        async with owner.connect() as conn:
            kept = {
                "profile": "SELECT profile_embedding IS NOT NULL FROM developer_profiles WHERE user_id = :id",
                "problem": "SELECT embedding IS NOT NULL FROM problems WHERE id = :id",
            }[kind]
            assert (await conn.execute(sa.text(kept), {"id": give_back[1]})).scalar_one() is True
    finally:
        await owner.dispose()
        await app.dispose()


@pytest.mark.parametrize("meanwhile", ["withdrawal", "erasure"])
async def test_a_row_cleared_while_the_empty_clearer_waits_is_not_counted(url: URL, meanwhile: str) -> None:
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        user, _ = await _consented(owner)
        async with owner.begin() as conn:
            assert await set_profile(conn, user)
            await t.as_owner(conn)  # the text emptied and committed: the clearer's candidate
            await t.run(conn, "DELETE FROM developer_niches WHERE user_id = :u", u=user)
        async with app.connect() as other, app.connect() as worker:
            await other.begin()
            if meanwhile == "withdrawal":  # the consents trigger clears the vector and holds the row
                await t.act(other, user)
                await t.run(other, CONSENT, **_withdrawal(user))
            else:  # the owner's erasure deletes the profile with the user
                await t.as_owner(other)
                await t.run(other, "DELETE FROM users WHERE id = :u", u=user)
            await worker.begin()
            await t.act(worker, None)  # its snapshot still sees the vector
            pid = await t.backend_pid(worker)
            clearing = asyncio.create_task(worker.execute(sa.text(CLEAR_EMPTY)))
            await t.wait_until_blocked(other, pid, clearing)  # the clearer waits for the row
            await other.commit()
            assert tuple((await clearing).one()) == (0, 0)
            await worker.commit()
    finally:
        await owner.dispose()
        await app.dispose()


@pytest.mark.parametrize("kind", ["profile", "problem"])
async def test_overlapping_empty_clearers_count_each_row_once(url: URL, kind: str) -> None:
    """Two runs of the job overlap: the first clears an emptied profile (or problem) and holds its row; the second,
    which already listed it, waits for the row and, once the first commits, clears and counts nothing."""
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        user, _ = await _consented(owner)
        async with owner.begin() as conn:
            issue = await w.add_problem(conn, user, await named_niche(conn, "Overlap"))
            if kind == "profile":  # one text emptied and committed, with its vector
                assert await set_profile(conn, user)
                await t.as_owner(conn)
                await t.run(conn, "DELETE FROM developer_niches WHERE user_id = :u", u=user)
            else:
                assert await set_problem(conn, issue)
                await t.as_owner(conn)
                await t.run(conn, "UPDATE problems SET title = ' ', statement = ' ' WHERE id = :id", id=issue)
        cleared = (1, 0) if kind == "profile" else (0, 1)
        async with app.connect() as first, app.connect() as second:
            await first.begin()
            await t.act(first, None)
            assert tuple((await first.execute(sa.text(CLEAR_EMPTY))).one()) == cleared
            await second.begin()
            await t.act(second, None)  # its snapshot still sees the vector
            pid = await t.backend_pid(second)
            clearing = asyncio.create_task(second.execute(sa.text(CLEAR_EMPTY)))
            await t.wait_until_blocked(first, pid, clearing)
            await first.commit()
            assert tuple((await clearing).one()) == (0, 0)
            await second.commit()
    finally:
        await owner.dispose()
        await app.dispose()
