"""REQ-PROP-01 / REQ-REPO-01 (docs/spec/06 6.1): Tier-2 fields and attachment names never appear in a Tier-1
response (teaser, lists, publish, the problem picker, the moderation queue), in a log line (the whole flow, the
registration pipeline included), in an audit payload, a moderation case, a job's arguments or a signal."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from bridge.crypto.envelope import LocalKeyWrapper
from bridge.provenance.signing import LocalSigner
from bridge.provenance.tsa import TsaClient
from bridge.storage.objects import InMemoryObjectStore
from tests.integration.proposals.helpers import (
    TIER2_MARKERS,
    Developers,
    ProposalWorld,
    Staff,
    create,
    draft_body,
    publish,
    rows,
    user_of,
)
from tests.integration.proposals.test_attachments import PDF, upload
from tests.integration.proposals.test_publish import run_pipeline

SECRET_FILE = "TIER2-SECRET-deck.pdf"


def assert_clean(text: str, where: str) -> None:
    for marker in TIER2_MARKERS:
        assert marker not in text, f"Tier-2 text in {where}"


async def test_tier2_never_reaches_tier1_responses_logs_or_audit(
    developers: Developers,
    moderators: Staff,
    proposal_world: ProposalWorld,
    owner_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
) -> None:
    owner = await developers(wrapper=wrapper)
    reader = await developers(level="d0")
    moderator = await moderators()
    with capture_logs() as logs:
        body = draft_body(proposal_world, summary=f"Unlike the corrupt {proposal_world.org_brand}, we report outages.")
        body["new_problem"] = {"title": "Gateways fail quietly", "statement": "Nobody hears when a gateway dies."}
        created = await create(owner, body)
        pid = created["id"]
        assert (await upload(owner, pid, PDF, name=SECRET_FILE)).status_code == 201
        saved = await owner.patch(f"/api/me/proposals/{pid}", json={"confidential": {"notes": "TIER2-SECRET-notes"}})
        assert saved.status_code == 200
        published = await publish(owner, pid)
        assert published.status_code == 200
        assert published.json()["moderation"]["state"] == "held"
        await run_pipeline(UUID(published.json()["version_id"]), user_of(owner), sessions, wrapper, store, signer, tsa)
        queue = await moderator.get("/api/admin/moderation/cases")
        [case] = [c for c in queue.json()["items"] if c["subject_id"] == pid]
        approved = await moderator.post(
            f"/api/admin/moderation/cases/{case['id']}/decision", json={"decision": "approve"}
        )
        tier1 = {
            "publish": published.text,
            "teaser": (await reader.get(f"/api/proposals/{pid}")).text,
            "my list": (await owner.get("/api/me/proposals")).text,
            "picker": (await reader.get("/api/problems", params={"niche": proposal_world.niche_slug})).text,
            "moderation queue": queue.text,
            "decision": approved.text,
            "verify": (await reader.get(f"/api/verify/{published.json()['cert_id']}")).text,
        }
    assert json.loads(tier1["teaser"])["id"] == pid
    for where, text in tier1.items():
        assert_clean(text, where)
    assert_clean(repr(logs), "logs")

    # The owner's own detail is where Tier 2 is shown.
    mine = (await owner.get(f"/api/me/proposals/{pid}")).text
    assert "TIER2-SECRET-notes" in mine
    assert SECRET_FILE in mine

    audit = await rows(owner_engine, "SELECT payload FROM audit_events WHERE actor_user_id = :u", u=user_of(owner))
    details = await rows(
        owner_engine,
        "SELECT d.details FROM event_details d JOIN audit_events e ON e.id = d.event_id WHERE e.actor_user_id = :u",
        u=user_of(owner),
    )
    cases = await rows(owner_engine, "SELECT reasons, classifier FROM moderation_cases WHERE subject_id = :p", p=pid)
    jobs_sql = "SELECT args FROM procrastinate_jobs WHERE args->>'owner_id' = :u"
    jobs = await rows(owner_engine, jobs_sql, u=str(user_of(owner)))
    signals = await rows(owner_engine, "SELECT * FROM signal_events WHERE item_id = :p", p=pid)
    for where, found in {"audit": audit, "details": details, "cases": cases, "jobs": jobs, "signals": signals}.items():
        assert found or where == "details", where
        assert_clean(repr([tuple(r) for r in found]), where)
