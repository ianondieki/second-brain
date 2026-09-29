"""REQ-ENG-02 (schema half; AC-TRACK-2 "always leave a verifiable chain"): ``engagement_events`` is append-only and
hash-chained, and ``engagements.state`` is its projection, written by the database in the same statement.

- Creating an engagement starts its chain (the genesis event); each append links to the previous event, is timed and
  numbered by the database, and moves the projection (state, stage times, end); an independent verifier
  (``bridge.engagements.chain``) recomputes every hash and finds a changed, missing or reordered event.
- The state changes only by appending an event: bridge_app holds no UPDATE on it and the guard refuses a direct write
  by every role, the owner included; an event must start from the current state, and none follows a terminal one.
- UPDATE, DELETE and TRUNCATE of events, endorsements and signatures are refused (grants and triggers).
- Payloads hold ids, codes, dates, amounts and digests only.
- Appends to one engagement are serialised (a second writer waits on the row lock, then sees the first event).
- Engagements that predate revision 0003 get a genesis event on upgrade.
- The ORM maps it all: server-generated chain columns and the server-side ``lock_version`` counter.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from bridge.engagements import chain
from bridge.engagements.models import Engagement, EngagementEvent
from bridge.ids import uuid7
from bridge.models.enums import ContactChannel, EngagementActorRole, EngagementOrigin, EngagementState
from tests.integration.conftest import create_database, drop_database, run_alembic
from tests.integration.engagements.tracker import (
    APPEND,
    ENGAGE,
    Parties,
    act,
    append,
    as_app,
    as_owner,
    engage,
    event_params,
    expect,
    parties,
    run,
    walk,
)

EVENTS = (
    "SELECT seq, command, actor_user_id, actor_role::text AS actor_role, from_state::text AS from_state,"
    " to_state::text AS to_state, created_at, stage_deadline_at, prev_hash, hash"
    " FROM engagement_events WHERE engagement_id = :e ORDER BY seq"
)
PROJECTION = (
    "SELECT state::text AS state, end_reason::text AS end_reason, stage_entered_at, stage_deadline_at, ended_at,"
    " lock_version FROM engagements WHERE id = :e"
)
# An append that also sends the database's columns (they are replaced).
FORGED_APPEND = (
    "INSERT INTO engagement_events (id, engagement_id, actor_user_id, actor_role, command, from_state, to_state,"
    " stage_deadline_at, seq, prev_hash, hash, created_at) VALUES (:id, :e, :actor, 'reviewer', 'start_review',"
    " 'SUBMITTED', 'UNDER_REVIEW', :deadline, 99, :junk, :junk, :then)"
)


def engage_params(p: Parties, org: UUID, *, origin: str = "tagged", state: str = "SUBMITTED") -> dict[str, object]:
    return {
        "id": uuid7(),
        "p": p.proposal,
        "org": org,
        "dev": p.developer,
        "v": p.version,
        "origin": origin,
        "state": state,
    }


async def test_creating_an_engagement_starts_its_chain(owner_engine: AsyncEngine) -> None:
    """The genesis event (seq 1, command create) records the engagement as inserted, acted by the inserting party, at
    the engagement's stage time. The developer creates SUBMITTED with their open delivered tag, a signatory
    ORG_INTEREST; both only for an E2 organisation and the proposal's current registered version."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        (genesis,) = (await conn.execute(sa.text(EVENTS), {"e": engagement})).all()
        assert (genesis.seq, genesis.command, genesis.actor_user_id, genesis.actor_role) == (
            1,
            "create",
            p.developer,
            "developer",
        )
        assert (genesis.from_state, genesis.to_state, genesis.prev_hash) == (None, "SUBMITTED", chain.GENESIS)
        projection = (await conn.execute(sa.text(PROJECTION), {"e": engagement})).one()
        assert projection.stage_entered_at == genesis.created_at
        assert (projection.state, projection.ended_at, projection.lock_version) == ("SUBMITTED", None, 0)
        assert await chain.verify_chain(conn, engagement) == []
        payload = await run(conn, "SELECT payload FROM engagement_events WHERE engagement_id = :e", e=engagement)
        assert payload == {"origin": "tagged", "version_id": str(p.version)}

        # One engagement per proposal and organisation; no tag, no engagement; only the initial states.
        await expect(conn, ENGAGE, "uq_engagements_proposal_id_org_id", **engage_params(p, p.org))
        await expect(conn, ENGAGE, "row-level security", **engage_params(p, p.other_org))
        await expect(conn, ENGAGE, "row-level security", **engage_params(p, p.org, state="UNDER_REVIEW"))
        await act(conn, p.outsider)  # never another developer's proposal
        await expect(conn, ENGAGE, "row-level security", **engage_params(p, p.org))

        # ORG_INTEREST: a signatory of an E2 organisation (the scout's Express interest), never a reviewer.
        await act(conn, p.reviewer, p.org)
        interest = engage_params(p, p.org, origin="org_browse", state="ORG_INTEREST")
        await expect(conn, ENGAGE, "row-level security", **interest)
        await act(conn, p.other_member, p.other_org)
        interest = engage_params(p, p.other_org, origin="org_agent_match", state="ORG_INTEREST")
        await run(conn, ENGAGE, **interest)
        actor = "SELECT actor_user_id, actor_role::text FROM engagement_events WHERE engagement_id = :e"
        assert tuple((await conn.execute(sa.text(actor), {"e": interest["id"]})).one()) == (p.other_member, "signatory")
        # Below E2 nobody engages (docs/spec/06 6.8: Express interest requires E2).
        await as_owner(conn)
        await run(conn, "UPDATE organizations SET verification = 'e1' WHERE id = :id", id=p.org)
        await act(conn, p.signatory, p.org)
        await expect(
            conn, ENGAGE, "row-level security", **engage_params(p, p.org, origin="org_browse", state="ORG_INTEREST")
        )


