"""Nightly audit verification (REQ-AUD-01 Phase 2; docs/spec/06 6.4 item 4).

``audit.verify_chain`` runs at 00:30 Nairobi time (21:30 UTC; Procrastinate's cron is UTC). It verifies every audit
chain as ``audit_reader`` (``AUDIT_READER_DATABASE_URL``) and, when all verify, publishes the signed Merkle root of
the chain heads for the Nairobi day that just ended (``bridge.provenance.transparency``). A broken chain publishes
nothing, logs ``audit.chain_broken`` and fails the job at once, so it is visible in ``procrastinate_jobs``; transient
failures are retried with a bounded backoff (``VERIFY_RETRY``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from bridge.config import ConfigurationError
from bridge.engagements.calendar import NAIROBI
from bridge.jobs.app import app
from bridge.jobs.provenance import Backoff, runtime
from bridge.provenance.transparency import ChainVerificationError, verify_and_publish_root

VERIFY_TASK = "audit.verify_chain"
# A transient failure (a dropped connection, the database restarting, a signer timeout) is retried six times over
# about 45 minutes (60 s doubling, at most 15 min apart); the same day is closed on every retry, and publishing is
# idempotent per day. A broken chain or a missing setting fails the job at once: no retry could publish a root.
VERIFY_RETRY = Backoff(base=60, cap=900, max_attempts=6, permanent=(ChainVerificationError, ConfigurationError))


def closing_day(timestamp: int) -> date:
    """The Nairobi calendar day that ended before ``timestamp`` (the run just after midnight closes yesterday)."""
    return datetime.fromtimestamp(timestamp, UTC).astimezone(NAIROBI).date() - timedelta(days=1)


@app.periodic(cron="30 21 * * *", periodic_id="nightly")
@app.task(name=VERIFY_TASK, queue="audit", retry=VERIFY_RETRY)
async def verify_chain(timestamp: int) -> None:
    rt = runtime()
    async with rt.session_factory() as session:
        await verify_and_publish_root(rt.audit_engine, session, rt.signer, closing_day(timestamp))
