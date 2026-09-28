"""Provenance integration fixtures: a local openssl test TSA, a throwaway signing key registered in
``provenance_keys``, a throwaway key encryption key, an in-memory evidence store, and the job runtime wired to them."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.crypto.envelope import LocalKeyWrapper
from bridge.db import create_session_factory
from bridge.jobs.provenance import ProvenanceRuntime, use_runtime
from bridge.provenance.signing import LocalSigner, register_public_key
from bridge.provenance.tsa import TsaClient
from bridge.storage.objects import InMemoryObjectStore
from tests.openssl_tsa import LocalTsa

TSA_URL = "http://tsa.test/tsr"


@pytest.fixture(scope="session")
def local_tsa(tmp_path_factory: pytest.TempPathFactory) -> LocalTsa:
    return LocalTsa.create(tmp_path_factory.mktemp("tsa"))


@pytest.fixture(scope="session")
def kek() -> bytes:
    return os.urandom(32)


@pytest.fixture(scope="session")
def wrapper(kek: bytes) -> LocalKeyWrapper:
    return LocalKeyWrapper(kek)


@pytest.fixture(scope="session")
async def signer(owner_engine: AsyncEngine) -> LocalSigner:
    signer = LocalSigner(os.urandom(32))
    async with owner_engine.begin() as conn:
        await register_public_key(conn, signer)
    return signer


@pytest.fixture
def store() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest.fixture
def tsa(local_tsa: LocalTsa) -> TsaClient:
    return TsaClient([local_tsa.endpoint(TSA_URL)], transport=local_tsa.transport())


@pytest.fixture
def sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(app_engine)


@pytest.fixture
async def runtime(
    sessions: async_sessionmaker[AsyncSession],
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
) -> AsyncIterator[ProvenanceRuntime]:
    rt = ProvenanceRuntime(session_factory=sessions, wrapper=wrapper, store=store, signer=signer, tsa=tsa)
    use_runtime(rt)
    yield rt
    use_runtime(None)
