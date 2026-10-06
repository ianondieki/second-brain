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

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.embeddings.schema_world import (
    CLEAR,
    COUNTS,
    MODEL,
    PROBLEMS,
    PROFILES,
    SET_PROBLEM,
    SET_PROFILE,
    VERSION,
    WORKER_ONLY,
    age,
    decide,
    embed_problem,
    embed_profile,
    listed,
    named_niche,
    problems,
    profiles,
    proposal,
    set_problem,
    set_profile,
    stored_problem,
    stored_profile,
    vector,
)
from tests.integration.engagements import tracker as t
from tests.integration.teams.schema_world import developer, org_only, refused

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


async def test_the_worker_functions_refuse_a_bound_session_and_malformed_arguments(owner_engine: AsyncEngine) -> None:
    """Given a signed-in developer, When they call any of the worker's functions, Then each refuses them
    (insufficient_privilege); the worker's malformed arguments (no or overlong labels, a blank or control-character
    label, a limit outside 1 to 1000, no vector, a vector of other dimensions, the zero vector, a model without a
    version for the counts) are invalid_parameter_value."""
    async with t.as_app(owner_engine) as conn:
        user = await consented(conn, "bound")
        issue = await w.add_problem(conn, user, await niche(conn, "bound-problem"))
        ok: dict[str, object] = {"model": MODEL, "version": VERSION, "limit": 10, "vector": vector()}
        calls: tuple[tuple[str, dict[str, object]], ...] = (
            (PROFILES, {}),
            (PROBLEMS, {}),
            (SET_PROFILE, {"user": user}),
            (SET_PROBLEM, {"problem": issue}),
            (COUNTS, {}),
        )
        await t.act(conn, user)
        for sql, extra in calls:
            await refused(conn, sql, WORKER_ONLY, DENIED, **{**ok, **extra})
        await t.act(conn, None)
        for model, version in (
            (None, VERSION),
            (MODEL, None),
            ("", VERSION),
            (" ", VERSION),
            ("m" * 81, VERSION),
            (MODEL, "v" * 41),
            ("a\x01b", VERSION),
            (MODEL, "1\n"),
        ):
            labels = {"model": model, "version": version}
            for sql, extra in calls[:4]:
                await refused(conn, sql, "a model", INVALID, **{**ok, **extra, **labels})
        for limit in (0, 1001, None):
            for sql in (PROFILES, PROBLEMS):
                await refused(conn, sql, "a limit of 1 to 1000", INVALID, **{**ok, "limit": limit})
        for bad in (None, vector(dims=3), vector(0.0)):
            await refused(
                conn, SET_PROFILE, "a non-zero vector of 1024", INVALID, **{**ok, "user": user, "vector": bad}
            )
            await refused(
                conn, SET_PROBLEM, "a non-zero vector of 1024", INVALID, **{**ok, "problem": issue, "vector": bad}
            )
        await refused(conn, COUNTS, "or neither", INVALID, model=MODEL, version=None)
        await refused(conn, COUNTS, "or neither", INVALID, model=None, version=VERSION)
        await refused(conn, COUNTS, "or neither", INVALID, model="", version=VERSION)
        assert (await conn.execute(sa.text(COUNTS), {"model": None, "version": None})).one() is not None
        assert (await conn.execute(sa.text(COUNTS), {"model": MODEL, "version": "1" * 40})).one() is not None
        assert await t.run(conn, SET_PROFILE, **{**ok, "user": user, "model": "m" * 80, "version": "v" * 40}) is True