async def test_events_extend_the_chain_and_move_the_projection(owner_engine: AsyncEngine) -> None:
    """Each append is numbered, linked and timed by the database (values sent are replaced); the engagement's state,
    stage times and deadline follow in the same statement; lock_version moves on every change; a same-state event
    keeps the stage time and may set a new deadline; the Python verifier agrees with the database's hashes."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        deadline = datetime(2026, 10, 13, 21, 0, tzinfo=UTC)
        await act(conn, p.reviewer, p.org)
        await run(
            conn,
            FORGED_APPEND,
            id=uuid7(),
            e=engagement,
            actor=p.reviewer,
            deadline=deadline,
            junk=bytes(32),
            then=datetime(2020, 1, 1, tzinfo=UTC),
        )
        first, second = (await conn.execute(sa.text(EVENTS), {"e": engagement})).all()
        assert (second.seq, second.prev_hash) == (2, first.hash)  # not the values sent
        assert first.created_at < second.created_at
        assert second.created_at > datetime.now(UTC) - timedelta(minutes=5)
        projection = (await conn.execute(sa.text(PROJECTION), {"e": engagement})).one()
        assert (projection.state, projection.stage_entered_at, projection.stage_deadline_at) == (
            "UNDER_REVIEW",
            second.created_at,
            deadline,
        )
        assert projection.lock_version == 1

        # A same-state event (one party's step inside a stage): the stage time stays, a new deadline may be set.
        later = deadline + timedelta(days=5)
        await append(
            conn,
            engagement,
            p.reviewer,
            "reviewer",
            "recommend",
            "UNDER_REVIEW",
            "UNDER_REVIEW",
            deadline=later,
            payload={"recommendation": "proceed"},
        )
        projection = (await conn.execute(sa.text(PROJECTION), {"e": engagement})).one()
        assert (projection.stage_entered_at, projection.stage_deadline_at, projection.lock_version) == (
            second.created_at,
            later,
            2,
        )
        # Entering a stage without a deadline clears the previous one.
        await act(conn, p.signatory, p.org)
        await append(conn, engagement, p.signatory, "signatory", "approve", "UNDER_REVIEW", "INTEREST_CONFIRMED")
        assert (await conn.execute(sa.text(PROJECTION), {"e": engagement})).one().stage_deadline_at is None

        rows = await chain.load_chain(conn, engagement)
        assert [r.seq for r in rows] == [1, 2, 3, 4]
        assert chain.verify_rows(rows) == []
        for row in rows:  # the canonical text is what the trigger hashed
            assert row.hash == hashlib.sha256(row.prev_hash + chain.canonical(row).encode()).digest()
        assert chain.canonical(rows[2]).startswith(f'{{"v":1,"id":"{rows[2].id}","engagement_id":"{engagement}"')
        assert chain.canonical(rows[2]).endswith(',"payload":{"recommendation": "proceed"}}')


async def test_the_verifier_finds_a_changed_missing_or_reordered_event(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        await walk(conn, p, engagement, "CONTACT_MADE")
        rows = await chain.load_chain(conn, engagement)
        assert len(rows) == 4
        assert chain.verify_rows(rows) == []
        edited = replace(rows[1], payload_text='{"recommendation": "decline"}')
        assert [problem.reason for problem in chain.verify_rows([rows[0], edited, *rows[2:]])] == [
            "hash does not match the row's contents"
        ]
        assert chain.verify_rows([*rows[:2], replace(rows[2], to_state="DECLINED"), rows[3]]) != []
        removed = {problem.reason for problem in chain.verify_rows([rows[0], *rows[2:]])}
        assert {"expected seq 2", "prev_hash does not link to the previous event"} <= removed
        assert chain.verify_rows([rows[1], rows[0], *rows[2:]]) != []  # reordered
        assert chain.verify_rows([replace(rows[0], created_at=rows[0].created_at + timedelta(microseconds=1))]) != []
        await act(conn, p.outsider)  # a non-party reads no event, so has nothing to verify
        assert await chain.verify_chain(conn, engagement) == [chain.ChainProblem(0, None, "no event")]


async def test_the_state_changes_only_by_appending_an_event(owner_engine: AsyncEngine) -> None:
    """bridge_app holds no UPDATE on the projection; the guard refuses a direct write for every role (the owner too);
    an event from a stale state is refused (409 for the state machine); a decline carries its reason code and ends the
    engagement; no event follows a terminal state; the parties, proposal and origin never change."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        for assignment in (
            "state = 'CLOSED'",
            "end_reason = 'BUDGET'",
            "stage_entered_at = now()",
            "stage_deadline_at = now()",
            "ended_at = now()",
            "lock_version = 7",
            "developer_id = developer_id",
            "origin = 'org_browse'",
        ):
            await expect(conn, f"UPDATE engagements SET {assignment} WHERE id = :e", "permission denied", e=engagement)
        await as_owner(conn)
        await expect(
            conn, "UPDATE engagements SET state = 'UNDER_REVIEW' WHERE id = :e", "only by appending", e=engagement
        )
        await expect(
            conn, "UPDATE engagements SET developer_id = :u WHERE id = :e", "never change", u=p.outsider, e=engagement
        )

        await act(conn, p.reviewer, p.org)
        stale = event_params(engagement, p.reviewer, "reviewer", "start_review", "UNDER_REVIEW", "INTEREST_CONFIRMED")
        await expect(conn, APPEND, "the engagement is in state SUBMITTED, not UNDER_REVIEW", **stale)
        genesis_again = event_params(engagement, p.reviewer, "reviewer", "start_review", None, "UNDER_REVIEW")
        await expect(conn, APPEND, "the engagement is in state SUBMITTED, not NULL", **genesis_again)
        await append(conn, engagement, p.reviewer, "reviewer", "start_review", "SUBMITTED", "UNDER_REVIEW")
        await act(conn, p.signatory, p.org)
        no_reason = event_params(engagement, p.signatory, "signatory", "decline", "UNDER_REVIEW", "DECLINED")
        await expect(conn, APPEND, "ck_engagement_events_end_reason_matches_state", **no_reason)
        await append(
            conn, engagement, p.signatory, "signatory", "decline", "UNDER_REVIEW", "DECLINED", reason="NOT_PRIORITY"
        )
        ended = (await conn.execute(sa.text(PROJECTION), {"e": engagement})).one()
        last = await run(conn, "SELECT max(created_at) FROM engagement_events WHERE engagement_id = :e", e=engagement)
        assert (ended.state, ended.end_reason, ended.ended_at, ended.stage_entered_at) == (
            "DECLINED",
            "NOT_PRIORITY",
            last,
            last,
        )
        await act(conn, p.developer)
        after = event_params(engagement, p.developer, "developer", "withdraw", "DECLINED", "WITHDRAWN")
        await expect(conn, APPEND, "ended in DECLINED and takes no further event", **after)
        await as_owner(conn)  # nothing reopens it, the owner included
        await expect(
            conn,
            "UPDATE engagements SET state = 'UNDER_REVIEW', end_reason = NULL, ended_at = NULL WHERE id = :e",
            "only by appending",
            e=engagement,
        )
        assert await chain.verify_chain(conn, engagement) == []


