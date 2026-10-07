"""Revision 0012 (REQ-PERS-01, REQ-PERS-02, REQ-EMB-01; P23-1, AC-PERS-3 at the database): profile and problem
embeddings, each test in one rolled-back transaction of the session database (other modules' committed rows may be
listed too, so each test asserts about its own rows).

- The indexes are HNSW over ``vector_cosine_ops``.
- ``app_profiles_to_embed`` lists developers (active, not staff) whose latest ``profiling`` decision is a grant and
  whose vector is missing or stale (another model or version, or a stored hash that is not the hash of the text now:
  a profile edit, a liked niche added, removed or renamed, a proposal published, hidden or with a new teaser), with
  the text (headline, bio, liked niche names, the five latest published teasers; NFKC, whitespace collapsed, at most
  8,000 characters) and its SHA-256, never embedded first; never anyone else. An update that changes no part of the
  text (a moved ``updated_at``, a followed niche, a weight, a draft) leaves the vector fresh.
- ``app_set_profile_embedding`` writes only under a granted consent for an active, non-staff developer and only with
  the hash of the text as it reads now (an edit between the listing and the write is never stamped as embedded); a
  withdrawal clears the vector in its own transaction (the consents trigger); ``app_clear_profile_embedding`` works for
  the worker and for the own row only.
- ``app_problems_to_embed`` lists published and clear problems only; ``app_set_problem_embedding`` re-checks that and
  the text's hash, so a problem held, archived or edited after it was listed is not written.
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
    CLEAR_EMPTY,
    COUNTS,
    EMPTY_PROBLEM,
    EMPTY_PROFILE,
    MODEL,
    PROBLEMS,
    PROFILES,
    SET_PROBLEM,
    SET_PROFILE,
    VERSION,
    WORKER_ONLY,
    decide,
    listed,
    named_niche,
    problem_text,
    problems,
    profile_text,
    profiles,
    proposal,
    set_problem,
    set_profile,
    sha,
    stored_problem,
    stored_profile,
    vector,
)
from tests.integration.engagements import tracker as t
from tests.integration.teams.schema_world import developer, org_only, organisation, refused

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
        found = {row.id: row for row in await profiles(conn)}
        assert found[user].text == "\n".join(expected)
        assert found[user].text_hash == sha(found[user].text)  # SHA-256 of the UTF-8 text, hex


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
        text = {row.id: row.text for row in await profiles(conn)}[user]
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


async def test_a_consent_decision_is_timed_by_the_database(owner_engine: AsyncEngine) -> None:
    """Given a developer, When bridge_app inserts a profiling grant dated a day ahead and then a withdrawal, Then both
    are stored at the transaction's time, so the withdrawal is the latest decision and the developer is not listed
    (security MINOR 2, round 3); the table's owner (a seed) keeps the time it sends."""
    async with t.as_app(owner_engine) as conn:
        user = await developer(conn, "dated", peers=False, liked=(await niche(conn, "dated"),))
        insert = (
            "INSERT INTO consents (id, user_id, purpose, granted, text_version, text_sha256, source, created_at)"
            " VALUES (:id, :u, 'profiling', :g, 'v1', :sha, 'settings', now() + interval '1 day') RETURNING created_at"
        )
        await t.act(conn, user)
        now = await t.run(conn, "SELECT now()")
        assert await t.run(conn, insert, id=uuid7(), u=user, g=True, sha=bytes(32)) == now
        await decide(conn, user, False)  # the settings page's withdrawal, at the database's time
        assert await listed(conn, user) == set()
        await t.as_owner(conn)
        seeded = await t.run(conn, insert, id=uuid7(), u=user, g=True, sha=bytes(32))
        assert seeded > now  # the owner's own time


async def test_staff_suspended_and_empty_profiles_are_never_listed_or_written(owner_engine: AsyncEngine) -> None:
    """Given consented developers who are staff, suspended, or have nothing to embed (no headline, bio, liked niche
    or published proposal), Then none is listed, and the writer writes none of them (an empty text, even with its
    hash, is never written)."""
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
        assert await set_profile(conn, empty, text_hash=sha("")) is False  # nothing to embed is never written
        for user in (staff, gone, empty):
            assert (await stored_profile(conn, user))["first"] is None