async def test_the_writer_writes_only_under_a_granted_profiling_consent(owner_engine: AsyncEngine) -> None:
    """Given developers who granted, withdrew or never decided, and an id with no profile, When the worker writes
    their vectors, Then only the granted one is written (vector, model, version and the transaction's time) and the
    writer says so; the others are left without a vector and the writer returns false."""
    async with t.as_app(owner_engine) as conn:
        granted = await consented(conn, "granted")
        withdrawn = await consented(conn, "withdrawn")
        await decide(conn, withdrawn, False)
        never = await developer(conn, "never", peers=False, liked=(await niche(conn, "never"),))
        no_profile = await org_only(conn)  # a profiling grant, but no developer profile
        await decide(conn, no_profile, True)
        assert await set_profile(conn, granted, first=0.5) is True
        now = await t.run(conn, "SELECT now()")
        assert await stored_profile(conn, granted) == {
            "first": 0.5,
            "embed_model": MODEL,
            "embed_version": VERSION,
            "profile_embedded_at": now,
        }
        for user in (withdrawn, never, no_profile, uuid7()):
            assert await set_profile(conn, user) is False
        for user in (withdrawn, never):
            assert await stored_profile(conn, user) == {
                "first": None,
                "embed_model": None,
                "embed_version": None,
                "profile_embedded_at": None,
            }


async def test_a_withdrawal_clears_the_vector_in_its_own_transaction(owner_engine: AsyncEngine) -> None:
    """Given an embedded developer, When they record a marketing decision or a profiling grant, Then the vector stays;
    When they withdraw profiling (as themselves, or a row the owner inserts), Then the vector, model, version and time
    are NULL before the transaction ends, and the developer is no longer listed (AC-PERS-3)."""
    async with t.as_app(owner_engine) as conn:
        user, seeded = await consented(conn, "optout"), await consented(conn, "seeded")
        for embedded in (user, seeded):
            assert await set_profile(conn, embedded)
        await decide(conn, user, False, "marketing")
        await decide(conn, user, True)
        assert (await stored_profile(conn, user))["first"] == 1.0
        await decide(conn, user, False)
        await decide(conn, seeded, False, as_owner=True)
        empty = {"first": None, "embed_model": None, "embed_version": None, "profile_embedded_at": None}
        for withdrawn in (user, seeded):
            assert await stored_profile(conn, withdrawn) == empty
        assert await listed(conn, user, seeded) == set()


async def test_the_clearer_serves_the_worker_and_the_own_row_only(owner_engine: AsyncEngine) -> None:
    """Given two embedded developers, When the first clears their own vector, Then it is cleared; When they name the
    other, Then they are refused (insufficient_privilege) and the other's vector stays; When the worker clears the
    other, Then it is cleared; an unknown user is a no-op."""
    async with t.as_app(owner_engine) as conn:
        amina, brian = await consented(conn, "amina"), await consented(conn, "brian")
        for user in (amina, brian):
            assert await set_profile(conn, user)
        await t.act(conn, amina)
        await t.run(conn, CLEAR, user=amina)
        assert (await stored_profile(conn, amina))["profile_embedded_at"] is None
        await t.act(conn, amina)
        await refused(conn, CLEAR, "the caller's own profile", DENIED, user=brian)
        await refused(conn, CLEAR, "the caller's own profile", DENIED, user=None)
        assert (await stored_profile(conn, brian))["first"] == 1.0
        await t.act(conn, None)
        await t.run(conn, CLEAR, user=brian)
        await t.run(conn, CLEAR, user=uuid7())
        assert await stored_profile(conn, brian) == {
            "first": None,
            "embed_model": None,
            "embed_version": None,
            "profile_embedded_at": None,
        }


async def test_profile_embedded_at_is_read_with_the_own_row_only(owner_engine: AsyncEngine) -> None:
    """Given two embedded developers, When the first reads profiles, Then they read their own vector's time and no
    row of the other's; neither may write it."""
    async with t.as_app(owner_engine) as conn:
        amina, brian = await consented(conn, "amina"), await consented(conn, "brian")
        for user in (amina, brian):
            assert await set_profile(conn, user)
        await t.act(conn, amina)
        read = "SELECT profile_embedded_at FROM developer_profiles WHERE user_id = :u"
        assert await t.run(conn, read, u=amina) == await t.run(conn, "SELECT now()")
        assert await t.rowcount(conn, read, u=brian) == 0
        await refused(
            conn,
            "UPDATE developer_profiles SET profile_embedded_at = NULL WHERE user_id = :u",
            "permission denied",
            DENIED,
            u=amina,
        )


