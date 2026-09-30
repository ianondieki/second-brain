"""P16-E1 item 5 (REQ-FND-01, docs/spec/08 p95 budgets): the staff console's queues send as many statements with
many rows as with few (``tests/integration/query_counts.py``): the moderation queue (open and decided), the claims
queue and the research queue (candidates and runs)."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.matching import trend_world as tw
from tests.integration.proposals.helpers import ProposalWorld, Staff, user_of
from tests.integration.query_counts import LARGE, SMALL, counted


async def test_the_moderation_queue(
    moderators: Staff, proposal_world: ProposalWorld, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Cases about proposals and problems, open and decided, dated ahead of every other test's (and removed after):
    the queue lists at most 200, oldest first."""
    moderator = await moderators()
    mine: list[UUID] = []

    async def file(count: int) -> None:
        """``count`` subjects, every other one a problem, each with an open and a decided case."""
        async with owner_engine.begin() as conn:
            author = await w.add_user(conn, f"qc-{uuid4().hex[:8]}@example.test", "Author")
            niche, problem = proposal_world.niche_id, proposal_world.problem_id
            for n in range(count):
                if n % 2:
                    kind, subject = "problem", await w.add_problem(conn, author, niche, moderation_state="held")
                else:
                    kind = "proposal"
                    subject, _ = await w.add_proposal(conn, author, niche, problem, moderation_state="held")
                for status in ("open", "approved"):
                    mine.append(uuid7())
                    await conn.execute(
                        text(
                            "INSERT INTO moderation_cases (id, subject_type, subject_id, reasons, source, status,"
                            " created_at, decided_at, decided_by) VALUES (:id, :kind, :subject,"
                            " ARRAY['names_real_org_negative'], 'regex', CAST(:status AS moderation_case_status),"
                            " '2000-01-01', CASE WHEN :status = 'approved' THEN now() END,"
                            " CASE WHEN :status = 'approved' THEN CAST(:staff AS uuid) END)"
                        ),
                        {
                            "id": mine[-1],
                            "kind": kind,
                            "subject": subject,
                            "status": status,
                            "staff": user_of(moderator),
                        },
                    )

    try:
        await file(SMALL)
        small = [
            await counted(moderator, app_engine, "/api/admin/moderation/cases", {"decided": d})
            for d in ("false", "true")
        ]
        await file(LARGE - SMALL)
        large = [
            await counted(moderator, app_engine, "/api/admin/moderation/cases", {"decided": d})
            for d in ("false", "true")
        ]
        open_ids = {item["id"] for item in large[0][1]["items"]}
        assert len(open_ids & set(map(str, mine))) == LARGE
        assert [count for count, _ in large] == [count for count, _ in small]
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(text("DELETE FROM moderation_cases WHERE id = ANY(:ids)"), {"ids": mine})


async def test_the_claims_queue(moderators: Staff, owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    admin = await moderators(role="admin")
    tag = uuid4().hex[:8]

    async def claim(count: int, start: int) -> None:
        async with owner_engine.begin() as conn:
            for n in range(start, start + count):
                org_id, claimant = uuid7(), await w.add_user(conn, f"claimant-{n}-{tag}@example.test", f"Claimant {n}")
                domain = f"claims-{n}-{tag}.example.test"
                await conn.execute(
                    text(
                        "INSERT INTO organizations (id, kind, legal_name, slug, source, verification)"
                        " VALUES (:id, 'company', :name, :slug, 'admin', 'unclaimed')"
                    ),
                    {"id": org_id, "name": f"Claimed {n} {tag}", "slug": f"claimed-{n}-{tag}"},
                )
                await conn.execute(
                    text(
                        "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status)"
                        " VALUES (:id, :org, :user, :domain, :email, 'e1', 'pending_review')"
                    ),
                    {"id": uuid7(), "org": org_id, "user": claimant, "domain": domain, "email": f"it@{domain}"},
                )

    await claim(SMALL, 0)
    small, body = await counted(admin, app_engine, "/api/admin/claims")
    mine = len([c for c in body["items"] if c["org"]["legal_name"] and tag in c["org"]["legal_name"]])
    assert mine == SMALL
    await claim(LARGE - SMALL, SMALL)
    large, body = await counted(admin, app_engine, "/api/admin/claims")
    assert len([c for c in body["items"] if c["org"]["legal_name"] and tag in c["org"]["legal_name"]]) == LARGE
    assert large == small


async def test_the_research_queue(moderators: Staff, owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    admin = await moderators(role="admin")
    world = await tw.build(owner_engine)
    mine: list[UUID] = []

    async def draft(count: int) -> None:
        for n in range(count):
            mine.append(
                await tw.research_card(owner_engine, world.niche, status="candidate", source_days=(n + 1.0, n + 2.0))
            )
            async with owner_engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO research_runs (id, niche_id, county_code, started_by, status, finished_at,"
                        " stop_reason) VALUES (:id, :niche, NULL, :by, 'completed', now(), NULL)"
                    ),
                    {"id": uuid7(), "niche": world.niche, "by": user_of(admin)},
                )

    await draft(SMALL)
    small = [await counted(admin, app_engine, f"/api/admin/research/{path}") for path in ("candidates", "runs")]
    await draft(LARGE - SMALL)
    large = [await counted(admin, app_engine, f"/api/admin/research/{path}") for path in ("candidates", "runs")]
    assert set(map(str, mine)) <= {c["id"] for c in large[0][1]["items"]}
    assert [count for count, _ in large] == [count for count, _ in small]