async def test_a_stale_model_version_or_hash_is_listed_and_a_fresh_vector_is_not(owner_engine: AsyncEngine) -> None:
    """Given a consented developer whose vector the worker wrote with the current model, version and the hash of their
    text, Then they are not listed for that model and version, and are listed for another model or version, when the
    stored hash is gone or another one, or when the vector is gone (the owner's hand); the vector's time only orders
    the list."""
    async with t.as_app(owner_engine) as conn:
        user = await consented(conn, "fresh")
        assert await listed(conn, user) == {user}
        assert await set_profile(conn, user)
        assert await listed(conn, user) == set()
        assert await listed(conn, user, model="other-model") == {user}
        assert await listed(conn, user, version="2") == {user}
        await t.as_owner(conn)
        await t.run(conn, "UPDATE developer_profiles SET profile_embedded_at = NULL WHERE user_id = :u", u=user)
        assert await listed(conn, user) == set()
        for change in (
            "profile_embedding_hash = NULL",
            f"profile_embedding_hash = '{sha('another text')}'",
            "profile_embedding = NULL",
        ):
            assert await set_profile(conn, user)
            await t.as_owner(conn)
            await t.run(conn, f"UPDATE developer_profiles SET {change} WHERE user_id = :u", u=user)
            assert await listed(conn, user) == {user}, change