async def test_problems_listed_are_published_and_clear_with_their_text(owner_engine: AsyncEngine) -> None:
    """Given problems published and clear, published but held, pending review, rejected, archived and candidate,
    When the worker lists problems to embed, Then only the published and clear one is listed, with its title and
    statement normalised on two lines; once embedded it is listed again only for another model or version, after an
    edit, or when its vector has no time."""
    async with t.as_app(owner_engine) as conn:
        author = await developer(conn, "author", peers=False)
        topic = await niche(conn, "problems")
        await t.as_owner(conn)
        states = {
            "open": ("published", "clear"),
            "held": ("published", "held"),
            "review": ("pending_review", "clear"),
            "rejected": ("rejected", "clear"),
            "archived": ("archived", "clear"),
            "candidate": ("candidate", "clear"),
        }
        ids = {
            label: await w.add_problem(conn, author, topic, status=status, moderation_state=state)
            for label, (status, state) in states.items()
        }
        await t.run(
            conn,
            "UPDATE problems SET title = :t, statement = :s WHERE id = :id",
            t="\uff2d-Pesa  float",
            s="Agents run\n\nout of float\x0b ",
            id=ids["open"],
        )
        found = {problem: text for problem, text in await problems(conn) if problem in set(ids.values())}
        assert found == {ids["open"]: "M-Pesa float\nAgents run out of float"}
        await embed_problem(conn, ids["open"])
        mine = set(ids.values())
        assert not {p for p, _ in await problems(conn)} & mine
        assert {p for p, _ in await problems(conn, model="other")} & mine == {ids["open"]}
        assert {p for p, _ in await problems(conn, version="2")} & mine == {ids["open"]}
        await t.as_owner(conn)
        await t.run(conn, "UPDATE problems SET statement = 'Edited', updated_at = now() WHERE id = :id", id=ids["open"])
        assert {p for p, _ in await problems(conn)} & mine == {ids["open"]}
        await embed_problem(conn, ids["open"])
        await t.run(conn, "UPDATE problems SET embedded_at = NULL WHERE id = :id", id=ids["open"])
        assert {p for p, _ in await problems(conn)} & mine == {ids["open"]}
        await embed_problem(conn, ids["open"])  # a time without a vector is stale too
        await t.run(conn, "UPDATE problems SET embedding = NULL WHERE id = :id", id=ids["open"])
        assert {p for p, _ in await problems(conn)} & mine == {ids["open"]}


async def test_problems_never_embedded_first_then_the_oldest_and_never_a_blank_one(owner_engine: AsyncEngine) -> None:
    """Given published, clear problems never embedded, embedded long ago and recently (with another model), and one
    whose title and statement are blank, When the worker lists problems for the current model, Then the never embedded
    come first (by id), then the oldest vector; the blank one is not listed; the limit bounds the page."""
    async with t.as_app(owner_engine) as conn:
        author = await developer(conn, "order", peers=False)
        topic = await niche(conn, "order")
        first = uuid7()  # the smaller id, inserted after the second, so the scan order is not the expected one
        second, old, recent, blank = [await w.add_problem(conn, author, topic) for _ in range(4)]
        await t.run(
            conn,
            "INSERT INTO problems (id, source, niche_id, title, statement, status, created_by)"
            " VALUES (:id, 'developer', :n, 'First', 'First statement', 'published', :u)",
            id=first,
            n=topic,
            u=author,
        )
        assert first < second
        await t.run(conn, "UPDATE problems SET title = ' ', statement = E'\\t' WHERE id = :id", id=blank)
        for problem_id, minutes in ((old, 120), (recent, 5)):
            assert await set_problem(conn, problem_id, model="previous")
            await t.as_owner(conn)
            await t.run(
                conn,
                "UPDATE problems SET embedded_at = now() - make_interval(mins => :m) WHERE id = :id",
                m=minutes,
                id=problem_id,
            )
        mine = {first, second, old, recent, blank}
        assert [p for p, _ in await problems(conn) if p in mine] == [first, second, old, recent]
        assert len(await problems(conn, limit=1)) == 1
        assert len(await problems(conn, limit=3)) <= 3


