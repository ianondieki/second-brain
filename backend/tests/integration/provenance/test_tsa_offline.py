"""REQ-PROV-02 over REQ-PROV-01's pipeline: the TSA offline, for real on loopback (no mock transport).

A TSA that refuses the connection, or accepts it and never answers within the attempt's deadline, leaves the signed
version without a token: ``/api/verify`` and the owner's certificate read "Timestamp pending", the timestamp job's retry
strategy schedules another attempt, and a later retry against a TSA that answers stores the token, after which both
read "Timestamped" with the TSA's serial. (The HTTP 503 outage is ``test_registration.py``'s.)
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from procrastinate.jobs import Job
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.crypto.envelope import LocalKeyWrapper
from bridge.jobs.app import app
from bridge.jobs.provenance import TIMESTAMP_RETRY
from bridge.models.enums import ProvenanceStatus
from bridge.provenance import service
from bridge.provenance.service import hash_manifest, sign_manifest, timestamp_manifest
from bridge.provenance.signing import LocalSigner
from bridge.provenance.tsa import TsaClient, TsaEndpoint, TsaUnavailableError
from bridge.storage.objects import InMemoryObjectStore
from tests.integration.api import sign_in_as
from tests.integration.proposals.helpers import rows
from tests.integration.provenance.builders import Built, registered_version
from tests.integration.provenance.test_verify_api import client
from tests.unit.provenance.test_certificate import pdf_text

Sessions = async_sessionmaker[AsyncSession]


@asynccontextmanager
async def offline_tsa(kind: str) -> AsyncIterator[TsaClient]:
    """A TSA client whose only URL is a loopback port that refuses connections (bound, never listening), or one that
    accepts and never answers (the attempt's one-second deadline ends it)."""
    if kind == "connection-refused":
        with socket.socket() as bound:
            bound.bind(("127.0.0.1", 0))  # held for the test, so no other process can listen there meanwhile
            port = bound.getsockname()[1]
            yield TsaClient([TsaEndpoint(f"http://127.0.0.1:{port}/tsr", None)], timeout=5.0, deadline=5.0)
        return
    silent: list[asyncio.StreamWriter] = []

    async def never_answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        silent.append(writer)
        try:
            await reader.read()  # reads the request, answers nothing, until the client gives up
        finally:
            writer.close()

    server = await asyncio.start_server(never_answer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield TsaClient([TsaEndpoint(f"http://127.0.0.1:{port}/tsr", None)], timeout=30.0, deadline=1.0)
    finally:
        # Whatever the test body did, even failing with the client's connection still open: close every connection
        # first (Server.wait_closed waits for them), then the server, bounded, so a regression fails fast instead of
        # holding the suite to CI's timeout.
        for writer in silent:
            writer.close()
        server.close()
        async with asyncio.timeout(5):
            await server.wait_closed()


async def evidence(app_engine: AsyncEngine, kek: bytes, built: Built) -> tuple[dict[str, Any], str]:
    """What anyone sees at /api/verify, and the owner's certificate PDF as text."""
    async with client(app_engine, kek) as c:
        public = await c.get(f"/api/verify/{built.cert_id}")
        await sign_in_as(c, app_engine, built.owner_id, mfa_verified=True)
        pdf = await c.get(f"/api/provenance/certificates/{built.cert_id}/certificate.pdf")
    assert (public.status_code, pdf.status_code) == (200, 200), (public.text, pdf.status_code)
    body: dict[str, Any] = public.json()
    return body, pdf_text(pdf.content)


@pytest.mark.parametrize("kind", ["connection-refused", "timeout"])
async def test_an_offline_tsa_leaves_timestamp_pending_and_a_later_retry_fills_it(
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
    kek: bytes,
    kind: str,
) -> None:
    built = await registered_version(owner_engine, wrapper, attachments=0)
    async with sessions() as s:
        await hash_manifest(s, built.version_id, built.owner_id, wrapper=wrapper, store=store)
    async with sessions() as s:
        await sign_manifest(s, built.version_id, built.owner_id, signer=signer)

    async with offline_tsa(kind) as down, sessions() as s:
        with pytest.raises(TsaUnavailableError, match="no TSA returned a valid token") as failed:
            await timestamp_manifest(s, built.version_id, built.owner_id, tsa=down)
    timed_out = "no answer within the 1 s deadline" in str(failed.value)
    assert timed_out is (kind == "timeout")  # refused at once, or cut off by the attempt's deadline
    # The timestamp job retries it later (a minute on the first attempt, growing, for two weeks), not failed for good:
    # the strategy attached to the task itself, and its decision for this very error.
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    strategy = app.tasks[service.TASK_TIMESTAMP].retry_strategy
    assert strategy is TIMESTAMP_RETRY
    job = Job(queue=service.QUEUE, lock=None, queueing_lock=None, task_name=service.TASK_TIMESTAMP)
    assert strategy.get_retry_decision(exception=failed.value, job=job) is not None

    sql = "SELECT status, tsa_token, tsa_serial FROM provenance_records WHERE version_id = :v"
    [record] = await rows(owner_engine, sql, v=built.version_id)
    assert (record.status, record.tsa_token, record.tsa_serial) == (ProvenanceStatus.SIGNED, None, None)
    public, certificate = await evidence(app_engine, kek, built)
    assert (public["status_label"], public["timestamp"], public["tsa_serial"]) == ("Timestamp pending", None, None)
    assert "Timestamp pending" in certificate
    assert "Timestamped" not in certificate

    async with sessions() as s:  # the later retry: the TSA answers again
        assert await timestamp_manifest(s, built.version_id, built.owner_id, tsa=tsa) is True
    [record] = await rows(owner_engine, sql, v=built.version_id)
    assert record.status == ProvenanceStatus.TIMESTAMPED
    assert record.tsa_token is not None
    public, certificate = await evidence(app_engine, kek, built)
    assert (public["status_label"], public["tsa_serial"]) == ("Timestamped", record.tsa_serial)
    assert public["timestamp"] is not None
    assert "Timestamp pending" not in certificate
    assert record.tsa_serial in certificate
