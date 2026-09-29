"""REQ-SCOUT-01, REQ-SCOUT-02 (schema half; revision 0005): scouts, their runs and matches, and ``app_scouts_due``.

- ``scout_agents``: members read; only the organisation's owner or admin configures (as ``created_by``), and nobody
  of another organisation (a forged ``app.org_id`` included) reads or writes anything; the form is bounded (CHECKs);
  recipients are active reviewers of the organisation when the list is written (every role).
- ``agent_runs``: acting members (owner, admin, signatory, reviewer) start a running run and finish it; a failed run
  carries a code; nothing is deleted by the app; deleting a scout removes its runs and matches.
- ``agent_matches``: only for the current registered version of a published, clear proposal; once per scout and
  proposal; feedback as oneself.
- ``app_scouts_due``: the scan job only (no user bound); unpaused scouts of E1/E2 organisations that are not
  suspended, of the trigger's frequency, not already run in the Nairobi day or ISO week of ``p_now`` (a failed run may
  be retried), on_new only for a published, clear proposal not matched yet; returns the scout, its organisation and
  the member to act as (the creator while an active owner or admin, else the earliest one), nothing else.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration.schema_v4 import (
    Proposals,
    act,
    add_niche,
    add_org,
    add_user,
    as_app,
    as_owner,
    expect,
    member,
    proposals,
    rowcount,
    run,
    seats,
)

NAIROBI = ZoneInfo("Africa/Nairobi")
SCOUT = (
    "INSERT INTO scout_agents (id, org_id, niches, created_by, frequency, recipients, include_keywords, min_fit,"
    " language, counties, budget_band) VALUES (:id, :org, CAST(:niches AS uuid[]), :by,"
    " CAST(:frequency AS scout_frequency), CAST(:recipients AS uuid[]), CAST(:keywords AS text[]), :min_fit, :language,"
    " CAST(:counties AS text[]), :band)"
)
RUN = (
    "INSERT INTO agent_runs (id, scout_id, org_id, trigger, status, finished_at, error_code, window_end)"
    " VALUES (:id, :scout, :org, CAST(:trigger AS scout_frequency), CAST(:status AS agent_run_status), :finished,"
    " :error, now())"
)
MATCH = (
    "INSERT INTO agent_matches (id, scout_id, org_id, proposal_id, version_id, niche_id, score, rationale, feedback,"
    " feedback_by, feedback_at, digest_sent_at) VALUES (:id, :scout, :org, :proposal, :version, :niche, 70, :rationale,"
    " CAST(:feedback AS match_feedback), :feedback_by, :feedback_at, :digest)"
)
DUE = "SELECT scout_id, org_id, act_as_user_id FROM app_scouts_due(:now, CAST(:trigger AS scout_frequency), :proposal)"


def _array(values: list[Any]) -> str:
    return "{" + ",".join(str(v) for v in values) + "}"


def scout_params(org: UUID, by: UUID, niche: UUID, **overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "id": uuid7(),
        "org": org,
        "niches": _array([niche]),
        "by": by,
        "frequency": "weekly",
        "recipients": "{}",
        "keywords": "{}",
        "min_fit": 60,
        "language": "en",
        "counties": "{}",
        "band": None,
    }
    params.update(overrides)
    return params


def run_params(scout: UUID, org: UUID, **overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "id": uuid7(),
        "scout": scout,
        "org": org,
        "trigger": "weekly",
        "status": "running",
        "finished": None,
        "error": None,
    }
    params.update(overrides)
    return params


def match_params(scout: UUID, org: UUID, found: Proposals, **overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "id": uuid7(),
        "scout": scout,
        "org": org,
        "proposal": found.published,
        "version": found.published_version,
        "niche": found.niche,
        "rationale": "Matched on niche and keywords.",
        "feedback": None,
        "feedback_by": None,
        "feedback_at": None,
        "digest": None,
    }
    params.update(overrides)
    return params


async def _scout(conn: AsyncConnection, org: UUID, by: UUID, niche: UUID, **overrides: Any) -> UUID:
    """As the owner (no RLS, the triggers still run): a scout of ``org`` created by ``by``."""
    params = scout_params(org, by, niche, **overrides)
    await run(conn, SCOUT, **params)
    return UUID(str(params["id"]))


# --- scout_agents -------------------------------------------------------------------------------------------------


async def test_members_read_and_only_the_owner_or_admin_configures_a_scout(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        niche = await add_niche(conn)
        a, b = await seats(conn), await seats(conn)
        own = scout_params(a.org, a.owner, niche)
        await act(conn, a.owner, a.org)
        await run(conn, SCOUT, **own)
        await act(conn, a.admin)  # an admin, no org context: every organisation of theirs
        await run(conn, SCOUT, **scout_params(a.org, a.admin, niche))
        await expect(conn, SCOUT, "row-level security", **scout_params(a.org, a.owner, niche))  # not as themselves
        for role in (a.signatory, a.reviewer, a.finance, a.viewer):
            await act(conn, role)
            await expect(conn, SCOUT, "row-level security", **scout_params(a.org, role, niche))
            assert await run(conn, "SELECT count(*) FROM scout_agents WHERE org_id = :o", o=a.org) == 2  # members read
            assert await rowcount(conn, "UPDATE scout_agents SET min_fit = 70 WHERE org_id = :o", o=a.org) == 0
            assert await rowcount(conn, "DELETE FROM scout_agents WHERE org_id = :o", o=a.org) == 0
        # Another organisation's owner, and a's owner under a forged context, read and write nothing of a's.
        for user, context in ((b.owner, None), (b.owner, a.org), (a.owner, b.org)):
            await act(conn, user, context)
            assert await run(conn, "SELECT count(*) FROM scout_agents WHERE org_id = :o", o=a.org) == 0
            assert await rowcount(conn, "UPDATE scout_agents SET paused_at = now() WHERE org_id = :o", o=a.org) == 0
            assert await rowcount(conn, "DELETE FROM scout_agents WHERE org_id = :o", o=a.org) == 0
            await expect(conn, SCOUT, "row-level security", **scout_params(a.org, user, niche))
        await act(conn, a.owner, a.org)
        paused = "UPDATE scout_agents SET paused_at = now(), min_fit = 55, frequency = 'daily' WHERE id = :id"
        assert await rowcount(conn, paused, id=own["id"]) == 1
        await expect(
            conn, "UPDATE scout_agents SET created_by = :u WHERE id = :id", "permission denied", u=a.admin, id=own["id"]
        )
        assert await rowcount(conn, "DELETE FROM scout_agents WHERE id = :id", id=own["id"]) == 1


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("niches", "{}", "niches_valid"),
        ("niches", "six", "niches_valid"),
        ("niches", "twice", "niches_valid"),
        ("niches", "{NULL}", "niches_valid"),
        ("keywords", "{" + "x" * 61 + "}", "include_keywords_valid"),
        ("keywords", _array([f"k{i}" for i in range(21)]), "include_keywords_valid"),
        ("keywords", '{" "}', "include_keywords_valid"),
        ("keywords", "{a,a}", "include_keywords_valid"),
        ("counties", "{KE-123456}", "counties_valid"),
        ("min_fit", 101, "min_fit_range"),
        ("min_fit", -1, "min_fit_range"),
        ("language", "fr", "language_known"),
        ("band", "Big Budget", "budget_band_code"),
    ],
)
async def test_the_scout_form_is_bounded(owner_engine: AsyncEngine, column: str, value: Any, constraint: str) -> None:
    """Niches 1 to 5 distinct ids, keywords at most 20 distinct of at most 60 characters, counties short codes,
    min_fit 0-100, language en or sw, a budget band code: refused by CHECK for the app role."""
    async with as_app(owner_engine) as conn:
        niche = await add_niche(conn)
        a = await seats(conn)
        others = [await add_niche(conn) for _ in range(5)]
        value = {"six": _array([niche, *others]), "twice": _array([niche, niche])}.get(value, value)
        await act(conn, a.owner, a.org)
        await expect(conn, SCOUT, constraint, **scout_params(a.org, a.owner, niche, **{column: value}))
        await run(conn, SCOUT, **scout_params(a.org, a.owner, niche, niches=_array([niche, *others[:4]])))


async def test_recipients_are_active_reviewers_of_the_organisation(owner_engine: AsyncEngine) -> None:
    """AC-SCOUT-7 (schema half): the owner or admin picks recipients among the organisation's active reviewers; a
    viewer, an owner without the reviewer role, a removed reviewer or another organisation's reviewer is refused, for
    every role (the owner's own inserts too)."""
    async with as_app(owner_engine) as conn:
        niche = await add_niche(conn)
        a, b = await seats(conn), await seats(conn)
        removed = await add_user(conn, "removed")
        await member(conn, a.org, removed, "{reviewer}", status="removed")
        await act(conn, a.owner, a.org)
        scout = scout_params(a.org, a.owner, niche, recipients=_array([a.reviewer]))
        await run(conn, SCOUT, **scout)
        for outsider in (a.viewer, a.owner, removed, b.reviewer):
            await expect(
                conn,
                SCOUT,
                "every recipient is an active reviewer",
                **scout_params(a.org, a.owner, niche, recipients=_array([a.reviewer, outsider])),
            )
            await expect(
                conn,
                "UPDATE scout_agents SET recipients = CAST(:r AS uuid[]) WHERE id = :id",
                "every recipient is an active reviewer",
                r=_array([outsider]),
                id=scout["id"],
            )
        assert await rowcount(conn, "UPDATE scout_agents SET recipients = '{}' WHERE id = :id", id=scout["id"]) == 1
        await as_owner(conn)
        await expect(
            conn,
            SCOUT,
            "every recipient is an active reviewer",
            **scout_params(a.org, a.owner, niche, recipients=_array([b.reviewer])),
        )


# --- agent_runs ---------------------------------------------------------------------------------------------------


async def test_runs_are_written_by_acting_members_and_never_deleted(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        niche = await add_niche(conn)
        a, b = await seats(conn), await seats(conn)
        scout = await _scout(conn, a.org, a.owner, niche)
        for actor in (a.owner, a.admin, a.signatory, a.reviewer):
            await act(conn, actor, a.org)
            await run(conn, RUN, **run_params(scout, a.org))
        for idle in (a.finance, a.viewer):  # members who see the scout but do not act for it
            await act(conn, idle)
            await expect(conn, RUN, "row-level security", **run_params(scout, a.org))
        await act(conn, b.owner, b.org)  # another organisation cannot file a run under a's scout by naming its own
        for params in (run_params(scout, b.org), run_params(scout, a.org), run_params(uuid7(), b.org)):
            await expect(conn, RUN, "no scout of the caller's with that id", **params)
        await act(conn, a.reviewer, a.org)
        for status, error in (("completed", None), ("failed", "llm_unavailable")):
            params = run_params(scout, a.org, status=status, finished=datetime.now(NAIROBI), error=error)
            await expect(conn, RUN, "row-level security", **params)  # a run starts running
        running = run_params(scout, a.org)
        await run(conn, RUN, **running)
        started = await run(
            conn,
            "SELECT started_at BETWEEN app_clock_now() - interval '1 minute' AND app_clock_now() FROM agent_runs"
            " WHERE id = :id",
            id=running["id"],
        )
        assert started is True  # the database's clock (app_clock_now(), which follows the test clock)
        failed = "UPDATE agent_runs SET status = 'failed', finished_at = now(), error_code = :code WHERE id = :id"
        await expect(conn, failed, "error_code_when_failed", code="The LLM said: no", id=running["id"])
        await expect(conn, failed.replace(", error_code = :code", ""), "error_code_when_failed", id=running["id"])
        await expect(
            conn,
            "UPDATE agent_runs SET status = 'completed' WHERE id = :id",
            "finished_unless_running",
            id=running["id"],
        )
        assert await rowcount(conn, failed, code="llm_unavailable", id=running["id"]) == 1
        await expect(conn, "DELETE FROM agent_runs WHERE id = :id", "permission denied", id=running["id"])
        await act(conn, b.owner, None)
        assert await run(conn, "SELECT count(*) FROM agent_runs WHERE org_id = :o", o=a.org) == 0
        assert await rowcount(conn, "UPDATE agent_runs SET scanned_count = 9 WHERE org_id = :o", o=a.org) == 0


# --- agent_matches ------------------------------------------------------------------------------------------------


async def test_matches_name_the_current_version_of_a_published_clear_proposal(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        niche = await add_niche(conn)
        a, b = await seats(conn), await seats(conn)
        found = await proposals(conn, niche)
        scout = await _scout(conn, a.org, a.owner, niche)
        next_version = uuid7()  # a newer draft version of the published proposal: never the matched one
        await run(
            conn,
            "INSERT INTO proposal_versions (id, proposal_id, version_no) VALUES (:id, :p, 2)",
            id=next_version,
            p=found.published,
        )
        await act(conn, a.reviewer, a.org)
        refused = (
            {"proposal": found.draft, "version": found.draft_version},  # a draft: invisible, never matched
            {"proposal": found.held, "version": found.held_version},  # held by moderation
            {"version": next_version},  # not the current version
            {"digest": datetime.now(NAIROBI)},  # a match starts undelivered
            {"feedback": "relevant", "feedback_by": a.reviewer, "feedback_at": datetime.now(NAIROBI)},  # and unjudged
        )
        for overrides in refused:
            await expect(conn, MATCH, "row-level security", **match_params(scout, a.org, found, **overrides))
        await act(conn, a.viewer, a.org)
        await expect(conn, MATCH, "row-level security", **match_params(scout, a.org, found))
        await act(conn, a.reviewer, a.org)
        match = match_params(scout, a.org, found)
        await run(conn, MATCH, **match)
        await expect(conn, MATCH, "uq_agent_matches_scout_id_proposal_id", **match_params(scout, a.org, found))
        await expect(
            conn,
            MATCH,
            "rationale_length",
            **match_params(scout, a.org, found, proposal=found.published, rationale="x" * 601, id=uuid7()),
        )
        judge = (
            "UPDATE agent_matches SET feedback = 'not_relevant', feedback_reason = :reason, feedback_by = :by,"
            " feedback_at = now() WHERE id = :id"
        )
        await expect(conn, judge, "a feedback is given as oneself", reason="off_niche", by=a.owner, id=match["id"])
        await expect(conn, judge, "feedback_complete", reason="Not for us!", by=a.reviewer, id=match["id"])
        assert await rowcount(conn, judge, reason="off_niche", by=a.reviewer, id=match["id"]) == 1
        sent = "UPDATE agent_matches SET digest_sent_at = now() WHERE id = :id"
        assert await rowcount(conn, sent, id=match["id"]) == 1
        await act(conn, b.owner, None)
        assert await run(conn, "SELECT count(*) FROM agent_matches WHERE org_id = :o", o=a.org) == 0
        assert await rowcount(conn, sent, id=match["id"]) == 0
        # a's scout under b's name, or a's: one refusal, the same as for no scout (never "a's scout matched this").
        await act(conn, b.owner, b.org)
        for scout_id, org_id in ((scout, b.org), (scout, a.org), (uuid7(), b.org)):
            await expect(conn, MATCH, "no scout of the caller's with that id", **match_params(scout_id, org_id, found))


async def test_a_feedback_is_changed_or_cleared_only_by_its_author(owner_engine: AsyncEngine) -> None:
    """Another acting member (or the owner role) neither overwrites nor clears a reviewer's feedback, but still records
    the digest time; the author changes and clears their own; a cleared feedback is anyone's to give again."""
    async with as_app(owner_engine) as conn:
        niche = await add_niche(conn)
        a = await seats(conn)
        found = await proposals(conn, niche)
        scout = await _scout(conn, a.org, a.owner, niche)
        match = match_params(scout, a.org, found)
        await run(conn, MATCH, **match)
        judge = (
            "UPDATE agent_matches SET feedback = CAST(:f AS match_feedback), feedback_reason = NULL,"
            " feedback_by = :by, feedback_at = now() WHERE id = :id"
        )
        clear = (
            "UPDATE agent_matches SET feedback = NULL, feedback_reason = NULL, feedback_by = NULL, feedback_at = NULL"
            " WHERE id = :id"
        )
        await act(conn, a.reviewer, a.org)
        assert await rowcount(conn, judge, f="relevant", by=a.reviewer, id=match["id"]) == 1
        await act(conn, a.owner, a.org)
        await expect(conn, judge, "only the member who gave a feedback", f="not_relevant", by=a.owner, id=match["id"])
        await expect(conn, clear, "only the member who gave a feedback", id=match["id"])
        assert (
            await rowcount(conn, "UPDATE agent_matches SET digest_sent_at = now() WHERE id = :id", id=match["id"]) == 1
        )
        await as_owner(conn)
        await expect(conn, clear, "only the member who gave a feedback", id=match["id"])
        await act(conn, a.reviewer, a.org)
        assert await rowcount(conn, judge, f="not_relevant", by=a.reviewer, id=match["id"]) == 1
        assert await rowcount(conn, clear, id=match["id"]) == 1
        await act(conn, a.owner, a.org)
        assert await rowcount(conn, judge, f="relevant", by=a.owner, id=match["id"]) == 1


async def test_deleting_a_scout_removes_its_runs_and_matches(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        niche = await add_niche(conn)
        a = await seats(conn)
        found = await proposals(conn, niche)
        scout = await _scout(conn, a.org, a.owner, niche)
        await run(conn, RUN, **run_params(scout, a.org))
        await run(conn, MATCH, **match_params(scout, a.org, found))
        await act(conn, a.admin, a.org)
        assert await rowcount(conn, "DELETE FROM scout_agents WHERE id = :id", id=scout) == 1
        for table in ("agent_runs", "agent_matches"):
            assert await run(conn, f"SELECT count(*) FROM {table} WHERE scout_id = :s", s=scout) == 0


# --- app_scouts_due -----------------------------------------------------------------------------------------------


async def _due(
    conn: AsyncConnection, now: datetime, trigger: str, proposal: UUID | None = None
) -> set[tuple[UUID, ...]]:
    return {
        tuple(row)
        for row in (await conn.execute(sa.text(DUE), {"now": now, "trigger": trigger, "proposal": proposal})).all()
    }


async def test_due_scouts_are_asked_for_by_the_scan_job_only(owner_engine: AsyncEngine) -> None:
    """Refused while a user is bound (a request learns nothing of other organisations' scouts), and for a missing time
    or trigger, an on_new scan without its proposal or a scheduled one with one. It returns three columns."""
    async with as_app(owner_engine) as conn:
        a = await seats(conn)
        niche = await add_niche(conn)
        found = await proposals(conn, niche)
        now = datetime.now(NAIROBI)
        for user in (a.owner, found.developer):
            await act(conn, user, a.org)
            await expect(conn, DUE, "the scouts.scan job only", now=now, trigger="daily", proposal=None)
        await act(conn, None)
        for bad in (
            {"now": None, "trigger": "daily", "proposal": None},
            {"now": now, "trigger": None, "proposal": None},
            {"now": now, "trigger": "on_new", "proposal": None},
            {"now": now, "trigger": "weekly", "proposal": found.published},
        ):
            await expect(conn, DUE, "name the time and the trigger", **bad)
        result = await conn.execute(sa.text(DUE), {"now": now, "trigger": "daily", "proposal": None})
        assert list(result.keys()) == ["scout_id", "org_id", "act_as_user_id"]
        columns = await run(
            conn,
            "SELECT pg_get_function_result(to_regprocedure('app_scouts_due(timestamptz, scout_frequency, uuid)'))",
        )
        assert columns == "TABLE(scout_id uuid, org_id uuid, act_as_user_id uuid)"


async def test_only_active_scouts_of_verified_unsuspended_organisations_are_due(owner_engine: AsyncEngine) -> None:
    """E1 and E2 organisations only (pending, unclaimed and rejected configure and preview), never a suspended one; a
    paused scout or one of another frequency is not due; an organisation without an active owner or admin has nobody
    to act as."""
    async with as_app(owner_engine) as conn:
        niche = await add_niche(conn)
        now = datetime.now(NAIROBI)
        expected: set[tuple[UUID, ...]] = set()
        mine: set[UUID] = set()
        for verification, suspended in (
            ("e2", False),
            ("e1", False),
            ("pending", False),
            ("unclaimed", False),
            ("rejected", False),
            ("e2", True),
            ("e1", True),
        ):
            org = await seats(conn, verification, suspended=suspended)
            daily = await _scout(conn, org.org, org.owner, niche, frequency="daily")
            if verification in ("e1", "e2") and not suspended:
                expected.add((daily, org.org, org.owner))
            weekly = await _scout(conn, org.org, org.owner, niche, frequency="weekly")
            paused = await _scout(conn, org.org, org.owner, niche, frequency="daily")
            await run(conn, "UPDATE scout_agents SET paused_at = now() WHERE id = :id", id=paused)
            mine |= {daily, weekly, paused}
        # Nobody to act as: the only owner is a suspended user, the only admin's membership is removed.
        lonely = await add_org(conn, "e2")
        suspended_owner = await add_user(conn, "suspended", status="suspended")
        removed_admin = await add_user(conn, "gone")
        await member(conn, lonely, suspended_owner, "{owner,admin}")
        await member(conn, lonely, removed_admin, "{admin}", status="removed")
        mine.add(await _scout(conn, lonely, suspended_owner, niche, frequency="daily"))
        await act(conn, None)
        assert {row for row in await _due(conn, now, "daily") if row[0] in mine} == expected
        assert len(expected) == 2


async def test_the_scout_acts_as_its_creator_while_an_owner_or_admin_else_the_earliest_one(
    owner_engine: AsyncEngine,
) -> None:
    async with as_app(owner_engine) as conn:
        niche = await add_niche(conn)
        a = await seats(conn)
        now = datetime.now(NAIROBI)
        scout = await _scout(conn, a.org, a.admin, niche, frequency="daily")
        await act(conn, None)
        assert await _due(conn, now, "daily") >= {(scout, a.org, a.admin)}
        await as_owner(conn)
        await run(
            conn, "UPDATE memberships SET roles = '{reviewer}' WHERE org_id = :o AND user_id = :u", o=a.org, u=a.admin
        )
        await act(conn, None)
        assert (scout, a.org, a.owner) in await _due(conn, now, "daily")  # demoted: the earliest owner or admin
        await as_owner(conn)
        await run(
            conn, "UPDATE memberships SET status = 'removed' WHERE org_id = :o AND user_id = :u", o=a.org, u=a.owner
        )
        await act(conn, None)
        assert not {row for row in await _due(conn, now, "daily") if row[0] == scout}  # nobody left to act as


async def test_a_scheduled_scout_is_due_once_per_nairobi_day_or_week(owner_engine: AsyncEngine) -> None:
    """AC-SCOUT-6 (schema half): a daily scout that ran (or is running) today is not due again today, and is due the
    next Nairobi day; a weekly one once per ISO week; a failed run may be retried; runs are timed by the database's
    clock, which the job passes as p_now (the test clock)."""
    async with as_app(owner_engine) as conn:
        niche = await add_niche(conn)
        a = await seats(conn)
        daily = await _scout(conn, a.org, a.owner, niche, frequency="daily")
        weekly = await _scout(conn, a.org, a.owner, niche, frequency="weekly")
        monday = datetime(2026, 10, 5, 10, 0, tzinfo=NAIROBI)
        timed = "UPDATE agent_runs SET started_at = :at WHERE id = :id"

        async def ran(scout: UUID, trigger: str, at: datetime, status: str = "completed") -> None:
            params = run_params(
                scout,
                a.org,
                trigger=trigger,
                status=status,
                finished=None if status == "running" else at,
                error="llm_unavailable" if status == "failed" else None,
            )
            await as_owner(conn)
            await run(conn, RUN, **params)
            await run(conn, timed, at=at, id=params["id"])

        async def due(scout: UUID, trigger: str, at: datetime) -> bool:
            await act(conn, None)
            return any(row[0] == scout for row in await _due(conn, at, trigger))

        assert await due(daily, "daily", monday)
        await ran(daily, "daily", monday, "failed")
        assert await due(daily, "daily", monday + timedelta(hours=1))  # a failed run may be retried
        await ran(daily, "daily", monday, "running")
        assert not await due(daily, "daily", monday + timedelta(hours=13, minutes=59))  # 23:59 Nairobi
        assert await due(daily, "daily", monday + timedelta(hours=14))  # 00:00 Tuesday Nairobi
        assert await due(weekly, "weekly", monday)
        await ran(weekly, "weekly", monday)
        assert not await due(weekly, "weekly", monday + timedelta(days=6, hours=13))  # Sunday 23:00 Nairobi
        assert await due(weekly, "weekly", monday + timedelta(days=6, hours=14))  # the next Monday
        assert not await due(daily, "weekly", monday + timedelta(days=7))  # frequencies never mix


async def test_an_on_new_scout_is_due_once_for_a_published_clear_proposal(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        niche = await add_niche(conn)
        a = await seats(conn)
        found = await proposals(conn, niche)
        on_new = await _scout(conn, a.org, a.owner, niche, frequency="on_new")
        daily = await _scout(conn, a.org, a.owner, niche, frequency="daily")
        now = datetime.now(NAIROBI)

        async def scouts_for(proposal: UUID) -> set[UUID]:
            await act(conn, None)
            return {row[0] for row in await _due(conn, now, "on_new", proposal)} & {on_new, daily}

        assert await scouts_for(found.published) == {on_new}
        for hidden in (found.draft, found.held, uuid7()):
            assert await scouts_for(hidden) == set()
        await as_owner(conn)
        await run(conn, MATCH, **match_params(on_new, a.org, found))
        assert await scouts_for(found.published) == set()  # matched already: each proposal once (AC-SCOUT-6)