async def test_a_change_to_the_text_makes_a_profile_stale_and_nothing_else_does(owner_engine: AsyncEngine) -> None:
    """Given consented developers whose vectors are fresh, When one edits their headline, one adds a liked niche, one
    removes one, one changes a liked niche to followed, one's liked niche is renamed by staff, one has a proposal
    published, one hides a proposal and one has a published proposal's teaser changed, Then exactly those are listed;
    an update that moves updated_at but changes no text, following or unfollowing a niche, changing a liked niche's
    weight, editing a draft proposal and moving a published proposal's dates leave the vector fresh."""
    async with t.as_app(owner_engine) as conn:
        shared, extra = await niche(conn, "shared"), await niche(conn, "extra")
        labels = ["edit", "add", "remove", "unlike", "rename", "publish", "hide", "teaser", "touch", "follow"]
        labels += ["unfollow", "weight", "draft", "redate"]
        users = {label: await consented(conn, label, liked=(shared, await niche(conn, label))) for label in labels}
        renamed = await niche(conn, "to-rename")
        await t.run(
            conn,
            "INSERT INTO developer_niches (user_id, niche_id, kind) VALUES (:u, :n, 'liked')",
            u=users["rename"],
            n=renamed,
        )
        published = {
            label: await proposal(conn, users[label], shared, title="Teaser", statement="Statement")
            for label in ("hide", "teaser", "redate")
        }
        followed = await niche(conn, "followed")
        await t.run(
            conn,
            "INSERT INTO developer_niches (user_id, niche_id, kind) VALUES (:u, :n, 'followed')",
            u=users["unfollow"],
            n=followed,
        )
        draft = await proposal(conn, users["draft"], shared, title="Draft", statement="Draft", status="draft")
        for user in users.values():
            assert await set_profile(conn, user)
        assert await listed(conn, *users.values()) == set()

        await t.act(conn, users["edit"])  # the app's PATCH
        await t.run(conn, "UPDATE developer_profiles SET headline = 'New' WHERE user_id = :u", u=users["edit"])
        await t.act(conn, users["touch"])  # an ORM update that changes nothing of the text (review MINOR 3)
        await t.run(
            conn,
            "UPDATE developer_profiles SET updated_at = now() + interval '1 hour' WHERE user_id = :u",
            u=users["touch"],
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
        await t.as_owner(conn)  # staff rename a niche
        await t.run(conn, "UPDATE niches SET name_en = 'Renamed' WHERE id = :n", n=renamed)
        await t.act(conn, users["follow"])
        await t.run(conn, add, u=users["follow"], n=extra, k="followed")
        await t.act(conn, users["unfollow"])
        await t.run(conn, "DELETE FROM developer_niches WHERE user_id = :u AND kind = 'followed'", u=users["unfollow"])
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
        await t.as_owner(conn)  # one proposal: its dates order nothing
        await t.run(
            conn,
            "UPDATE proposals SET published_at = now() + interval '1 hour', updated_at = now() + interval '1 hour'"
            " WHERE id = :id",
            id=published["redate"],
        )
        stale = {users[label] for label in ("edit", "add", "remove", "unlike", "rename", "publish", "hide", "teaser")}
        assert await listed(conn, *users.values()) == stale


async def test_an_edit_between_the_listing_and_the_write_is_never_stamped(owner_engine: AsyncEngine) -> None:
    """Given a developer and a problem the worker listed with their texts' hashes, When the headline and the problem's
    statement change before the vectors are written (review MAJOR: freshness by time lost such an edit), Then the
    writers write nothing and return false; both are listed again with the new texts' hashes, and written with those
    they are fresh."""
    async with t.as_app(owner_engine) as conn:
        user = await consented(conn, "racing")
        issue = await w.add_problem(conn, user, await niche(conn, "racing-problem"))
        profile = {row.id: row for row in await profiles(conn)}[user]
        problem = {row.id: row for row in await problems(conn)}[issue]
        await t.act(conn, user)
        await t.run(conn, "UPDATE developer_profiles SET headline = 'Edited meanwhile' WHERE user_id = :u", u=user)
        await t.run(conn, "UPDATE problems SET statement = 'Edited meanwhile' WHERE id = :id", id=issue)
        assert await set_profile(conn, user, text_hash=profile.text_hash) is False
        assert await set_problem(conn, issue, text_hash=problem.text_hash) is False
        assert await stored_profile(conn, user) == EMPTY_PROFILE
        assert await stored_problem(conn, issue) == EMPTY_PROBLEM
        again = {row.id: row for row in await profiles(conn)}[user]
        assert again.text.startswith("Edited meanwhile\n")
        assert again.text_hash != profile.text_hash
        problem_again = {row.id: row for row in await problems(conn)}[issue]
        assert problem_again.text_hash == sha(await problem_text(conn, issue)) != problem.text_hash
        assert await set_profile(conn, user, text_hash=again.text_hash) is True
        assert await set_problem(conn, issue, text_hash=problem_again.text_hash) is True
        assert await listed(conn, user) == set()
        assert issue not in {row.id for row in await problems(conn)}


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
        order = [row.id for row in await profiles(conn) if row.id in mine]
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
        ok: dict[str, object] = {
            "model": MODEL,
            "version": VERSION,
            "limit": 10,
            "vector": vector(),
            "text_hash": sha(await profile_text(conn, user)),
        }
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
        for bad_hash in (None, "", "0" * 63, "A" * 64, "g" * 64, "0" * 65):
            await refused(conn, SET_PROFILE, "the text's hash", INVALID, **{**ok, "user": user, "text_hash": bad_hash})
            await refused(
                conn, SET_PROBLEM, "the text's hash", INVALID, **{**ok, "problem": issue, "text_hash": bad_hash}
            )
        await refused(conn, COUNTS, "or neither", INVALID, model=MODEL, version=None)
        await refused(conn, COUNTS, "or neither", INVALID, model=None, version=VERSION)
        await refused(conn, COUNTS, "or neither", INVALID, model="", version=VERSION)
        assert (await conn.execute(sa.text(COUNTS), {"model": None, "version": None})).one() is not None
        assert (await conn.execute(sa.text(COUNTS), {"model": MODEL, "version": "1" * 40})).one() is not None
        assert await t.run(conn, SET_PROFILE, **{**ok, "user": user, "model": "m" * 80, "version": "v" * 40}) is True


async def test_the_writer_writes_only_under_a_granted_profiling_consent(owner_engine: AsyncEngine) -> None:
    """Given developers who granted, withdrew or never decided, and an id with no profile, When the worker writes
    their vectors, Then only the granted one is written (vector, model, version, the transaction's time and the text's
    hash) and the writer says so; the others are left without a vector and the writer returns false."""
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
            "profile_embedding_hash": sha(await profile_text(conn, granted)),
        }
        for user in (withdrawn, never, no_profile, uuid7()):
            assert await set_profile(conn, user) is False
        for user in (withdrawn, never):
            assert await stored_profile(conn, user) == EMPTY_PROFILE