async def test_the_problem_writer_writes_only_while_published_and_clear(owner_engine: AsyncEngine) -> None:
    """Given a published, clear problem the worker listed, When it is held, or archived, before its vector is
    written, Then the writer writes nothing and returns false; published and clear again, it is written (vector,
    model, version, the transaction's time); an unknown id is false."""
    async with t.as_app(owner_engine) as conn:
        author = await developer(conn, "writer", peers=False)
        issue = await w.add_problem(conn, author, await niche(conn, "writer"))
        assert issue in {p for p, _ in await problems(conn)}
        empty = {"first": None, "embed_model": None, "embed_version": None, "embedded_at": None}
        for status, state in (("published", "held"), ("archived", "clear"), ("pending_review", "clear")):
            await t.as_owner(conn)
            await t.run(
                conn,
                "UPDATE problems SET status = CAST(:s AS problem_status), moderation_state = CAST(:m AS"
                " moderation_state) WHERE id = :id",
                s=status,
                m=state,
                id=issue,
            )
            assert await set_problem(conn, issue) is False, (status, state)
            assert await stored_problem(conn, issue) == empty
        await t.as_owner(conn)
        await t.run(
            conn, "UPDATE problems SET status = 'published', moderation_state = 'clear' WHERE id = :id", id=issue
        )
        assert await set_problem(conn, issue, first=0.25) is True
        now = await t.run(conn, "SELECT now()")
        assert await stored_problem(conn, issue) == {
            "first": 0.25,
            "embed_model": MODEL,
            "embed_version": VERSION,
            "embedded_at": now,
        }
        assert await set_problem(conn, uuid7()) is False


async def test_the_counts_follow_the_readers(owner_engine: AsyncEngine) -> None:
    """Given a consented developer and a published problem, both stale, Then the counts include each until the worker
    writes them; with no model and version the counts leave the model rule out (another model's vector is not stale
    then)."""
    async with t.as_app(owner_engine) as conn:

        async def counts(model: str | None = MODEL, version: str | None = VERSION) -> tuple[int, int]:
            await t.act(conn, None)
            row = (await conn.execute(sa.text(COUNTS), {"model": model, "version": version})).one()
            return int(row.profiles), int(row.problems)

        base, base_any = await counts(), await counts(None, None)
        user = await consented(conn, "counted")
        issue = await w.add_problem(conn, user, await niche(conn, "counted"))
        assert await counts() == (base[0] + 1, base[1] + 1)
        assert await counts(None, None) == (base_any[0] + 1, base_any[1] + 1)
        assert await set_profile(conn, user, model="previous")
        assert await set_problem(conn, issue, model="previous")
        assert await counts() == (base[0] + 1, base[1] + 1)  # another model's vector is stale for this one
        assert await counts(None, None) == base_any  # without a model, only missing or changed vectors
        assert await set_profile(conn, user)
        assert await set_problem(conn, issue)
        assert await counts() == base


@pytest.mark.parametrize("kind", ["liked", "followed"])
async def test_deleting_a_developer_with_niches_cascades(owner_engine: AsyncEngine, kind: str) -> None:
    """Given a developer with a profile, a vector and a niche, When their account is deleted (the owner's erasure),
    Then the cascade removes the profile and the niches; the liked-niche trigger does not stand in its way."""
    async with t.as_app(owner_engine) as conn:
        topic = await niche(conn, "cascade")
        niches = (topic,)
        if kind == "liked":
            user = await developer(conn, "cascade", peers=False, liked=niches)
        else:
            user = await developer(conn, "cascade", peers=False, followed=niches)
        await decide(conn, user, True)
        assert await set_profile(conn, user)
        await t.as_owner(conn)
        await t.run(conn, "DELETE FROM users WHERE id = :u", u=user)
        assert await t.run(conn, "SELECT count(*) FROM developer_profiles WHERE user_id = :u", u=user) == 0
        assert await t.run(conn, "SELECT count(*) FROM developer_niches WHERE user_id = :u", u=user) == 0