async def test_events_endorsements_and_signatures_are_insert_only(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        await walk(conn, p, engagement, "NDA_SIGNED")  # two endorsements and two signatures exist
        for table in ("engagement_events", "engagement_endorsements", "signatures"):
            assert await run(conn, f"SELECT count(*) FROM {table} WHERE engagement_id = :e", e=engagement) >= 2
            for sql in (
                f"UPDATE {table} SET id = id WHERE engagement_id = :e",
                f"DELETE FROM {table} WHERE engagement_id = :e",
                f"TRUNCATE {table}",
            ):
                await expect(conn, sql, "permission denied", e=engagement)
        await as_owner(conn)  # the triggers hold for every role
        for table in ("engagement_events", "engagement_endorsements", "signatures"):
            await expect(conn, f"UPDATE {table} SET id = id WHERE engagement_id = :e", "append-only", e=engagement)
            await expect(conn, f"DELETE FROM {table} WHERE engagement_id = :e", "append-only", e=engagement)
        for table in (
            "engagement_events",
            "engagement_endorsements",
            "signatures",
            "agreements",
            "milestones",
            "payment_records",
        ):
            await expect(conn, f"TRUNCATE {table} CASCADE", "append-only")
        assert await chain.verify_chain(conn, engagement) == []


PAYLOADS_REFUSED = (
    {"email": "alice@example.test"},
    {"reason": "not a priority for us this year"},
    {"url": "https://example.test/x"},
    {"Name": "x"},
    {"nested": {"text": "free text here"}},
    {"list": ["ok", "not ok"]},
    {"digest": "a" * 129},
    {"big": "a" * 128, "more": ["b" * 128] * 40},  # over 4 KB
)


async def test_event_payloads_hold_ids_codes_dates_amounts_and_digests_only(owner_engine: AsyncEngine) -> None:
    """docs/spec/06 6.4 item 4: no free text or personal data enters the chain (AC-IP-7)."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        await act(conn, p.reviewer, p.org)
        for payload in PAYLOADS_REFUSED:
            params = event_params(engagement, p.reviewer, "reviewer", "note", "SUBMITTED", "SUBMITTED", payload=payload)
            await expect(conn, APPEND, "ck_engagement_events_payload_holds_ids_and_codes", **params)
        accepted = {
            "internal_start_date": "2026-08-01",
            "attested": True,
            "amount_kes_minor": 25000000,
            "reason_digest": hashlib.sha256(b"why").hexdigest(),
            "tag_id": str(uuid7()),
            "at": "2026-09-29T10:00:00+03:00",
            "milestones": [{"seq": 1, "state": "PLANNED"}],
            "note": None,
        }
        await append(conn, engagement, p.reviewer, "reviewer", "note", "SUBMITTED", "SUBMITTED", payload=accepted)
        for command_name in ("Start review", "start-review", "x" * 41, ""):
            params = event_params(engagement, p.reviewer, "reviewer", command_name, "SUBMITTED", "SUBMITTED")
            await expect(conn, APPEND, "ck_engagement_events_command_is_a_code|value too long", **params)
        assert await chain.verify_chain(conn, engagement) == []


async def test_the_orm_maps_the_chain_and_the_version_counter(owner_engine: AsyncEngine) -> None:
    """ORM inserts leave the database's columns out and read them back; lock_version is a server-side version counter,
    so an update from a stale copy raises StaleDataError; after an append, a refresh shows the new projection."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        # A savepoint of its own, so the StaleDataError below rolls back only the session's work.
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        engagement = Engagement(
            proposal_id=p.proposal,
            org_id=p.org,
            developer_id=p.developer,
            version_id=p.version,
            origin=EngagementOrigin.TAGGED,
            state=EngagementState.SUBMITTED,
        )
        session.add(engagement)
        await session.flush()
        assert (engagement.lock_version, engagement.ended_at) == (0, None)
        assert engagement.stage_entered_at is not None

        await act(conn, p.reviewer, p.org)
        event = EngagementEvent(
            engagement_id=engagement.id,
            actor_user_id=p.reviewer,
            actor_role=EngagementActorRole.REVIEWER,
            command="start_review",
            from_state=EngagementState.SUBMITTED,
            to_state=EngagementState.UNDER_REVIEW,
            payload={},
        )
        session.add(event)
        await session.flush()
        assert (event.seq, len(event.hash), len(event.prev_hash)) == (2, 32, 32)
        stale_version = engagement.lock_version
        await session.refresh(engagement)
        assert (engagement.state, engagement.lock_version) == (EngagementState.UNDER_REVIEW, stale_version + 1)

        await act(conn, p.signatory, p.org)
        engagement.contact_user_id = p.owner
        engagement.contact_channel = ContactChannel.PHONE
        engagement.contact_by = date(2026, 12, 1)
        await session.flush()  # UPDATE ... WHERE lock_version = 1, the database bumps it
        assert engagement.lock_version == stale_version + 2
        # Someone else changed the row meanwhile: a flush from this copy finds no row at its version.
        await run(conn, "UPDATE engagements SET contact_channel = 'email' WHERE id = :e", e=engagement.id)
        engagement.contact_channel = ContactChannel.VIDEO_CALL
        with pytest.raises(StaleDataError):
            await session.flush()
        await session.rollback()
        await session.close()


# --- Concurrency and the upgrade (databases of their own: these tests commit) ---------------------------------------


@pytest.fixture
def scratch_url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_trk_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        yield url
    finally:
        drop_database(admin_url, name)


def _committed_engagement(conn: sa.Connection, *, state: str = "SUBMITTED", reason: str | None = None) -> UUID:
    """As the owner: a developer's engagement with an organisation, in ``state``; returns its id (the reviewer of the
    organisation is the engagement's org member ``reviewer_of``)."""
    developer, org, niche, proposal, version, engagement = (uuid7() for _ in range(6))
    run_sync = conn.execute
    run_sync(
        sa.text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Developer')"),
        {"id": developer, "email": f"{developer.hex}@example.test"},
    )
    run_sync(
        sa.text(
            "INSERT INTO organizations (id, kind, legal_name, slug, source, verification) VALUES (:id,"
            " 'company', 'Lock Ltd', :slug, 'seed', 'e2')"
        ),
        {"id": org, "slug": f"lock-{org.hex}"},
    )
    run_sync(
        sa.text("INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Lock')"),
        {"id": niche, "s": f"lock-{niche.hex}"},
    )
    run_sync(
        sa.text("INSERT INTO proposals (id, owner_id, title, niche_id) VALUES (:id, :o, 'Lock', :n)"),
        {"id": proposal, "o": developer, "n": niche},
    )
    run_sync(
        sa.text("INSERT INTO proposal_versions (id, proposal_id, version_no) VALUES (:id, :p, 1)"),
        {"id": version, "p": proposal},
    )
    run_sync(
        sa.text(
            "INSERT INTO engagements (id, proposal_id, org_id, developer_id, version_id, origin, state, end_reason)"
            " VALUES (:id, :p, :o, :d, :v, 'tagged', CAST(:state AS engagement_state),"
            " CAST(:reason AS engagement_end_reason))"
        ),
        {"id": engagement, "p": proposal, "o": org, "d": developer, "v": version, "state": state, "reason": reason},
    )
    return engagement


def _verify_sync(conn: sa.Connection, engagement: UUID) -> list[chain.ChainProblem]:
    rows = [chain.EventRow(*row) for row in conn.execute(chain.SELECT_CHAIN, {"engagement_id": engagement}).all()]
    return chain.verify_rows(rows) if rows else [chain.ChainProblem(0, None, "no event")]


def test_concurrent_appends_to_one_engagement_are_serialised(scratch_url: URL) -> None:
    """A second writer waits on the engagement's row lock; once the first commits, its append from the state the first
    event left behind is refused, and a fresh one links to the first event: seq stays gapless (1, 2, 3)."""
    run_alembic(scratch_url, lambda config: command.upgrade(config, "head"))
    engine = sa.create_engine(scratch_url, poolclass=sa.pool.NullPool)
    with engine.begin() as conn:
        conn.exec_driver_sql("SET LOCAL ROLE bridge_owner")
        engagement = _committed_engagement(conn)
    start_review = event_params(engagement, None, "system", "start_review", "SUBMITTED", "UNDER_REVIEW")
    errors: list[BaseException] = []
    pid: list[int] = []

    def second_writer() -> None:
        try:
            with engine.begin() as conn:  # commits on exit
                conn.exec_driver_sql("SET LOCAL ROLE bridge_owner")
                pid.append(conn.execute(sa.text("SELECT pg_backend_pid()")).scalar_one())
                conn.execute(sa.text(APPEND), start_review | {"id": uuid7()})
        except BaseException as exc:  # reported by the main thread
            errors.append(exc)

    blocked = sa.text("SELECT count(*) FROM pg_locks WHERE pid = :pid AND NOT granted")
    try:
        with engine.begin() as first:  # holds the engagement's row lock until it commits on exit
            first.exec_driver_sql("SET LOCAL ROLE bridge_owner")
            first.execute(sa.text(APPEND), start_review)
            thread = threading.Thread(target=second_writer)
            thread.start()
            deadline = time.monotonic() + 60
            waiting = False
            while not waiting and time.monotonic() < deadline and thread.is_alive():
                time.sleep(0.1)
                if pid:
                    waiting = bool(first.execute(blocked, {"pid": pid[0]}).scalar_one())
            assert waiting, "the second writer did not wait on the engagement's row lock"
        thread.join(timeout=60)
        assert not thread.is_alive()
        assert len(errors) == 1
        assert "the engagement is in state UNDER_REVIEW, not SUBMITTED" in str(errors[0])
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL ROLE bridge_owner")
            recommend = event_params(engagement, None, "system", "recommend", "UNDER_REVIEW", "UNDER_REVIEW")
            conn.execute(sa.text(APPEND), recommend)
        with engine.connect() as conn:
            seqs = (
                conn.execute(
                    sa.text("SELECT seq FROM engagement_events WHERE engagement_id = :e ORDER BY seq"),
                    {"e": engagement},
                )
                .scalars()
                .all()
            )
            assert seqs == [1, 2, 3]
            assert _verify_sync(conn, engagement) == []
    finally:
        engine.dispose()


def test_engagements_that_predate_the_revision_get_a_genesis_event(scratch_url: URL) -> None:
    """Upgrading a database whose engagements (fixtures) predate revision 0003: each gets a genesis event by the system
    (command import) recording its state and end reason; a terminal one is ended; every chain verifies; the next
    append links to it; the downgrade drops the tracker again and the upgrade after it starts over."""
    run_alembic(scratch_url, lambda config: command.upgrade(config, "0002"))
    engine = sa.create_engine(scratch_url, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL ROLE bridge_owner")
            submitted = _committed_engagement(conn)
            declined = _committed_engagement(conn, state="DECLINED", reason="BUDGET")
        run_alembic(scratch_url, lambda config: command.upgrade(config, "head"))
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL ROLE bridge_owner")
            imported = conn.execute(
                sa.text(
                    "SELECT e.id, v.seq, v.command, v.actor_user_id, v.actor_role::text AS role, v.to_state::text AS s,"
                    " v.end_reason::text AS reason, v.created_at = e.stage_entered_at AS timed, e.ended_at IS NOT NULL"
                    " AS ended, e.lock_version FROM engagements e JOIN engagement_events v ON v.engagement_id = e.id"
                )
            ).all()
            assert {tuple(row) for row in imported} == {
                (submitted, 1, "import", None, "system", "SUBMITTED", None, True, False, 0),
                (declined, 1, "import", None, "system", "DECLINED", "BUDGET", True, True, 0),
            }
            for engagement in (submitted, declined):
                assert _verify_sync(conn, engagement) == []
            conn.execute(
                sa.text(APPEND), event_params(submitted, None, "system", "start_review", "SUBMITTED", "UNDER_REVIEW")
            )
            assert _verify_sync(conn, submitted) == []
            assert (
                conn.execute(
                    sa.text("SELECT state::text FROM engagements WHERE id = :e"), {"e": submitted}
                ).scalar_one()
                == "UNDER_REVIEW"
            )
        run_alembic(scratch_url, lambda config: command.downgrade(config, "0002"))
        run_alembic(scratch_url, lambda config: command.upgrade(config, "head"))
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT count(*) FROM engagement_events")).scalar_one() == 2  # new genesis
    finally:
        engine.dispose()