async def test_a_withdrawal_clears_the_vector_in_its_own_transaction(owner_engine: AsyncEngine) -> None:
    """Given an embedded developer, When they record a marketing decision or a profiling grant, Then the vector stays;
    When they withdraw profiling (as themselves, or a row the owner inserts), Then the vector, model, version, time and
    hash are NULL before the transaction ends, and the developer is no longer listed (AC-PERS-3); the withdrawal writes
    the profile's row (updated_at moves) even when there is no vector, so a writer racing it always meets the write
    (review MINOR 2)."""
    async with t.as_app(owner_engine) as conn:
        user, seeded = await consented(conn, "optout"), await consented(conn, "seeded")
        bare = await consented(conn, "bare")  # never embedded
        for embedded in (user, seeded):
            assert await set_profile(conn, embedded)
        await t.as_owner(conn)
        await t.run(
            conn,
            "UPDATE developer_profiles SET updated_at = now() - interval '1 hour' WHERE user_id = ANY(:u)",
            u=[user, seeded, bare],
        )
        await decide(conn, user, False, "marketing")
        await decide(conn, user, True)
        assert (await stored_profile(conn, user))["first"] == 1.0
        untouched = "SELECT updated_at < now() FROM developer_profiles WHERE user_id = :u"
        assert await t.run(conn, untouched, u=user) is True  # neither a marketing decision nor a grant writes it
        await decide(conn, user, False)
        await decide(conn, seeded, False, as_owner=True)
        await decide(conn, bare, False)
        for withdrawn in (user, seeded, bare):
            assert await stored_profile(conn, withdrawn) == EMPTY_PROFILE
            touched = "SELECT updated_at = now() FROM developer_profiles WHERE user_id = :u"
            assert await t.run(conn, touched, u=withdrawn) is True
        assert await listed(conn, user, seeded) == set()


@pytest.mark.parametrize("level", ["REPEATABLE READ", "SERIALIZABLE"])
async def test_the_writers_run_at_read_committed_only(owner_engine: AsyncEngine, level: str) -> None:
    """Given a transaction at REPEATABLE READ or SERIALIZABLE, When the worker writes a profile's or a problem's vector,
    Then both writers refuse (invalid_transaction_state): their consent, state and text reads after the row lock would
    see the snapshot, not the committed state (review MINOR 2)."""
    async with t.as_app(owner_engine) as conn:
        await t.run(conn, f"SET TRANSACTION ISOLATION LEVEL {level}")
        user = await consented(conn, "isolated")
        issue = await w.add_problem(conn, user, await niche(conn, "isolated"))
        common = {"vector": vector(), "model": MODEL, "version": VERSION}
        profile_hash, problem_hash = sha(await profile_text(conn, user)), sha(await problem_text(conn, issue))
        await t.act(conn, None)
        match = f"must run at READ COMMITTED isolation, not {level}"
        await refused(conn, SET_PROFILE, match, "25000", **common, user=user, text_hash=profile_hash)
        await refused(conn, SET_PROBLEM, match, "25000", **common, problem=issue, text_hash=problem_hash)


