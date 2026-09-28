"""Nightly audit verification (REQ-AUD-01 Phase 2; docs/spec/06 6.4 item 4).

``audit.verify_chain`` runs at 00:30 Nairobi time (21:30 UTC; Procrastinate's cron is UTC). It verifies every audit
chain as ``audit_reader`` (``AUDIT_READER_DATABASE_URL``) and, when all verify, publishes the signed Merkle root of
the chain heads for the Nairobi day that just ended (``bridge.provenance.transparency``). A broken chain publishes
nothing, logs ``audit.chain_broken`` and fails the job, so it is visible in ``procrastinate_jobs``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from bridge.engagements.calendar import NAIROBI
from bridge.jobs.app import app
from bridge.jobs.provenance import runtime
from bridge.provenance.transparency import verify_and_publish_root

VERIFY_TASK = "audit.verify_chain"


def closing_day(timestamp: int) -> date:
    """The Nairobi calendar day that ended before ``timestamp`` (the run just after midnight closes yesterday)."""
    return datetime.fromtimestamp(timestamp, UTC).astimezone(NAIROBI).date() - timedelta(days=1)


@app.periodic(cron="30 21 * * *", periodic_id="nightly")
@app.task(name=VERIFY_TASK, queue="audit")
async def verify_chain(timestamp: int) -> None:
    rt = runtime()
    async with rt.session_factory() as session:
        await verify_and_publish_root(rt.audit_engine, session, rt.signer, closing_day(timestamp))
