"""Revision 0012 (REQ-PERS-01, REQ-PERS-02, REQ-EMB-01; P23-1, AC-PERS-3 at the database): profile and problem
embeddings, each test in one rolled-back transaction of the session database (other modules' committed rows may be
listed too, so each test asserts about its own rows).

- The indexes are HNSW over ``vector_cosine_ops``.
- ``app_profiles_to_embed`` lists developers (active, not staff) whose latest ``profiling`` decision is a grant and
  whose vector is missing or stale (another model or version; a profile edit, a liked-niche change, or a proposal
  published, hidden or changed since), with the text (headline, bio, liked niche names, the five latest published
  teasers; NFKC, whitespace collapsed, at most 8,000 characters), never embedded first; never anyone else.
- ``app_set_profile_embedding`` writes only under a granted consent for an active, non-staff developer; a withdrawal
  clears the vector in its own transaction (the consents trigger); ``app_clear_profile_embedding`` works for the
  worker and for the own row only.
- ``app_problems_to_embed`` lists published and clear problems only; ``app_set_problem_embedding`` re-checks that, so
  a problem held or archived after it was listed is not written.
- Every worker function refuses a bound session (insufficient_privilege) and malformed arguments
  (invalid_parameter_value); ``profile_embedded_at`` is readable with the own row only.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration.embeddings.schema_world import (
    COUNTS,
    MODEL,
    VERSION,
    age,
    decide,
    embed_profile,
    listed,
    named_niche,
    profiles,
    proposal,
    set_profile,
    stored_profile,
)
from tests.integration.engagements import tracker as t
from tests.integration.teams.schema_world import developer

INVALID = "22023"
DENIED = "42501"


async def niche(conn: AsyncConnection, label: str) -> UUID:
    """As the owner, whatever the connection acted as before: a niche named after ``label``."""
    return await named_niche(conn, label.title())


async def consented(
    conn: AsyncConnection, label: str, *, liked: tuple[UUID, ...] = (), staff: str | None = None
) -> UUID:
    """A developer with a liked niche (so their text is not empty) who granted profiling."""
    user = await developer(conn, label, peers=False, liked=liked or (await niche(conn, label),), staff=staff)
    await decide(conn, user, True)
    return user


async def test_the_indexes_are_hnsw_over_cosine_distance(owner_engine: AsyncEngine) -> None:
    """Given revision 0012, Then both vector columns have an HNSW index whose operator class is vector_cosine_ops
    (the ranker orders by ``<=>``, as the originality check does on the teasers)."""
    async with t.as_app(owner_engine) as conn:
        found = await conn.execute(
            sa.text(
                "SELECT i.indexrelid::regclass::text AS name, a.amname, o.opcname FROM pg_index i"
                " JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_am a ON a.oid = c.relam"
                " JOIN pg_opclass o ON o.oid = i.indclass[0]"
                " WHERE i.indexrelid::regclass::text IN ('ix_developer_profiles_profile_embedding',"
                " 'ix_problems_embedding')"
            )
        )
        assert sorted(tuple(row) for row in found) == [
            ("ix_developer_profiles_profile_embedding", "hnsw", "vector_cosine_ops"),
            ("ix_problems_embedding", "hnsw", "vector_cosine_ops"),
        ]


async def test_a_consented_developer_is_listed_with_their_normalised_text(owner_engine: AsyncEngine) -> None:
    """Given a developer who granted profiling, with a headline and bio holding odd spacing, a control character and
    compatibility characters, liked niches (and a followed one), six published proposals, a draft and a hidden one,
    When the worker lists profiles to embed, Then they are listed with the headline, the bio, the liked niches' names
    (by sort order, then name) and the title and statement of the five latest published proposals (newest first), each
    NFKC-normalised and whitespace-collapsed, empty parts left out, one per line."""
    async with t.as_app(owner_engine) as conn:
        # created in an order that is neither the expected one nor its reverse, so the id is never the tie-break
        health, agri, zebra = (
            await named_niche(conn, "Health"),
            await named_niche(conn, "Agri"),
            await named_niche(conn, "Zebra", -1),
        )
        followed = await named_niche(conn, "Followed only")
        user = await developer(conn, "text", peers=False, liked=(health, agri, zebra), followed=(followed,))
        await t.run(
            conn,
            "UPDATE developer_profiles SET headline = :h, bio = :b WHERE user_id = :u",
            h="  Builds\u00a0fintech\t\ttools\x07 ",
            b="\uff2d-Pesa \ufb01xes\n\nfor   chamas",
            u=user,
        )
        for n in range(1, 7):
            statement = "   " if n == 3 else f"Statement {n}"  # a blank statement is left out
            await proposal(conn, user, agri, title=f"Title {n}", statement=statement, days_ago=n)
        await proposal(conn, user, agri, title="Draft", statement="Draft statement", status="draft")
        await proposal(conn, user, agri, title="Hidden", statement="Hidden statement", status="hidden", days_ago=0)
        await decide(conn, user, True)
        expected = ["Builds fintech tools", "M-Pesa fixes for chamas", "Zebra", "Agri", "Health"]
        for n in range(1, 6):
            expected += [f"Title {n}"] + ([] if n == 3 else [f"Statement {n}"])
        found = dict(await profiles(conn))
        assert found[user] == "\n".join(expected)


async def test_the_text_is_cut_at_8000_characters(owner_engine: AsyncEngine) -> None:
    """Given a developer whose bio alone is longer than 8,000 characters, Then their text is the first 8,000
    characters of the whole (headline first)."""
    async with t.as_app(owner_engine) as conn:
        user = await consented(conn, "long")
        await t.as_owner(conn)
        await t.run(
            conn,
            "UPDATE developer_profiles SET headline = 'Head', bio = :b WHERE user_id = :u",
            b="word " * 2000,
            u=user,
        )
        text = dict(await profiles(conn))[user]
        assert len(text) == 8000
        assert text.startswith("Head\nword word ")


async def test_only_a_granted_latest_profiling_decision_lists_a_developer(owner_engine: AsyncEngine) -> None:
    """Given developers with no decision, a grant, a grant then a withdrawal, a withdrawal then a grant, and only a
    marketing grant, When the worker lists profiles, Then only those whose latest profiling decision is a grant are
    listed; the counts follow."""
    async with t.as_app(owner_engine) as conn:
        await t.act(conn, None)
        before = (await conn.execute(sa.text(COUNTS), {"model": MODEL, "version": VERSION})).one()
        users = {}
        for label in ("none", "granted", "withdrawn", "regranted", "marketing"):
            users[label] = await developer(conn, label, peers=False, liked=(await niche(conn, label),))
        await decide(conn, users["granted"], True)
        await decide(conn, users["withdrawn"], True)
        await decide(conn, users["withdrawn"], False)
        await decide(conn, users["regranted"], False)
        await decide(conn, users["regranted"], True)
        await decide(conn, users["marketing"], True, "marketing")
        assert await listed(conn, *users.values()) == {users["granted"], users["regranted"]}
        await t.act(conn, None)
        after = (await conn.execute(sa.text(COUNTS), {"model": MODEL, "version": VERSION})).one()
        assert after.profiles == before.profiles + 2


async def test_staff_suspended_and_empty_profiles_are_never_listed_or_written(owner_engine: AsyncEngine) -> None:
    """Given consented developers who are staff, suspended, or have nothing to embed (no headline, bio, liked niche
    or published proposal), Then none is listed, and the writer writes none of the first two."""
    async with t.as_app(owner_engine) as conn:
        staff = await consented(conn, "staff", staff="admin")
        gone = await consented(conn, "gone")
        await t.as_owner(conn)
        await t.run(conn, "UPDATE users SET status = 'suspended' WHERE id = :u", u=gone)
        empty = await developer(conn, "empty", peers=False, followed=(await niche(conn, "followed"),))
        await decide(conn, empty, True)
        regular = await consented(conn, "regular")
        assert await listed(conn, staff, gone, empty, regular) == {regular}
        assert await set_profile(conn, staff) is False
        assert await set_profile(conn, gone) is False
        for user in (staff, gone):
            assert (await stored_profile(conn, user))["first"] is None


async def test_a_stale_model_or_version_is_listed_and_a_fresh_vector_is_not(owner_engine: AsyncEngine) -> None:
    """Given a consented developer whose vector the worker wrote with the current model and version, Then they are not
    listed for that model and version, and are listed for another model or another version; a vector without its time
    (written outside the worker) is stale."""
    async with t.as_app(owner_engine) as conn:
        user = await consented(conn, "fresh")
        await age(conn, user)
        assert await listed(conn, user) == {user}
        await embed_profile(conn, user)
        assert await listed(conn, user) == set()
        assert await listed(conn, user, model="other-model") == {user}
        assert await listed(conn, user, version="2") == {user}
        await t.as_owner(conn)
        await t.run(conn, "UPDATE developer_profiles SET profile_embedded_at = NULL WHERE user_id = :u", u=user)
        assert await listed(conn, user) == {user}
        await embed_profile(conn, user)  # a time without a vector (the owner's hand) is stale too
        await t.run(conn, "UPDATE developer_profiles SET profile_embedding = NULL WHERE user_id = :u", u=user)
        assert await listed(conn, user) == {user}


async def test_an_edit_a_liked_niche_change_or_a_teaser_change_makes_a_profile_stale(owner_engine: AsyncEngine) -> None:
    """Given consented developers embedded a minute ago with nothing changed since, When one edits their profile, one
    adds a liked niche, one removes one, one changes a liked niche to followed, one has a proposal published (by the
    app, or dated by the owner as a seed does), one hides a proposal and one has a published proposal's teaser
    changed, Then exactly those are listed; following or unfollowing a niche, changing a liked niche's weight and
    editing a draft proposal leave the vector fresh."""
    async with t.as_app(owner_engine) as conn:
        shared, extra = await niche(conn, "shared"), await niche(conn, "extra")
        labels = ["edit", "add", "remove", "unlike", "publish", "seeded", "hide", "teaser", "follow", "unfollow"]
        labels += ["weight", "draft"]
        users = {label: await consented(conn, label, liked=(shared, await niche(conn, label))) for label in labels}
        published = {
            label: await proposal(conn, users[label], shared, title="Teaser", statement="Statement")
            for label in ("hide", "teaser", "seeded")
        }
        followed = await niche(conn, "followed")
        await t.run(
            conn,
            "INSERT INTO developer_niches (user_id, niche_id, kind) VALUES (:u, :n, 'followed')",
            u=users["unfollow"],
            n=followed,
        )
        draft = await proposal(conn, users["draft"], shared, title="Draft", statement="Draft", status="draft")
        await age(conn, *users.values())
        for user in users.values():
            await embed_profile(conn, user)
        assert await listed(conn, *users.values()) == set()

        await t.act(conn, users["edit"])  # the app's PATCH: the ORM moves updated_at
        await t.run(
            conn,
            "UPDATE developer_profiles SET headline = 'New', updated_at = now() WHERE user_id = :u",
            u=users["edit"],
        )
        add = "INSERT INTO developer_niches (user_id, niche_id, kind) VALUES (:u, :n, CAST(:k AS niche_interest))"
        await t.act(conn, users["add"])
        await t.run(conn, add, u=users["add"], n=extra, k="liked")
        await t.act(conn, users["remove"])
        await t.run(
            conn, "DELETE FROM developer_niches WHERE user_id = :u AND niche_id = :n", u=users["remove"], n=shared
        )
        await t.act(conn, users["unlike"])
        await t.run(
            conn,
            "UPDATE developer_niches SET kind = 'followed' WHERE user_id = :u AND niche_id = :n",
            u=users["unlike"],
            n=shared,
        )
        await t.act(conn, users["follow"])
        await t.run(conn, add, u=users["follow"], n=extra, k="followed")
        await t.act(conn, users["unfollow"])
        await t.run(conn, "DELETE FROM developer_niches WHERE user_id = :u AND kind = 'followed'", u=users["unfollow"])
        await t.as_owner(conn)  # a seed dates a publication itself: published_at moves, updated_at does not
        await t.run(conn, "UPDATE proposals SET published_at = now() WHERE id = :id", id=published["seeded"])
        await t.act(conn, users["weight"])
        await t.run(conn, "UPDATE developer_niches SET weight = 2 WHERE user_id = :u", u=users["weight"])
        await proposal(conn, users["publish"], shared, title="New", statement="New", days_ago=0)
        await t.act(conn, users["hide"])  # proposals/lifecycle.py's hide
        await t.run(
            conn,
            "UPDATE proposals SET status = 'hidden', hidden_at = now(), updated_at = now() WHERE id = :id",
            id=published["hide"],
        )
        await t.act(conn, users["teaser"])  # a new version published: published_at stays, the teaser changes
        await t.run(
            conn, "UPDATE proposals SET title = 'Changed', updated_at = now() WHERE id = :id", id=published["teaser"]
        )
        await t.act(conn, users["draft"])
        await t.run(conn, "UPDATE proposals SET title = 'Still a draft', updated_at = now() WHERE id = :id", id=draft)
        stale = {users[label] for label in ("edit", "add", "remove", "unlike", "publish", "seeded", "hide", "teaser")}
        assert await listed(conn, *users.values()) == stale


async def test_never_embedded_first_then_the_oldest_vector(owner_engine: AsyncEngine) -> None:
    """Given consented developers never embedded, embedded long ago and embedded recently (all with another model),
    When the worker lists profiles for the current model, Then the never embedded come first (by user id), then the
    oldest vector; the limit bounds the page."""
    async with t.as_app(owner_engine) as conn:
        first = uuid7()  # the smaller id, inserted after the second, so the scan order is not the expected one
        second = await consented(conn, "never-b")
        await t.as_owner(conn)
        await t.run(
            conn, "INSERT INTO users (id, email, display_name) VALUES (:u, :e, 'First')", u=first, e=f"{first}@x.test"
        )
        await t.run(
            conn, "INSERT INTO developer_profiles (user_id, handle) VALUES (:u, :h)", u=first, h=f"first-{first.hex}"
        )
        await t.run(
            conn,
            "INSERT INTO developer_niches (user_id, niche_id, kind) VALUES (:u, :n, 'liked')",
            u=first,
            n=await niche(conn, "never-a"),
        )
        await decide(conn, first, True)
        old, recent = await consented(conn, "old"), await consented(conn, "recent")
        for user, minutes in ((old, 120), (recent, 5)):
            assert await set_profile(conn, user, model="previous")
            await t.as_owner(conn)
            await t.run(
                conn,
                "UPDATE developer_profiles SET profile_embedded_at = now() - make_interval(mins => :m)"
                " WHERE user_id = :u",
                m=minutes,
                u=user,
            )
        mine = {first, second, old, recent}
        order = [user for user, _ in await profiles(conn) if user in mine]
        assert first < second
        assert order == [first, second, old, recent]
        assert len(await profiles(conn, limit=1)) == 1
        assert len(await profiles(conn, limit=3)) <= 3