async def test_a_profile_is_inserted_without_an_embedding(owner_engine: AsyncEngine) -> None:
    """Given a new user, When bridge_app inserts their profile with a vector, a model, a version, a time or a hash,
    Then row-level security refuses it (the INSERT policy, review MINOR 3); with all of them NULL, as the signup's ORM
    insert sends them, the profile is created."""
    async with t.as_app(owner_engine) as conn:
        await t.as_owner(conn)
        user = await w.add_user(conn, f"signup-{uuid7().hex}@example.test", "Signup")
        insert = (
            "INSERT INTO developer_profiles (user_id, handle, profile_embedding, embed_model, embed_version,"
            " profile_embedded_at, profile_embedding_hash) VALUES (:u, :h, CAST(:v AS vector), :m, :ver, :at, :hash)"
        )
        nothing = {"v": None, "m": None, "ver": None, "at": None, "hash": None}
        await t.act(conn, user)
        now = await t.run(conn, "SELECT now()")
        for planted in ({"v": vector()}, {"m": MODEL}, {"ver": VERSION}, {"at": now}, {"hash": sha("planted")}):
            params = {**nothing, **planted, "u": user, "h": f"s-{user.hex}"}
            await refused(conn, insert, "row-level security", DENIED, **params)
        assert await t.rowcount(conn, insert, u=user, h=f"s-{user.hex}", **nothing) == 1


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
        assert await stored_profile(conn, brian) == EMPTY_PROFILE


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
    statement normalised on two lines and its hash; once embedded it is listed again only for another model or
    version, after an edit of its text, or when its vector or hash is gone (not after an update that changes no
    text)."""
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
        mine = set(ids.values())
        found = {row.id: row for row in await problems(conn) if row.id in mine}
        assert {problem: row.text for problem, row in found.items()} == {
            ids["open"]: "M-Pesa float\nAgents run out of float"
        }
        assert found[ids["open"]].text_hash == sha("M-Pesa float\nAgents run out of float")
        await t.as_owner(conn)
        long = await w.add_problem(conn, author, topic)  # a statement longer than the cap
        lengthen = "UPDATE problems SET title = 'Long', statement = :s WHERE id = :id"
        await t.run(conn, lengthen, s="word " * 2000, id=long)
        long_text = {row.id: row.text for row in await problems(conn)}[long]
        assert len(long_text) == 8000
        assert long_text.startswith("Long\nword word ")
        assert await set_problem(conn, ids["open"])
        assert not {row.id for row in await problems(conn)} & mine
        assert {row.id for row in await problems(conn, model="other")} & mine == {ids["open"]}
        assert {row.id for row in await problems(conn, version="2")} & mine == {ids["open"]}
        await t.as_owner(conn)  # an update that changes no text: still fresh
        await t.run(
            conn,
            "UPDATE problems SET updated_at = now() + interval '1 hour', embedded_at = NULL WHERE id = :id",
            id=ids["open"],
        )
        assert not {row.id for row in await problems(conn)} & mine
        for change in ("statement = 'Edited'", "embedding_hash = NULL", "embedding = NULL"):
            assert await set_problem(conn, ids["open"])
            await t.as_owner(conn)
            await t.run(conn, f"UPDATE problems SET {change} WHERE id = :id", id=ids["open"])
            assert {row.id for row in await problems(conn)} & mine == {ids["open"]}, change


async def test_a_problem_is_embedded_only_once_developers_may_read_it(owner_engine: AsyncEngine) -> None:
    """Given an E2 organisation's problems approved by staff (published and clear): one whose Brief is still a draft,
    one whose organisation is then delisted and one whose organisation loses its verification, When the worker lists
    problems, Then none is listed and the writer writes none (security MINOR 1, round 3; trend_facts' predicate, so a
    problem is embedded only once the recommender may show it: a developer of another organisation reads no draft
    Brief's problem); once the Brief is published and the organisations listed and verified again, each is listed and
    written."""
    async with t.as_app(owner_engine) as conn:
        member = await developer(conn, "briefer", peers=False)
        reader = await developer(conn, "reader", peers=False)
        topic = await niche(conn, "briefs")
        orgs, ids = {}, {}
        for label in ("draft", "delisted", "unverified"):
            orgs[label] = await organisation(conn, f"emb-{label}")
            await t.member(conn, orgs[label], member, "{owner,admin}")
            ids[label] = await w.add_problem(conn, member, topic, org_id=orgs[label])
            await t.run(
                conn,
                "INSERT INTO problem_briefs (problem_id, org_id, visibility, status) VALUES (:p, :o, 'public',"
                " CAST(:s AS brief_status))",
                p=ids[label],
                o=orgs[label],
                s="draft" if label == "draft" else "published",
            )
        await t.run(conn, "UPDATE organizations SET delisted_at = now() WHERE id = :o", o=orgs["delisted"])
        await t.run(conn, "UPDATE organizations SET verification = 'pending' WHERE id = :o", o=orgs["unverified"])
        mine = set(ids.values())
        assert not {row.id for row in await problems(conn)} & mine
        for problem_id in mine:
            assert await set_problem(conn, problem_id) is False
            assert await stored_problem(conn, problem_id) == EMPTY_PROBLEM
        await t.act(conn, reader)
        assert await t.run(conn, "SELECT count(*) FROM problems WHERE id = :id", id=ids["draft"]) == 0
        await t.as_owner(conn)  # moderation publishes the Brief; the organisations are listed and verified again
        await t.run(conn, "UPDATE problem_briefs SET status = 'published' WHERE problem_id = :p", p=ids["draft"])
        await t.run(conn, "UPDATE organizations SET delisted_at = NULL WHERE id = :o", o=orgs["delisted"])
        await t.run(conn, "UPDATE organizations SET verification = 'e2' WHERE id = :o", o=orgs["unverified"])
        assert {row.id for row in await problems(conn)} & mine == mine
        for problem_id in mine:
            assert await set_problem(conn, problem_id) is True


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
        assert await set_problem(conn, blank, text_hash=sha("")) is False  # nothing to embed is never written
        mine = {first, second, old, recent, blank}
        assert [row.id for row in await problems(conn) if row.id in mine] == [first, second, old, recent]
        assert len(await problems(conn, limit=1)) == 1
        assert len(await problems(conn, limit=3)) <= 3


async def test_the_problem_writer_writes_only_while_published_and_clear(owner_engine: AsyncEngine) -> None:
    """Given a published, clear problem the worker listed, When it is held, or archived, before its vector is
    written, Then the writer writes nothing and returns false; published and clear again, it is written (vector,
    model, version, the transaction's time); an unknown id is false."""
    async with t.as_app(owner_engine) as conn:
        author = await developer(conn, "writer", peers=False)
        issue = await w.add_problem(conn, author, await niche(conn, "writer"))
        assert issue in {row.id for row in await problems(conn)}
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
            assert await stored_problem(conn, issue) == EMPTY_PROBLEM
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
            "embedding_hash": sha(await problem_text(conn, issue)),
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


async def test_vectors_whose_text_became_empty_are_counted_and_cleared(owner_engine: AsyncEngine) -> None:
    """Given an embedded developer and an embedded problem, When everything their texts are made of is removed (the
    headline, bio, liked niche and published proposal; the problem's title and statement), Then neither is listed, both
    are counted, and app_clear_empty_embeddings clears their vector, model, version, time and hash and says so (review
    MAJOR, round 3); a vector whose text is not empty stays; a bound session and a transaction above READ COMMITTED
    are refused."""
    async with t.as_app(owner_engine) as conn:
        emptied, kept = await consented(conn, "emptied"), await consented(conn, "kept")
        topic = await niche(conn, "emptied-proposal")
        await proposal(conn, emptied, topic, title="Teaser", statement="Statement")
        issue = await w.add_problem(conn, emptied, topic)
        for user in (emptied, kept):
            assert await set_profile(conn, user)
        assert await set_problem(conn, issue)

        async def counts() -> tuple[int, int]:
            await t.act(conn, None)
            row = (await conn.execute(sa.text(COUNTS), {"model": MODEL, "version": VERSION})).one()
            return int(row.profiles), int(row.problems)

        before = await counts()
        await t.as_owner(conn)
        await t.run(conn, "UPDATE developer_profiles SET headline = ' ', bio = NULL WHERE user_id = :u", u=emptied)
        await t.run(conn, "DELETE FROM developer_niches WHERE user_id = :u", u=emptied)
        await t.run(conn, "UPDATE proposals SET status = 'hidden', hidden_at = now() WHERE owner_id = :u", u=emptied)
        await t.run(conn, "UPDATE problems SET title = ' ', statement = E'\\n' WHERE id = :id", id=issue)
        assert await profile_text(conn, emptied) == ""
        assert await listed(conn, emptied, kept) == set()
        assert issue not in {row.id for row in await problems(conn)}
        assert await counts() == (before[0] + 1, before[1] + 1)
        await t.act(conn, emptied)
        await refused(conn, CLEAR_EMPTY, WORKER_ONLY, DENIED)
        await t.act(conn, None)
        cleared = (await conn.execute(sa.text(CLEAR_EMPTY))).one()
        assert cleared.profiles >= 1
        assert cleared.problems >= 1
        assert await stored_profile(conn, emptied) == EMPTY_PROFILE
        assert await stored_problem(conn, issue) == EMPTY_PROBLEM
        assert (await stored_profile(conn, kept))["first"] == 1.0
        assert await counts() == before  # everything else the clearer cleared was counted before too
        await t.act(conn, None)
        assert tuple((await conn.execute(sa.text(CLEAR_EMPTY))).one()) == (0, 0)


async def test_the_empty_clearer_runs_at_read_committed_only(owner_engine: AsyncEngine) -> None:
    """Given a transaction at REPEATABLE READ, When the worker clears empty vectors, Then it is refused
    (invalid_transaction_state), as the writers are."""
    async with t.as_app(owner_engine) as conn:
        await t.run(conn, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        await t.act(conn, None)
        await refused(conn, CLEAR_EMPTY, "must run at READ COMMITTED isolation, not REPEATABLE READ", "25000")


async def test_erasing_a_developer_with_a_vector_and_niches_cascades(owner_engine: AsyncEngine) -> None:
    """Given a developer with a profile, a stored vector, liked and followed niches and consent decisions, When their
    account is deleted (the owner's erasure), Then the cascade removes the profile, the niches and the decisions."""
    async with t.as_app(owner_engine) as conn:
        liked, followed = await niche(conn, "cascade-liked"), await niche(conn, "cascade-followed")
        user = await developer(conn, "cascade", peers=False, liked=(liked,), followed=(followed,))
        await decide(conn, user, True)
        assert await set_profile(conn, user)
        await t.as_owner(conn)
        await t.run(conn, "DELETE FROM users WHERE id = :u", u=user)
        for table in ("developer_profiles", "developer_niches", "consents"):
            assert await t.run(conn, f"SELECT count(*) FROM {table} WHERE user_id = :u", u=user) == 0, table
