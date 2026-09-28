"""Provenance background jobs (REQ-PROV-01, REQ-AUD-01; docs/spec/06 6.4; ADR-003).

Registration steps (``bridge.provenance.service``), queued one after the other in the same transaction as each
step's writes, one version at a time (lock ``provenance:<version id>``), each idempotent:

- ``provenance.hash_manifest`` -> ``provenance.sign_manifest`` -> ``provenance.timestamp_manifest``.

Periodic: ``provenance.anchor_chain_heads`` hourly at minute 7 (RFC 3161 anchors of the audit chain heads). The nightly
``audit.verify_chain`` lives in ``bridge.jobs.audit``.

Retries: ``RegistrationError`` is permanent. Anything else (the database, the object store, an earlier version still
registering, the signing key not yet published) backs off exponentially. The timestamp step keeps trying for two weeks
(TSA outages): the record reads "Timestamp pending" meanwhile. A job that exhausts its retries stays ``failed`` in
``procrastinate_jobs``; re-run it with ``procrastinate --app=bridge.jobs.app.app`` (``retry`` in the shell) once the
cause is fixed: every step is idempotent.

The runtime (database, key wrapper, object store, signer, TSA client) is built from settings on first use; tests
install their own with ``use_runtime``.
"""

from __future__ import annotations

from uuid import UUID

from procrastinate import BaseRetryStrategy, RetryDecision
from procrastinate.jobs import Job
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.config import ConfigurationError, Settings, get_settings
from bridge.crypto.envelope import KeyWrapper, key_wrapper_from_settings
from bridge.db import create_engine, create_session_factory
from bridge.jobs.app import app
from bridge.provenance import service
from bridge.provenance.service import RegistrationError
from bridge.provenance.signing import Signer, signer_from_settings
from bridge.provenance.transparency import anchor_chain_heads as anchor_heads
from bridge.provenance.tsa import TsaClient, tsa_client_from_settings
from bridge.storage.objects import ObjectStore, object_store_from_settings

ANCHOR_TASK = "provenance.anchor_chain_heads"


class Backoff(BaseRetryStrategy):
    """``base * 2**attempts`` seconds, at most ``cap``; never after ``RegistrationError`` or ``max_attempts``."""

    def __init__(self, *, base: int, cap: int, max_attempts: int) -> None:
        self.base, self.cap, self.max_attempts = base, cap, max_attempts

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        if isinstance(exception, RegistrationError) or job.attempts >= self.max_attempts:
            return None
        return RetryDecision(retry_in={"seconds": min(self.cap, self.base * 2**job.attempts)})


STEP_RETRY = Backoff(base=30, cap=3600, max_attempts=12)  # about eight hours in all
TIMESTAMP_RETRY = Backoff(base=60, cap=3600, max_attempts=24 * 14)  # hourly for two weeks
ANCHOR_RETRY = Backoff(base=60, cap=600, max_attempts=3)  # the next hourly run catches up anyway


class ProvenanceRuntime:
    """What the provenance and audit jobs need. Each part is built from settings when first used, so a worker that
    never signs never needs the signing key; a missing setting fails closed (``ConfigurationError``)."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        wrapper: KeyWrapper | None = None,
        store: ObjectStore | None = None,
        signer: Signer | None = None,
        tsa: TsaClient | None = None,
        audit_engine: AsyncEngine | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._wrapper = wrapper
        self._store = store
        self._signer = signer
        self._tsa = tsa
        self._audit_engine = audit_engine

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            engine = create_engine(self.settings.database_url.get_secret_value())
            self._session_factory = create_session_factory(engine)
        return self._session_factory

    @property
    def wrapper(self) -> KeyWrapper:
        if self._wrapper is None:
            self._wrapper = key_wrapper_from_settings(self.settings)
        return self._wrapper

    @property
    def store(self) -> ObjectStore:
        if self._store is None:
            self._store = object_store_from_settings(self.settings)
        return self._store

    @property
    def signer(self) -> Signer:
        if self._signer is None:
            self._signer = signer_from_settings(self.settings)
        return self._signer

    @property
    def tsa(self) -> TsaClient:
        if self._tsa is None:
            self._tsa = tsa_client_from_settings(self.settings)
        return self._tsa

    @property
    def audit_engine(self) -> AsyncEngine:
        if self._audit_engine is None:
            url = self.settings.audit_reader_database_url
            if url is None:
                raise ConfigurationError("audit.verify_chain needs AUDIT_READER_DATABASE_URL (the audit_reader login)")
            self._audit_engine = create_engine(url.get_secret_value())
        return self._audit_engine


_runtime: ProvenanceRuntime | None = None


def runtime() -> ProvenanceRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ProvenanceRuntime()
    return _runtime


def use_runtime(value: ProvenanceRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


@app.task(name=service.TASK_HASH, queue=service.QUEUE, retry=STEP_RETRY)
async def hash_manifest(version_id: str, owner_id: str) -> None:
    rt = runtime()
    async with rt.session_factory() as session:
        await service.hash_manifest(session, UUID(version_id), UUID(owner_id), wrapper=rt.wrapper, store=rt.store)


@app.task(name=service.TASK_SIGN, queue=service.QUEUE, retry=STEP_RETRY)
async def sign_manifest(version_id: str, owner_id: str) -> None:
    rt = runtime()
    async with rt.session_factory() as session:
        await service.sign_manifest(session, UUID(version_id), UUID(owner_id), signer=rt.signer)


@app.task(name=service.TASK_TIMESTAMP, queue=service.QUEUE, retry=TIMESTAMP_RETRY)
async def timestamp_manifest(version_id: str, owner_id: str) -> None:
    rt = runtime()
    async with rt.session_factory() as session:
        await service.timestamp_manifest(session, UUID(version_id), UUID(owner_id), tsa=rt.tsa)


@app.periodic(cron="7 * * * *", periodic_id="hourly")
@app.task(name=ANCHOR_TASK, queue=service.QUEUE, retry=ANCHOR_RETRY)
async def anchor_chain_heads(timestamp: int) -> None:
    rt = runtime()
    async with rt.session_factory() as session:
        await anchor_heads(session, rt.tsa)
